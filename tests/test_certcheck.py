import asyncio
import datetime as dt
import ipaddress
import socket
import ssl
import threading
import time

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.certcheck import (CertMonitor, cert_targets, fetch_certificate, level_for,
                           parse_targets)
from app.config import ConfigError, Settings
from app.ha import HaPublisher, broker_states
from app.tracker import Tracker

NOW = dt.datetime.now(dt.timezone.utc)
BASE = {"MQTT_HOST": "b", "MQTT_USERNAME": "mgr", "MQTT_PASSWORD": "x", "UI_PASSWORD": "password123",
        "UI_SECRET": "k"}


def settings(tmp_path, **extra):
    return Settings.from_env({**BASE, "DATA_DIR": str(tmp_path), **extra})


# ---------------------------------------------------------------- certificates
def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def make_ca(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (x509.CertificateBuilder().subject_name(_name("Test CA")).issuer_name(_name("Test CA"))
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(NOW - dt.timedelta(days=400)).not_valid_after(NOW + dt.timedelta(days=400))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    (tmp_path / "ca.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key, cert


def make_server_cert(tmp_path, ca, *, expires_in_days, started_days_ago=30, name="server"):
    ca_key, ca_cert = ca
    key = ec.generate_private_key(ec.SECP384R1())
    cert = (x509.CertificateBuilder().subject_name(_name("*.example.test")).issuer_name(ca_cert.subject)
            .public_key(key.public_key()).serial_number(0xABCDEF)
            .not_valid_before(NOW - dt.timedelta(days=started_days_ago))
            .not_valid_after(NOW + dt.timedelta(days=expires_in_days))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("*.example.test"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                critical=False)
            .sign(ca_key, hashes.SHA256()))
    crt, k = tmp_path / f"{name}.crt", tmp_path / f"{name}.key"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    return crt, k


class TlsServer:
    def __init__(self, crt, key):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(crt, key)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        threading.Thread(target=self._serve, args=(ctx,), daemon=True).start()

    def _serve(self, ctx):
        self.sock.settimeout(0.2)
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            try:
                ctx.wrap_socket(conn, server_side=True).close()
            except (ssl.SSLError, OSError):
                conn.close()

    def close(self):
        self.stop.set()
        self.sock.close()


@pytest.fixture
def ca(tmp_path):
    return make_ca(tmp_path)


def serve(tmp_path, ca, **kw):
    crt, key = make_server_cert(tmp_path, ca, **kw)
    return TlsServer(crt, key)


# ------------------------------------------------------------------- the reader
def test_fetch_reads_the_certificate_details(tmp_path, ca):
    srv = serve(tmp_path, ca, expires_in_days=40)
    try:
        info = fetch_certificate("127.0.0.1", srv.port)
    finally:
        srv.close()
    assert info["subject"] == "*.example.test" and info["issuer"] == "Test CA"
    assert info["names"] == ["*.example.test"] and info["key"] == "ECDSA secp384r1"
    assert info["serial"] == "abcdef"
    assert 39.9 < (info["not_after"] - time.time()) / 86400 < 40.1


def test_an_expired_certificate_can_still_be_read(tmp_path, ca):
    srv = serve(tmp_path, ca, expires_in_days=-2, started_days_ago=90)
    try:
        info = fetch_certificate("127.0.0.1", srv.port)
    finally:
        srv.close()
    assert info["not_after"] < time.time()


# --------------------------------------------------------------------- policies
@pytest.mark.parametrize("days,level", [(60, "ok"), (14.0, "ok"), (13.9, "warning"), (7.0, "warning"),
                                        (6.9, "critical"), (0.1, "critical"), (-0.1, "expired")])
def test_levels(days, level):
    assert level_for(days, 14) == level


def test_parse_targets():
    assert parse_targets("a.b:8883, 10.0.0.1:8884;c:1") == [("a.b", 8883), ("10.0.0.1", 8884), ("c", 1)]
    for bad in ("nohost", "a:b", ":8883"):
        with pytest.raises(ValueError):
            parse_targets(bad)


def test_default_targets(tmp_path):
    assert cert_targets(settings(tmp_path, MQTT_TLS="true", MQTT_HOST="mqtt.x", MQTT_PORT="8883")) == (
        [("mqtt.x", 8883)], True)
    assert cert_targets(settings(tmp_path, TLS_PORTS="8883,8884")) == (
        [("b", 8883), ("b", 8884)], False)  # plain manager: look at the TLS ports, stay quiet if none
    assert cert_targets(settings(tmp_path, CERT_CHECK="off")) == ([], False)
    assert cert_targets(settings(tmp_path, CERT_CHECK="h:1")) == ([("h", 1)], True)


def test_config_validation(tmp_path):
    for bad in ({"CERT_CHECK": "nonsense"}, {"CERT_WARN_DAYS": "soon"}):
        with pytest.raises(ConfigError):
            settings(tmp_path, **bad)
    assert settings(tmp_path).cert_warn_days == 14


# ---------------------------------------------------------------------- monitor
def run(coro):
    return asyncio.run(coro)


def test_monitor_reports_days_level_and_trust(tmp_path, ca):
    srv = serve(tmp_path, ca, expires_in_days=10)
    try:
        s = settings(tmp_path, CERT_CHECK=f"127.0.0.1:{srv.port}", MQTT_CA_FILE=str(tmp_path / "ca.crt"))
        mon = CertMonitor(s)
        run(mon.check_now())
        (item,) = mon.snapshot()
        assert item["level"] == "warning" and 9.9 < item["days_left"] < 10.1
        assert item["trust_error"] is None and item["issuer"] == "Test CA"
        assert mon.primary()["port"] == srv.port
        # without the CA the manager cannot verify it, and says so
        mon2 = CertMonitor(settings(tmp_path, CERT_CHECK=f"127.0.0.1:{srv.port}"))
        run(mon2.check_now())
        assert "MQTT_CA_FILE" in mon2.snapshot()[0]["trust_error"]
    finally:
        srv.close()


def test_monitor_flags_expired_certificates(tmp_path, ca):
    srv = serve(tmp_path, ca, expires_in_days=-1, started_days_ago=90)
    try:
        mon = CertMonitor(settings(tmp_path, CERT_CHECK=f"127.0.0.1:{srv.port}",
                                   MQTT_CA_FILE=str(tmp_path / "ca.crt")))
        run(mon.check_now())
        item = mon.snapshot()[0]
        assert item["level"] == "expired" and item["days_left"] < 0
        assert "expired" in item["trust_error"].lower()
    finally:
        srv.close()


def test_missing_listener_is_quiet_by_default_but_reported_when_asked(tmp_path):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # nothing listens here
    auto = CertMonitor(settings(tmp_path, TLS_PORTS=str(port), MQTT_HOST="127.0.0.1"))
    run(auto.check_now())
    assert auto.snapshot() == []
    explicit = CertMonitor(settings(tmp_path, CERT_CHECK=f"127.0.0.1:{port}"))
    run(explicit.check_now())
    (item,) = explicit.snapshot()
    assert item["level"] == "error" and "cannot read" in item["error"]
    assert explicit.primary() is None


def test_snapshot_keeps_counting_between_checks(tmp_path):
    mon = CertMonitor(settings(tmp_path, CERT_CHECK="h:1"))
    mon.results["h:1"] = {"host": "h", "port": 1, "error": None, "checked": 0, "not_after": 1_000_000.0,
                          "not_before": 0, "subject": "x", "issuer": "y", "names": [], "key": "k",
                          "serial": "1", "trust_error": None}
    assert mon.snapshot(now=1_000_000.0 - 20 * 86400)[0]["level"] == "ok"
    assert mon.snapshot(now=1_000_000.0 - 3 * 86400)[0]["level"] == "critical"
    assert mon.snapshot(now=1_000_000.0 + 86400)[0]["level"] == "expired"


# ----------------------------------------------------------- Home Assistant side
def test_ha_states_for_the_certificate():
    snap = {"clients_connected": 1}
    kw = dict(users_total=1, users_online=1, failed_24h=0, failed_10m=0, threshold=5, last_failed=None)
    ok = broker_states(snap, cert={"days_left": 45.7, "not_after": 1_800_000_000.0, "level": "ok"}, **kw)
    assert ok["cert_days_left"] == "45" and ok["cert_expiring"] == "OFF"
    assert ok["cert_expires"].endswith("+00:00")
    soon = broker_states(snap, cert={"days_left": 3.2, "not_after": 1_800_000_000.0, "level": "critical"}, **kw)
    assert soon["cert_expiring"] == "ON" and soon["cert_days_left"] == "3"
    none = broker_states(snap, cert=None, **kw)
    assert none["cert_days_left"] == "None" and none["cert_expires"] == "None" and none["cert_expiring"] == "OFF"


def test_ha_publisher_publishes_certificate_sensors(tmp_path):
    class Certs:
        def primary(self):
            return {"days_left": 12.5, "not_after": 1_800_000_000.0, "level": "warning"}

    class B:
        connected = True
        on_event = None

        def snapshot(self):
            return {"version": "2.1.2", "has_sys": True}

        async def list_clients(self):
            return []

    sent = {}
    s = settings(tmp_path, HA_DISCOVERY="true")
    pub = HaPublisher(s, B(), Tracker(), certs=Certs(), publish=lambda t, p, r: sent.__setitem__(t, p))
    asyncio.run(pub._tick())
    assert sent["mosquitto_manager/state/cert_days_left"] == "12"
    assert sent["mosquitto_manager/state/cert_expiring"] == "ON"
    assert "homeassistant/binary_sensor/mosquitto_manager/cert_expiring/config" in sent
