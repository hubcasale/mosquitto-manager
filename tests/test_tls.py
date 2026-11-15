"""TLS diagnosis, against a throw-away TLS server with certificates made by the openssl CLI."""

import shutil
import socket
import ssl
import subprocess
import threading

import pytest

from app.broker import diagnose_tls

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl CLI")


def run(*args, cwd):
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)


def make_pki(tmp_path, san="DNS:localhost,IP:127.0.0.1", days=30, name="server"):
    d = tmp_path
    if not (d / "ca.crt").exists():
        run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.crt",
            "-days", "30", "-subj", "/CN=Test CA", cwd=d)
    run("req", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{name}.key", "-out", f"{name}.csr",
        "-subj", f"/CN={name}", cwd=d)
    (d / f"{name}.ext").write_text(f"subjectAltName={san}\n")
    run("x509", "-req", "-in", f"{name}.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial",
        "-out", f"{name}.crt", "-days", str(days), "-extfile", f"{name}.ext", cwd=d)
    return d / f"{name}.crt", d / f"{name}.key"


@pytest.fixture
def tls_server(tmp_path):
    cert, key = make_pki(tmp_path)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    stop = threading.Event()

    def serve():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except (socket.timeout, OSError):
                continue
            try:
                ctx.wrap_socket(conn, server_side=True).close()
            except (ssl.SSLError, OSError):
                conn.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield srv.getsockname()[1], tmp_path / "ca.crt"
    stop.set()
    srv.close()


def test_trusted_certificate_is_fine(tls_server):
    port, ca = tls_server
    assert diagnose_tls("localhost", port, str(ca)) is None


def test_unknown_issuer_points_to_mqtt_ca_file(tls_server):
    port, _ = tls_server
    msg = diagnose_tls("localhost", port, None)
    assert msg and "rejected" in msg and "MQTT_CA_FILE" in msg


def test_wrong_hostname_says_which_name_to_use(tls_server, monkeypatch):
    port, ca = tls_server
    real = socket.create_connection
    # connect to the local server whatever name is asked for; the certificate has no such name
    monkeypatch.setattr(socket, "create_connection",
                        lambda addr, timeout=None: real(("127.0.0.1", addr[1]), timeout=timeout))
    msg = diagnose_tls("mqtt.other.example", port, str(ca))
    assert msg and "mismatch" in msg.lower() and "MQTT_HOST" in msg
    # MQTT_TLS_INSECURE only skips the hostname check, like the MQTT client does
    assert diagnose_tls("mqtt.other.example", port, str(ca), insecure=True) is None


def test_insecure_does_not_accept_an_unknown_issuer(tls_server):
    port, _ = tls_server
    assert "rejected" in diagnose_tls("localhost", port, None, insecure=True)


def test_plain_port_is_reported_as_not_tls():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    stop = threading.Event()

    def serve():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except (socket.timeout, OSError):
                continue
            conn.sendall(b"not tls at all\n")
            conn.close()

    threading.Thread(target=serve, daemon=True).start()
    try:
        msg = diagnose_tls("127.0.0.1", srv.getsockname()[1], None)
    finally:
        stop.set()
        srv.close()
    assert msg and "TLS" in msg


def test_closed_port_is_reported_as_unreachable():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert "Cannot reach" in diagnose_tls("127.0.0.1", port, None, timeout=1)
