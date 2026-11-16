"""Guards for the Turing Pi BMC certificate reconciler.

    cd ansible && .venv/bin/pytest roles/docker_compose_certbot_turingpi_bmc/tests/ -q

Hermetic: no BMC, no sockets, no sleeping. The TLS probe and the ssh session are injected, and the
ssh boundary itself runs against a fake subprocess.run.

Most of these exist because of what a wrong install costs here. Every install restarts bmcd, and a
pair bmcd cannot load stops it, so an install must be refused early and must be able to undo itself.
"""

import datetime
import importlib.util
import ssl
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

SCRIPT = Path(__file__).resolve().parents[1] / "files" / "turingpi_bmc_cert_updater.py"


def _load():
    assert SCRIPT.exists(), "script missing at %s" % SCRIPT
    spec = importlib.util.spec_from_file_location("_turingpi_updater_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # The script lives in an Ansible files/ directory. Writing bytecode would drop a __pycache__
    # there, next to a file the role copies to a container.
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


updater = _load()

DISK_SERIAL = 0x5A9ABB
OLD_SERIAL = 0x050AE5
PASSWORD_SENTINEL = "hunter2%do-not-print"
KEY_MARKER = b"PRIVATE KEY"
NOW = datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)


# --------------------------------------------------------------------------- fixtures


def _make_cert(serial, common_name, key=None, days=90):
    key = key or ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(serial)
        .not_valid_before(start)
        .not_valid_after(start + datetime.timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    return cert, key


def _pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM)


def _key_pem(key):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


@pytest.fixture
def bmc(tmp_path):
    """An ini plus the cert and key it points at, with a known leaf serial."""
    leaf, key = _make_cert(DISK_SERIAL, "bmc.example")
    intermediate, _ = _make_cert(0xDEADBEEF, "Intermediate CA")

    cert_file = tmp_path / "fullchain.pem"
    cert_file.write_bytes(_pem(leaf) + _pem(intermediate))
    key_file = tmp_path / "privkey.pem"
    key_file.write_bytes(_key_pem(key))

    ini = tmp_path / "updater.ini"
    ini.write_text(
        "[DEFAULT]\n"
        "rhost = https://bmc.example\n"
        "key-file = %s\n"
        "cert-file = %s\n"
        "known-hosts-file = %s\n"
        "username = root\n"
        "password = %s\n" % (key_file, cert_file, tmp_path / "known_hosts", PASSWORD_SENTINEL)
    )
    return updater.load_config(str(ini))


class FakeSession:
    """Records the calls reconcile makes, in order."""

    def __init__(self, calls, fail_on=None):
        self.calls = calls
        self.fail_on = fail_on

    def _call(self, name):
        self.calls.append(name)
        if name == self.fail_on:
            raise updater.BmcError("%s failed" % name)

    def backup(self):
        self._call("backup")

    def upload(self):
        self._call("upload")

    def activate(self):
        self._call("activate")

    def rollback(self):
        self._call("rollback")


def constant_probe(serial):
    return lambda host, port, timeout: serial


def sequence_probe(*results):
    """Each result in turn, then the last one forever. An exception instance is raised."""
    remaining = list(results)

    def probe(host, port, timeout):
        result = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(result, Exception):
            raise result
        return result

    return probe


def run(bmc, probe, calls, *, fail_on=None, now=NOW, log=lambda *_: None):
    return updater.reconcile(
        bmc,
        probe=probe,
        session_factory=lambda config: FakeSession(calls, fail_on),
        sleep=lambda _: None,
        now=now,
        log=log,
    )


# --------------------------------------------------------------------------- reconcile behaviour


def test_matching_serial_touches_nothing(bmc):
    """Nearly every cycle lands here, and an install restarts bmcd."""
    calls = []
    assert run(bmc, constant_probe(DISK_SERIAL), calls) == updater.EXIT_OK
    assert calls == []


def test_unreachable_bmc_touches_nothing(bmc):
    """A permanently broken probe must not turn into a nightly restart."""

    def probe(host, port, timeout):
        raise OSError("no route to host")

    calls = []
    assert run(bmc, probe, calls) == updater.EXIT_UNREACHABLE
    assert calls == []


def test_mismatch_backs_up_before_anything_else(bmc):
    calls = []
    probe = sequence_probe(OLD_SERIAL, DISK_SERIAL)
    assert run(bmc, probe, calls) == updater.EXIT_OK
    assert calls == ["backup", "upload", "activate"]


def test_verify_tolerates_the_daemon_restart(bmc):
    """bmcd drops its listener while it restarts, so early post-install probes failing is normal."""
    calls = []
    probe = sequence_probe(
        OLD_SERIAL,
        ConnectionRefusedError("refused"),
        ssl.SSLError("handshake failed"),
        DISK_SERIAL,
    )
    assert run(bmc, probe, calls) == updater.EXIT_OK
    assert "rollback" not in calls


def test_never_served_rolls_back(bmc):
    """A bmcd that will not come back on the new pair must get the old one back."""
    calls = []
    assert run(bmc, constant_probe(OLD_SERIAL), calls) == updater.EXIT_FAILED
    assert calls == ["backup", "upload", "activate", "rollback"]


def test_rollback_restarts_at_most_once_per_cycle(bmc):
    """Two restarts is the ceiling: one for the install, one for the rollback."""
    calls = []
    run(bmc, constant_probe(OLD_SERIAL), calls)
    assert calls.count("activate") == 1
    assert calls.count("rollback") == 1


def test_rollback_that_fails_is_reported(bmc):
    calls = []
    lines = []
    code = run(bmc, constant_probe(OLD_SERIAL), calls, fail_on="rollback", log=lines.append)
    assert code == updater.EXIT_FAILED
    assert any("rollback failed" in line for line in lines)


def test_rollback_that_never_serves_is_reported(bmc):
    """The BMC is left on neither certificate, and that has to be said."""
    calls = []
    lines = []
    probe = sequence_probe(OLD_SERIAL, 0x123456)
    assert run(bmc, probe, calls, log=lines.append) == updater.EXIT_FAILED
    assert any("not serving the previous certificate" in line for line in lines)


@pytest.mark.parametrize("step", ["backup", "upload"])
def test_failure_before_activate_leaves_bmcd_alone(bmc, step):
    """Nothing live has changed at this point, so there is nothing to restart or restore."""
    calls = []
    assert run(bmc, constant_probe(OLD_SERIAL), calls, fail_on=step) == updater.EXIT_FAILED
    assert "activate" not in calls
    assert "rollback" not in calls


def test_activate_error_is_not_the_verdict(bmc):
    """ssh can die during the restart that worked. The probe decides, not the exit code."""
    calls = []
    probe = sequence_probe(OLD_SERIAL, DISK_SERIAL)
    assert run(bmc, probe, calls, fail_on="activate") == updater.EXIT_OK
    assert "rollback" not in calls


# --------------------------------------------------------------------------- the pair check


def test_mismatched_key_is_refused_before_any_write(bmc, tmp_path):
    """bmcd's main fails on a pair it cannot load, which stops the UI, the API and tpi."""
    _, other_key = _make_cert(1, "other")
    Path(bmc.key_file).write_bytes(_key_pem(other_key))
    calls = []
    assert run(bmc, constant_probe(OLD_SERIAL), calls) == updater.EXIT_FAILED
    assert calls == []


def test_expired_certificate_is_refused_before_any_write(bmc):
    calls = []
    later = NOW + datetime.timedelta(days=365)
    assert run(bmc, constant_probe(OLD_SERIAL), calls, now=later) == updater.EXIT_FAILED
    assert calls == []


def test_unreadable_key_is_refused_before_any_write(bmc):
    Path(bmc.key_file).write_bytes(b"not a key")
    calls = []
    assert run(bmc, constant_probe(OLD_SERIAL), calls) == updater.EXIT_FAILED
    assert calls == []


def test_key_error_does_not_echo_the_file(bmc):
    Path(bmc.key_file).write_bytes(b"-----BEGIN PRIVATE KEY-----\nc2VjcmV0\n")
    with pytest.raises(updater.ConfigError) as excinfo:
        updater.check_pair(bmc.cert_file, bmc.key_file, NOW)
    assert "c2VjcmV0" not in str(excinfo.value)


def test_a_valid_pair_passes(bmc):
    updater.check_pair(bmc.cert_file, bmc.key_file, NOW)


# --------------------------------------------------------------------------- config handling


def _write_ini(tmp_path, body):
    path = tmp_path / "bad.ini"
    path.write_text(body)
    return str(path)


def test_config_errors_name_the_missing_key(tmp_path):
    path = _write_ini(tmp_path, "[DEFAULT]\nrhost = https://x\nusername = a\npassword = b\n")
    with pytest.raises(updater.ConfigError) as excinfo:
        updater.load_config(path)
    assert "key-file" in str(excinfo.value)


def test_password_may_contain_a_percent_sign(bmc):
    """ConfigParser's default interpolation raises on a lone %, which is a legal password."""
    assert bmc.password == PASSWORD_SENTINEL


def test_rhost_without_scheme_is_rejected(tmp_path):
    path = _write_ini(
        tmp_path,
        "[DEFAULT]\nrhost = bmc.example\nkey-file = k.pem\ncert-file = c.pem\n"
        "known-hosts-file = k\nusername = a\npassword = b\n",
    )
    with pytest.raises(updater.ConfigError) as excinfo:
        updater.load_config(path)
    assert "scheme" in str(excinfo.value)


def test_missing_config_file_is_a_clean_error(tmp_path):
    with pytest.raises(updater.ConfigError) as excinfo:
        updater.load_config(str(tmp_path / "nope.ini"))
    assert "nope.ini" in str(excinfo.value)


def test_main_turns_a_missing_certificate_into_an_exit_code(bmc, tmp_path, capsys):
    """Initial issuance failing leaves no fullchain.pem: a message, not a traceback."""
    Path(bmc.cert_file).unlink()
    ini = tmp_path / "updater.ini"
    assert updater.main(["--config-file", str(ini)]) == updater.EXIT_FAILED
    assert "fullchain.pem" in capsys.readouterr().err


# --------------------------------------------------------------------------- certificate parsing


def test_leaf_serial_from_fullchain(bmc):
    """cert-file is fullchain.pem: leaf first, then intermediates. The leaf is what gets served."""
    assert updater.read_disk_serial(bmc.cert_file) == DISK_SERIAL

    leaf, _ = _make_cert(DISK_SERIAL, "bmc.example")
    assert updater.serial_from_der(leaf.public_bytes(serialization.Encoding.DER)) == DISK_SERIAL


def test_garbage_cert_file_is_a_clean_error(tmp_path):
    path = tmp_path / "fullchain.pem"
    path.write_bytes(b"not a certificate")
    with pytest.raises(updater.ConfigError):
        updater.read_disk_serial(str(path))


# --------------------------------------------------------------------------- the ssh boundary


class FakeRun:
    """Stands in for subprocess.run inside BmcSession."""

    def __init__(self, returncode=0, stderr=b"", raises=None):
        self.returncode = returncode
        self.stderr = stderr
        self.raises = raises
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, b"", self.stderr)


def _session(monkeypatch, bmc, fake):
    monkeypatch.setattr(updater.subprocess, "run", fake)
    return updater.BmcSession(bmc)


def test_password_is_in_the_environment_and_not_in_argv(monkeypatch, bmc):
    fake = FakeRun()
    _session(monkeypatch, bmc, fake).backup()
    argv, kwargs = fake.calls[0]
    assert argv[:3] == ["sshpass", "-e", "ssh"]
    assert PASSWORD_SENTINEL not in " ".join(argv)
    assert kwargs["env"]["SSHPASS"] == PASSWORD_SENTINEL


def test_host_key_policy(monkeypatch, bmc):
    """accept-new, against the role's own file, so a changed host key fails visibly."""
    fake = FakeRun()
    _session(monkeypatch, bmc, fake).backup()
    argv = fake.calls[0][0]
    assert "StrictHostKeyChecking=accept-new" in argv
    assert "UserKnownHostsFile=%s" % bmc.known_hosts_file in argv
    assert "root@bmc.example" in argv


def test_every_restart_is_redirected(monkeypatch, bmc):
    """S94bmcd uses --no-close. Without the redirect bmcd holds the channel and ssh never returns."""
    fake = FakeRun()
    session = _session(monkeypatch, bmc, fake)
    session.activate()
    session.rollback()
    for argv, _ in fake.calls:
        assert argv[-1].endswith("/etc/init.d/S94bmcd restart </dev/null >/dev/null 2>&1")


def test_install_replaces_before_restarting(monkeypatch, bmc):
    fake = FakeRun()
    _session(monkeypatch, bmc, fake).activate()
    command = fake.calls[0][0][-1]
    assert command.index("mv ") < command.index("S94bmcd")
    assert "mv /etc/ssl/certs/bmcd_cert.pem.new /etc/ssl/certs/bmcd_cert.pem" in command
    assert "mv /etc/ssl/certs/bmcd_key.pem.new /etc/ssl/certs/bmcd_key.pem" in command


def test_upload_writes_beside_the_live_files(monkeypatch, bmc):
    """If this fails halfway, bmcd's own files are still whole."""
    fake = FakeRun()
    _session(monkeypatch, bmc, fake).upload()
    commands = [call[0][-1] for call in fake.calls]
    assert commands == [
        "cat > /etc/ssl/certs/bmcd_cert.pem.new",
        "umask 077 && cat > /etc/ssl/certs/bmcd_key.pem.new",
    ]
    assert fake.calls[0][1]["input"] == Path(bmc.cert_file).read_bytes()
    assert fake.calls[1][1]["input"] == Path(bmc.key_file).read_bytes()


def test_key_never_appears_in_argv(monkeypatch, bmc):
    fake = FakeRun()
    _session(monkeypatch, bmc, fake).upload()
    for argv, _ in fake.calls:
        assert all(KEY_MARKER.decode() not in part for part in argv)


def test_rollback_keeps_the_backup(monkeypatch, bmc):
    """cp, not mv: .prev stays until the next install, so a rollback that dies can be redone by hand."""
    fake = FakeRun()
    _session(monkeypatch, bmc, fake).rollback()
    command = fake.calls[0][0][-1]
    assert "cp -p /etc/ssl/certs/bmcd_cert.pem.prev /etc/ssl/certs/bmcd_cert.pem" in command
    assert "cp -p /etc/ssl/certs/bmcd_key.pem.prev /etc/ssl/certs/bmcd_key.pem" in command


def test_ssh_failure_names_the_step_and_status(monkeypatch, bmc):
    fake = FakeRun(returncode=5, stderr=b"Permission denied")
    with pytest.raises(updater.BmcError) as excinfo:
        _session(monkeypatch, bmc, fake).backup()
    message = str(excinfo.value)
    assert "backup" in message and "exit 5" in message and "Permission denied" in message


def test_ssh_stderr_is_truncated(monkeypatch, bmc):
    fake = FakeRun(returncode=1, stderr=b"x" * 5000)
    with pytest.raises(updater.BmcError) as excinfo:
        _session(monkeypatch, bmc, fake).backup()
    assert len(str(excinfo.value)) < 300


def test_hung_ssh_is_a_clean_error(monkeypatch, bmc):
    fake = FakeRun(raises=subprocess.TimeoutExpired(cmd="ssh", timeout=60))
    with pytest.raises(updater.BmcError) as excinfo:
        _session(monkeypatch, bmc, fake).backup()
    assert "timed out" in str(excinfo.value)


def test_secrets_never_printed(monkeypatch, bmc, capsys):
    """Nothing this script logs may carry the password or the key, on any path."""
    fake = FakeRun(returncode=255, stderr=b"Connection refused")
    monkeypatch.setattr(updater.subprocess, "run", fake)
    probe = sequence_probe(OLD_SERIAL, DISK_SERIAL)
    updater.reconcile(
        bmc,
        probe=probe,
        session_factory=updater.BmcSession,
        sleep=lambda _: None,
        now=NOW,
    )
    captured = capsys.readouterr()
    assert PASSWORD_SENTINEL not in captured.out + captured.err
    assert KEY_MARKER.decode() not in captured.out + captured.err
