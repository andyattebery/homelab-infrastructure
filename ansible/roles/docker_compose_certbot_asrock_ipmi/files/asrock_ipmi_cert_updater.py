"""Reconcile the certificate an ASRock Rack BMC serves with the one certbot holds on disk.

Derived from khung/letsencrypt-scripts@1b1cef96. What is kept from upstream is the ASRock API
surface, which is not Redfish and is not documented anywhere else — someone reverse engineered it:

  * POST /api/session  with {username, password, certlogin: 0}  -> {"CSRFToken": ...}
  * that token echoed back as the X-CSRFTOKEN header; the QSESSIONID cookie rides the session
  * GET and POST both live on /api/settings/ssl/certificate - the method is what distinguishes
    reading the current certificate from installing a new one
  * the upload is multipart with field names new_certificate / new_private_key
  * TLS verification is off throughout, because the certificate being replaced is frequently the
    expired one we are here to fix
  * logout has to follow the upload within about two seconds or it fails, apparently because
    installing a certificate soft-resets the BMC web service

Everything else is rewritten. Upstream ran only as a certbot --deploy-hook, so it fired once per
renewal and never checked its work; a single timeout left the BMC on a stale certificate until the
next renewal ~60 days later. This runs every cycle instead and is driven by a comparison:

  * read the leaf serial from cert-file on disk
  * read the serial the BMC actually serves, over TLS, not via its own JSON API
  * equal -> do nothing at all
  * different -> upload, then re-probe until the served serial matches or the attempts run out

Exit codes: 0 in sync (or brought into sync), 1 upload attempted and did not converge,
2 the BMC could not be probed - deliberately not an upload, since installing a certificate bounces
the web service and a permanently broken probe would otherwise do that nightly forever.
"""

import argparse
import configparser
import json
import socket
import ssl
import sys
import time

import requests
from cryptography import x509

LOGIN_PATH = "/api/session"
CERTIFICATE_PATH = "/api/settings/ssl/certificate"

DEFAULT_TIMEOUT = 60
DEFAULT_ATTEMPTS = 3
DEFAULT_PORT = 443

# How long to keep re-probing after an upload. Installing a certificate soft-resets the BMC web
# service, so the first probes after an upload are expected to fail.
VERIFY_TIMEOUT = 180
VERIFY_INTERVAL = 10

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNREACHABLE = 2

REQUIRED_KEYS = ("rhost", "key-file", "cert-file", "username", "password")


class ConfigError(Exception):
    """The ini is missing, malformed, or missing a value."""


class BmcError(Exception):
    """The BMC answered, but not with what was asked for."""


class Config:
    def __init__(self, rhost, host, port, key_file, cert_file, username, password):
        self.rhost = rhost
        self.host = host
        self.port = port
        self.key_file = key_file
        self.cert_file = cert_file
        self.username = username
        self.password = password


def load_config(path):
    """Parse the ini into a Config, naming whatever is wrong.

    Upstream indexed config['DEFAULT'] directly, so a missing key surfaced as a bare KeyError with
    no indication of which file it came from.
    """
    parser = configparser.ConfigParser()
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
        rhost=rhost,
        host=host,
        port=int(port) if port else DEFAULT_PORT,
        key_file=values["key-file"],
        cert_file=values["cert-file"],
        username=values["username"],
        password=values["password"],
    )


def serial_from_pem(data):
    """Serial of the first certificate in a PEM bundle.

    cert-file is fullchain.pem, so the bundle holds the leaf followed by the intermediates.
    load_pem_x509_certificate returns the first, which is the leaf - the one the BMC will serve.
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


def probe_served_serial(host, port, timeout):
    """Serial of the certificate the BMC is serving right now.

    Verification is off on purpose: the whole point is to look at a certificate that is very often
    expired, and hostname checking would reject a self-signed BMC default too.
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


def _describe(response):
    """A one-line summary of an unexpected response.

    Upstream threw the response away and printed "Login failed!", which is the same message for a
    wrong password, a 500, and an HTML error page from a captive portal.
    """
    body = " ".join((response.text or "").split())[:200]
    return "HTTP %d%s" % (response.status_code, ": %s" % body if body else "")


class BmcSession:
    """The three calls this needs, in the order the BMC insists on."""

    def __init__(self, config, timeout):
        self._config = config
        self._timeout = timeout
        self._session = requests.Session()
        self._session.verify = False

    def login(self):
        response = self._session.post(
            self._config.rhost + LOGIN_PATH,
            data={
                "username": self._config.username,
                "password": self._config.password,
                "certlogin": 0,
            },
            timeout=self._timeout,
        )
        if not response.ok:
            raise BmcError("login rejected (%s)" % _describe(response))
        try:
            token = json.loads(response.text)["CSRFToken"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise BmcError("login response carried no CSRF token (%s)" % _describe(response)) from exc
        # Never logged, never echoed in an error - it is a session credential.
        self._session.headers.update({"X-CSRFTOKEN": token})

    def upload(self):
        with open(self._config.cert_file, "rb") as handle:
            cert_data = handle.read()
        with open(self._config.key_file, "rb") as handle:
            key_data = handle.read()
        response = self._session.post(
            self._config.rhost + CERTIFICATE_PATH,
            files=[
                ("new_certificate", ("cert.pem", cert_data, "application/octet-stream")),
                ("new_private_key", ("key.pem", key_data, "application/octet-stream")),
            ],
            timeout=self._timeout,
        )
        if not response.ok:
            raise BmcError("certificate upload rejected (%s)" % _describe(response))

    def logout(self):
        """Best effort. Must be the very next call after upload - see the module docstring."""
        try:
            self._session.delete(self._config.rhost + LOGIN_PATH, timeout=self._timeout)
        except requests.exceptions.RequestException:
            pass

    def close(self):
        self._session.close()


def _verify(config, probe, sleep, want, log):
    """Re-probe until the BMC serves `want`, or VERIFY_TIMEOUT elapses.

    The BMC drops its web service while installing the certificate, so early failures here are
    normal and are not the answer.
    """
    waited = 0
    while True:
        try:
            served = probe(config.host, config.port, VERIFY_INTERVAL)
            if served == want:
                return True
            log("BMC still serving %s, waiting" % format(served, "X"))
        except (OSError, ssl.SSLError, BmcError) as exc:
            log("BMC not answering yet (%s)" % exc)
        if waited >= VERIFY_TIMEOUT:
            return False
        sleep(VERIFY_INTERVAL)
        waited += VERIFY_INTERVAL


def reconcile(config, *, probe, session_factory, sleep, attempts, force=False, log=print):
    """Bring the BMC's certificate in line with the one on disk. Returns an exit code."""
    disk_serial = read_disk_serial(config.cert_file)
    log("certificate on disk: serial %s" % format(disk_serial, "X"))

    try:
        served_serial = probe(config.host, config.port, VERIFY_INTERVAL)
    except (OSError, ssl.SSLError, BmcError) as exc:
        log("cannot probe %s:%d - %s" % (config.host, config.port, exc))
        return EXIT_UNREACHABLE
    log("certificate on BMC:  serial %s" % format(served_serial, "X"))

    if served_serial == disk_serial and not force:
        log("already current, nothing to do")
        return EXIT_OK

    for attempt in range(1, attempts + 1):
        log("uploading (attempt %d of %d)" % (attempt, attempts))
        session = session_factory(config)
        try:
            session.login()
            session.upload()
            # Immediately, before any verification round-trip. Upstream put a full cert-info GET in
            # between and blew the two-second window it documented itself.
            session.logout()
        except (requests.exceptions.RequestException, BmcError, OSError) as exc:
            log("upload failed: %s" % exc)
            session.close()
            if attempt < attempts:
                sleep(VERIFY_INTERVAL)
            continue
        session.close()

        if _verify(config, probe, sleep, disk_serial, log):
            log("BMC now serving serial %s" % format(disk_serial, "X"))
            return EXIT_OK
        log("upload succeeded but the BMC never served the new certificate")

    return EXIT_FAILED


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Reconcile an ASRock Rack BMC's certificate with the one on disk"
    )
    parser.add_argument("--config-file", required=True, help="ini with rhost, credentials and paths")
    parser.add_argument(
        "--force",
        action="store_true",
        help="upload even when the BMC already serves the certificate on disk",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="per-request timeout in seconds (default %d; the BMC login is slow)" % DEFAULT_TIMEOUT,
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=DEFAULT_ATTEMPTS,
        help="upload attempts before giving up (default %d)" % DEFAULT_ATTEMPTS,
    )
    args = parser.parse_args(argv)

    requests.packages.urllib3.disable_warnings(
        requests.packages.urllib3.exceptions.InsecureRequestWarning
    )

    try:
        config = load_config(args.config_file)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_FAILED

    return reconcile(
        config,
        probe=probe_served_serial,
        session_factory=lambda cfg: BmcSession(cfg, args.timeout),
        sleep=time.sleep,
        attempts=args.attempts,
        force=args.force,
    )


if __name__ == "__main__":
    sys.exit(main())
