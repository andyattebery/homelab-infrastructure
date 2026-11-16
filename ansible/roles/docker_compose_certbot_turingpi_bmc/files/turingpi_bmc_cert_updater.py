"""Reconcile the certificate a Turing Pi 2 BMC serves with the one certbot holds on disk.

Stock firmware has no certificate API. bmcd reads its pair once, in main, before it serves anything,
so the only install is to replace the files over ssh and restart the daemon:

  * read the leaf serial from cert-file on disk
  * read the serial the BMC actually serves, over TLS, not via its own API
  * equal -> do nothing at all
  * different -> check the pair, back up what is there, write the new pair, restart bmcd, then
    re-probe until the served serial matches
  * never served -> put the previous pair back and restart bmcd again

The pair is checked here first because load_tls_config runs in bmcd's main: a pair it cannot load
stops the daemon, which takes the web UI, the API and tpi with it. sshd is a separate process, so
that stays recoverable, which is what the rollback relies on.

A restart does not touch the nodes on a v2.5 board with stock firmware. That was measured, and it
does not hold on a v2.4 board, where bmcd's start drives the enable lines. See the role's README.

Exit codes: 0 in sync (or brought into sync), 1 install attempted and did not converge, or refused,
2 the BMC could not be probed - deliberately not an install, since each one restarts bmcd and a
permanently broken probe would otherwise do that nightly forever.
"""

import argparse
import configparser
import datetime
import os
import socket
import ssl
import subprocess
import sys
import time

from cryptography import x509
from cryptography.hazmat.primitives import serialization

# The two files S94bmcd generates when they are missing, and that config.yaml points at by default.
# Installing over them leaves config.yaml alone. Deleting both and restarting restores a self-signed
# pair.
REMOTE_CERT = "/etc/ssl/certs/bmcd_cert.pem"
REMOTE_KEY = "/etc/ssl/certs/bmcd_key.pem"

# Redirected because S94bmcd starts bmcd with --no-close: it would otherwise inherit the ssh channel's
# stdout and stderr, and ssh would never return.
RESTART_BMCD = "/etc/init.d/S94bmcd restart </dev/null >/dev/null 2>&1"

DEFAULT_PORT = 443
SSH_CONNECT_TIMEOUT = 15
SSH_COMMAND_TIMEOUT = 60

# How long to keep re-probing after a restart. The first probes are expected to fail.
VERIFY_TIMEOUT = 180
VERIFY_INTERVAL = 10

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNREACHABLE = 2

REQUIRED_KEYS = ("rhost", "key-file", "cert-file", "known-hosts-file", "username", "password")


class ConfigError(Exception):
    """The ini is missing, malformed, or missing a value, or the pair on disk is unusable."""


class BmcError(Exception):
    """The BMC answered, but not with what was asked for."""


class Config:
    def __init__(self, host, port, key_file, cert_file, known_hosts_file, username, password):
        self.host = host
        self.port = port
        self.key_file = key_file
        self.cert_file = cert_file
        self.known_hosts_file = known_hosts_file
        self.username = username
        self.password = password


def load_config(path):
    """Parse the ini into a Config, naming whatever is wrong."""
    # interpolation=None because a % in the password is a value, not a substitution.
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with open(path, encoding="utf-8") as handle:
            parser.read_file(handle)
    except OSError as exc:
        raise ConfigError("cannot read config file %s: %s" % (path, exc)) from exc
    except configparser.Error as exc:
        raise ConfigError("malformed config file %s: %s" % (path, exc)) from exc

    values = {}
    for key in REQUIRED_KEYS:
        value = parser["DEFAULT"].get(key, "").strip()
        if not value:
            raise ConfigError("config file %s is missing a value for '%s'" % (path, key))
        values[key] = value

    rhost = values["rhost"].rstrip("/")
    if "://" not in rhost:
        raise ConfigError("rhost must include a scheme, e.g. https://bmc.example - got '%s'" % rhost)
    authority = rhost.split("://", 1)[1]
    host, _, port = authority.partition(":")
    if not host:
        raise ConfigError("rhost has no hostname: '%s'" % rhost)

    for key in ("key-file", "cert-file"):
        if not values[key].endswith(".pem"):
            raise ConfigError("%s must be a PEM file, got '%s'" % (key, values[key]))

    return Config(
        host=host,
        port=int(port) if port else DEFAULT_PORT,
        key_file=values["key-file"],
        cert_file=values["cert-file"],
        known_hosts_file=values["known-hosts-file"],
        username=values["username"],
        password=values["password"],
    )


def serial_from_pem(data):
    """Serial of the first certificate in a PEM bundle.

    cert-file is fullchain.pem, so the bundle holds the leaf followed by the intermediates.
    load_pem_x509_certificate returns the first, which is the leaf. bmcd's X509::from_pem reads the
    same one and serves nothing else.
    """
    return x509.load_pem_x509_certificate(data).serial_number


def serial_from_der(data):
    return x509.load_der_x509_certificate(data).serial_number


def read_disk_serial(cert_file):
    try:
        with open(cert_file, "rb") as handle:
            return serial_from_pem(handle.read())
    except OSError as exc:
        raise ConfigError("cannot read certificate %s: %s" % (cert_file, exc)) from exc
    except ValueError as exc:
        raise ConfigError("%s is not a valid PEM certificate: %s" % (cert_file, exc)) from exc


def _public_der(holder):
    return holder.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def check_pair(cert_file, key_file, now):
    """Raise ConfigError unless the key belongs to the certificate and it has not expired."""
    try:
        with open(cert_file, "rb") as handle:
            certificate = x509.load_pem_x509_certificate(handle.read())
        with open(key_file, "rb") as handle:
            key = serialization.load_pem_private_key(handle.read(), password=None)
    except OSError as exc:
        raise ConfigError("cannot read the pair on disk: %s" % exc) from exc
    except (TypeError, ValueError) as exc:
        # Not the exception's text: it is about the key file, and it is not worth the risk.
        raise ConfigError("%s or %s is not valid PEM" % (cert_file, key_file)) from exc

    if _public_der(certificate) != _public_der(key):
        raise ConfigError("%s does not belong to %s" % (key_file, cert_file))
    if certificate.not_valid_after_utc <= now:
        raise ConfigError(
            "%s expired on %s" % (cert_file, certificate.not_valid_after_utc.isoformat())
        )


def probe_served_serial(host, port, timeout):
    """Serial of the certificate the BMC is serving right now.

    Verification is off on purpose: stock serves a self-signed pair until the first install, and the
    leaf alone after it, with no intermediates to build a chain from.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        raise BmcError("%s:%d completed a handshake but presented no certificate" % (host, port))
    return serial_from_der(der)


class BmcSession:
    """The ssh calls an install needs. Each is its own connection."""

    def __init__(self, config):
        self._config = config

    def _ssh(self, action, command, stdin=None):
        argv = [
            "sshpass",
            "-e",
            "ssh",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "UserKnownHostsFile=%s" % self._config.known_hosts_file,
            "-o",
            "ConnectTimeout=%d" % SSH_CONNECT_TIMEOUT,
            "-o",
            "PreferredAuthentications=password",
            "-o",
            "PubkeyAuthentication=no",
            "%s@%s" % (self._config.username, self._config.host),
            command,
        ]
        # In the environment, because anything in argv is visible in the process list.
        env = dict(os.environ, SSHPASS=self._config.password)
        try:
            result = subprocess.run(
                argv,
                input=stdin,
                env=env,
                capture_output=True,
                timeout=SSH_COMMAND_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BmcError("%s timed out after %d s" % (action, SSH_COMMAND_TIMEOUT)) from exc
        if result.returncode != 0:
            stderr = " ".join(result.stderr.decode("utf-8", "replace").split())[:200]
            raise BmcError("%s failed (exit %d): %s" % (action, result.returncode, stderr))

    def backup(self):
        self._ssh(
            "backup",
            "cp -p %s %s.prev && cp -p %s %s.prev" % (REMOTE_CERT, REMOTE_CERT, REMOTE_KEY, REMOTE_KEY),
        )

    def upload(self):
        """Write the pair beside the live one, which leaves bmcd's files untouched if this fails."""
        with open(self._config.cert_file, "rb") as handle:
            cert_data = handle.read()
        with open(self._config.key_file, "rb") as handle:
            key_data = handle.read()
        self._ssh("certificate upload", "cat > %s.new" % REMOTE_CERT, cert_data)
        self._ssh("key upload", "umask 077 && cat > %s.new" % REMOTE_KEY, key_data)

    def activate(self):
        self._ssh(
            "activate",
            "mv %s.new %s && mv %s.new %s && %s"
            % (REMOTE_CERT, REMOTE_CERT, REMOTE_KEY, REMOTE_KEY, RESTART_BMCD),
        )

    def rollback(self):
        self._ssh(
            "rollback",
            "cp -p %s.prev %s && cp -p %s.prev %s && %s"
            % (REMOTE_CERT, REMOTE_CERT, REMOTE_KEY, REMOTE_KEY, RESTART_BMCD),
        )


def _verify(config, probe, sleep, want, log):
    """Re-probe until the BMC serves `want`, or VERIFY_TIMEOUT elapses.

    bmcd drops its listener while it restarts, so early failures here are normal and are not the
    answer.
    """
    waited = 0
    while True:
        try:
            served = probe(config.host, config.port, VERIFY_INTERVAL)
            if served == want:
                return True
            log("BMC serving %s, waiting" % format(served, "X"))
        except (OSError, ssl.SSLError, BmcError) as exc:
            log("BMC not answering yet (%s)" % exc)
        if waited >= VERIFY_TIMEOUT:
            return False
        sleep(VERIFY_INTERVAL)
        waited += VERIFY_INTERVAL


def reconcile(config, *, probe, session_factory, sleep, now, log=print):
    """Bring the BMC's certificate in line with the one on disk. Returns an exit code."""
    disk_serial = read_disk_serial(config.cert_file)
    log("certificate on disk: serial %s" % format(disk_serial, "X"))

    try:
        served_serial = probe(config.host, config.port, VERIFY_INTERVAL)
    except (OSError, ssl.SSLError, BmcError) as exc:
        log("cannot probe %s:%d - %s" % (config.host, config.port, exc))
        return EXIT_UNREACHABLE
    log("certificate on BMC:  serial %s" % format(served_serial, "X"))

    if served_serial == disk_serial:
        log("already current, nothing to do")
        return EXIT_OK

    try:
        check_pair(config.cert_file, config.key_file, now)
    except ConfigError as exc:
        log("refusing to install: %s" % exc)
        return EXIT_FAILED

    log("installing")
    session = session_factory(config)
    try:
        session.backup()
        session.upload()
    except (BmcError, OSError) as exc:
        log("install failed, bmcd untouched: %s" % exc)
        return EXIT_FAILED

    # Not returned on: an ssh call that dies during the restart can still have restarted bmcd, so the
    # probe decides.
    try:
        session.activate()
    except (BmcError, OSError) as exc:
        log("activate reported a failure: %s" % exc)

    if _verify(config, probe, sleep, disk_serial, log):
        log("BMC now serving serial %s" % format(disk_serial, "X"))
        return EXIT_OK

    log("BMC never served the new certificate, restoring the previous pair")
    try:
        session.rollback()
    except (BmcError, OSError) as exc:
        log("rollback failed: %s" % exc)
        return EXIT_FAILED
    if _verify(config, probe, sleep, served_serial, log):
        log("BMC back on serial %s" % format(served_serial, "X"))
    else:
        log("BMC is not serving the previous certificate either")
    return EXIT_FAILED


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Reconcile a Turing Pi 2 BMC's certificate with the one on disk"
    )
    parser.add_argument("--config-file", required=True, help="ini with rhost, credentials and paths")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config_file)
        return reconcile(
            config,
            probe=probe_served_serial,
            session_factory=BmcSession,
            sleep=time.sleep,
            now=datetime.datetime.now(datetime.timezone.utc),
        )
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
