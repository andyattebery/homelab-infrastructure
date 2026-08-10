"""Guards for the vendored ASRock BMC certificate reconciler.

    cd ansible && .venv/bin/pytest roles/docker_compose_certbot_asrock_ipmi/tests/ -q

Hermetic: no BMC, no sockets, no sleeping. The two I/O boundaries in the script - the TLS probe and
the HTTP session - are injected, so every path below runs against fakes.

These are stricter than usual because the script replaces one that failed silently for four months.
Upstream's failure was not a crash: it was error handling that never matched, an upload that was
never verified, and no comparison against the BMC at all. Each of those has a test here, because
none of them would show up as a broken run.
"""

import datetime
import importlib.util
import json
import ssl
import sys
from pathlib import Path

import pytest
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

SCRIPT = Path(__file__).resolve().parents[1] / "files" / "asrock_ipmi_cert_updater.py"


def _load():
    assert SCRIPT.exists(), "script missing at %s" % SCRIPT
    spec = importlib.util.spec_from_file_location("_asrock_updater_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # The script lives in an Ansible files/ directory. Writing bytecode would drop a __pycache__
    # there, which is at best untracked cruft next to a file the role copies to a container.
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
PASSWORD_SENTINEL = "hunter2-do-not-print"
TOKEN_SENTINEL = "csrf-do-not-print"


# --------------------------------------------------------------------------- fixtures


def _make_cert(serial, common_name):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(serial)
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=90))
        .sign(key, hashes.SHA256())
    )
    return cert, key


@pytest.fixture
def bmc(tmp_path):
    """An ini plus the cert and key it points at, with a known leaf serial."""
    leaf, key = _make_cert(DISK_SERIAL, "ipmi.example")
    intermediate, _ = _make_cert(0xDEADBEEF, "Intermediate CA")

    cert_file = tmp_path / "fullchain.pem"
    cert_file.write_bytes(
        leaf.public_bytes(serialization.Encoding.PEM)
        + intermediate.public_bytes(serialization.Encoding.PEM)
    )
    key_file = tmp_path / "privkey.pem"
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    ini = tmp_path / "updater.ini"
    ini.write_text(
        "[DEFAULT]\n"
        "rhost = https://ipmi.example\n"
        "key-file = %s\n"
        "cert-file = %s\n"
        "username = admin\n"
        "password = %s\n" % (key_file, cert_file, PASSWORD_SENTINEL)
    )
    return updater.load_config(str(ini))


class FakeSession:
    """Records the calls reconcile makes, in order, across every attempt."""

    def __init__(self, calls, fail_with=None):
        self.calls = calls
        self.fail_with = fail_with

    def login(self):
        self.calls.append("login")
        if self.fail_with is not None:
            raise self.fail_with

    def upload(self):
        self.calls.append("upload")

    def logout(self):
        self.calls.append("logout")

    def close(self):
        pass


def make_factory(calls, fail_with=None):
    return lambda config: FakeSession(calls, fail_with)


def constant_probe(serial):
    return lambda host, port, timeout: serial


def run(bmc, probe, calls, *, force=False, attempts=3, fail_with=None, log=lambda *_: None):
    return updater.reconcile(
        bmc,
        probe=probe,
        session_factory=make_factory(calls, fail_with),
        sleep=lambda _: None,
        attempts=attempts,
        force=force,
        log=log,
    )


# --------------------------------------------------------------------------- the headline defect


def test_requests_connection_error_is_not_builtin_connectionerror():
    """Why upstream's error handling never ran.

    All four of its network calls were wrapped in `except ConnectionError:` - the builtin, an
    OSError subclass. requests raises requests.exceptions.ConnectionError, which inherits from
    RequestException -> IOError, and is not a subclass of the builtin. The handler could never
    match, so a timeout became an uncaught traceback instead of a clean False.

    If requests ever changes this, the assertion fails and tells you the guard is now redundant,
    rather than passing silently and leaving nobody any the wiser.
    """
    assert not issubclass(requests.exceptions.ConnectionError, ConnectionError)
    assert not issubclass(requests.exceptions.ReadTimeout, ConnectionError)
    assert issubclass(requests.exceptions.ConnectionError, requests.exceptions.RequestException)
    assert issubclass(requests.exceptions.ReadTimeout, requests.exceptions.RequestException)


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectionError("refused"),
        requests.exceptions.ReadTimeout("Read timed out. (read timeout=10)"),
    ],
)
def test_network_error_returns_exit_code_not_traceback(bmc, error):
    """The 2026-08-08 failure mode, which surfaced as a traceback out of the deploy hook."""
    calls = []
    assert run(bmc, constant_probe(OLD_SERIAL), calls, fail_with=error) == updater.EXIT_FAILED
    assert calls.count("login") == 3, "each attempt should have been tried"
    assert "upload" not in calls, "login failed, so nothing should have been uploaded"


# --------------------------------------------------------------------------- reconcile behaviour


def test_matching_serial_uploads_nothing(bmc):
    """The idempotency guard upstream had no equivalent of - it uploaded on every invocation."""
    calls = []
    assert run(bmc, constant_probe(DISK_SERIAL), calls) == updater.EXIT_OK
    assert calls == []


def test_force_uploads_despite_match(bmc):
    calls = []
    assert run(bmc, constant_probe(DISK_SERIAL), calls, force=True) == updater.EXIT_OK
    assert calls == ["login", "upload", "logout"]


def test_mismatch_uploads_once_and_verifies(bmc):
    seen = []

    def probe(host, port, timeout):
        seen.append(1)
        return OLD_SERIAL if len(seen) == 1 else DISK_SERIAL

    calls = []
    assert run(bmc, probe, calls) == updater.EXIT_OK
    assert calls == ["login", "upload", "logout"]


def test_verification_failure_is_bounded(bmc):
    """An upload that never takes must stop, not spin."""
    calls = []
    assert run(bmc, constant_probe(OLD_SERIAL), calls, attempts=2) == updater.EXIT_FAILED
    assert calls.count("upload") == 2


def test_unreachable_bmc_does_not_upload(bmc):
    """Installing a certificate bounces the BMC web service.

    If the probe is broken rather than the certificate, uploading blind would bounce it every
    single night, forever. Report and stop instead - the Prometheus metric covers this case.
    """
    def probe(host, port, timeout):
        raise OSError("no route to host")

    calls = []
    assert run(bmc, probe, calls) == updater.EXIT_UNREACHABLE
    assert calls == []


def test_verify_tolerates_the_web_service_restart(bmc):
    """The BMC drops its listener while installing, so early post-upload probes failing is normal."""
    seen = []

    def probe(host, port, timeout):
        seen.append(1)
        if len(seen) == 1:
            return OLD_SERIAL
        if len(seen) < 4:
            raise ssl.SSLError("handshake failed")
        return DISK_SERIAL

    calls = []
    assert run(bmc, probe, calls) == updater.EXIT_OK
    assert calls.count("upload") == 1


def test_logout_immediately_follows_upload(bmc):
    """Upstream put a full cert-info GET between upload and logout, which can burn an entire
    request timeout - and its own comment says logout must happen within two seconds."""
    calls = []
    run(bmc, constant_probe(OLD_SERIAL), calls, attempts=1)
    assert calls == ["login", "upload", "logout"]


# --------------------------------------------------------------------------- config handling


def _write_ini(tmp_path, body):
    path = tmp_path / "bad.ini"
    path.write_text(body)
    return str(path)


def test_config_errors_name_the_missing_key(tmp_path):
    """Upstream indexed config['DEFAULT'] directly, so this was a bare KeyError."""
    path = _write_ini(tmp_path, "[DEFAULT]\nrhost = https://x\nusername = a\npassword = b\n")
    with pytest.raises(updater.ConfigError) as excinfo:
        updater.load_config(path)
    assert "key-file" in str(excinfo.value)


def test_empty_rhost_is_rejected(tmp_path):
    """Upstream did rhost[-1] == '/' first thing, which is an IndexError on an empty value."""
    path = _write_ini(
        tmp_path,
        "[DEFAULT]\nrhost = \nkey-file = k.pem\ncert-file = c.pem\nusername = a\npassword = b\n",
    )
    with pytest.raises(updater.ConfigError) as excinfo:
        updater.load_config(path)
    assert "rhost" in str(excinfo.value)


def test_rhost_without_scheme_is_rejected(tmp_path):
    """A missing https:// is a real past bug here - fixed once already in fe4fcc8."""
    path = _write_ini(
        tmp_path,
        "[DEFAULT]\nrhost = ipmi.example\nkey-file = k.pem\ncert-file = c.pem\n"
        "username = a\npassword = b\n",
    )
    with pytest.raises(updater.ConfigError) as excinfo:
        updater.load_config(path)
    assert "scheme" in str(excinfo.value)


def test_missing_config_file_is_a_clean_error(tmp_path):
    with pytest.raises(updater.ConfigError) as excinfo:
        updater.load_config(str(tmp_path / "nope.ini"))
    assert "nope.ini" in str(excinfo.value)


def test_rhost_port_is_parsed(tmp_path):
    path = _write_ini(
        tmp_path,
        "[DEFAULT]\nrhost = https://ipmi.example:8443/\nkey-file = k.pem\ncert-file = c.pem\n"
        "username = a\npassword = b\n",
    )
    config = updater.load_config(path)
    assert (config.host, config.port) == ("ipmi.example", 8443)
    assert config.rhost == "https://ipmi.example:8443", "trailing slash must be stripped"


# --------------------------------------------------------------------------- certificate parsing


def test_leaf_serial_from_fullchain(bmc):
    """cert-file is fullchain.pem: leaf first, then intermediates. The leaf is what gets served."""
    assert updater.read_disk_serial(bmc.cert_file) == DISK_SERIAL

    leaf, _ = _make_cert(DISK_SERIAL, "ipmi.example")
    assert updater.serial_from_pem(leaf.public_bytes(serialization.Encoding.PEM)) == DISK_SERIAL
    assert updater.serial_from_der(leaf.public_bytes(serialization.Encoding.DER)) == DISK_SERIAL


def test_garbage_cert_file_is_a_clean_error(tmp_path):
    path = tmp_path / "fullchain.pem"
    path.write_bytes(b"not a certificate")
    with pytest.raises(updater.ConfigError):
        updater.read_disk_serial(str(path))


# --------------------------------------------------------------------------- the HTTP boundary


class FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text

    @property
    def ok(self):
        return 200 <= self.status_code < 300


class FakeHttp:
    """Stands in for requests.Session inside BmcSession."""

    def __init__(self, post_response):
        self.post_response = post_response
        self.headers = {}
        self.verify = True
        self.posted = []

    def post(self, url, **kwargs):
        self.posted.append((url, kwargs))
        return self.post_response

    def delete(self, url, **kwargs):
        return FakeResponse(200, "")

    def close(self):
        pass


def _session_with(monkeypatch, bmc, response):
    http = FakeHttp(response)
    monkeypatch.setattr(updater.requests, "Session", lambda: http)
    return updater.BmcSession(bmc, timeout=1), http


def test_http_error_message_includes_status(monkeypatch, bmc):
    """Upstream returned a bare False, so a 401 and a 500 produced the identical 'Login failed!'."""
    session, _ = _session_with(monkeypatch, bmc, FakeResponse(401, "Unauthorized"))
    with pytest.raises(updater.BmcError) as excinfo:
        session.login()
    assert "401" in str(excinfo.value)


def test_non_json_login_body_is_a_clean_error(monkeypatch, bmc):
    """A BMC that answers 200 with an HTML error page - upstream json.loads'd it unguarded."""
    session, _ = _session_with(monkeypatch, bmc, FakeResponse(200, "<html>oops</html>"))
    with pytest.raises(updater.BmcError) as excinfo:
        session.login()
    assert "CSRF" in str(excinfo.value)


def test_login_sets_the_csrf_header(monkeypatch, bmc):
    body = json.dumps({"CSRFToken": TOKEN_SENTINEL})
    session, http = _session_with(monkeypatch, bmc, FakeResponse(200, body))
    session.login()
    assert http.headers["X-CSRFTOKEN"] == TOKEN_SENTINEL
    assert http.verify is False, "the certificate being replaced is usually the expired one"
    url, kwargs = http.posted[0]
    assert url == "https://ipmi.example/api/session"
    assert kwargs["data"]["certlogin"] == 0


def test_secrets_never_printed(monkeypatch, bmc, capsys):
    """Nothing this script logs may carry the IPMI password or the session's CSRF token."""
    body = json.dumps({"CSRFToken": TOKEN_SENTINEL})
    session, _ = _session_with(monkeypatch, bmc, FakeResponse(200, body))
    session.login()

    calls = []
    updater.reconcile(
        bmc,
        probe=constant_probe(OLD_SERIAL),
        session_factory=make_factory(calls, requests.exceptions.ConnectionError("refused")),
        sleep=lambda _: None,
        attempts=2,
        log=print,
    )

    captured = capsys.readouterr()
    assert PASSWORD_SENTINEL not in captured.out + captured.err
    assert TOKEN_SENTINEL not in captured.out + captured.err


def test_error_body_is_truncated(monkeypatch, bmc):
    """A BMC dumping a whole HTML page into an exception message helps nobody."""
    session, _ = _session_with(monkeypatch, bmc, FakeResponse(500, "x" * 5000))
    with pytest.raises(updater.BmcError) as excinfo:
        session.login()
    assert len(str(excinfo.value)) < 300
