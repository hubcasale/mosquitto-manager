"""Watches the TLS certificate the broker presents, so an expiring certificate is noticed
long before every client starts refusing it."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import ssl
import time
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from .broker import diagnose_tls
from .config import Settings

log = logging.getLogger("mosquitto_manager.certcheck")

CHECK_INTERVAL_SECONDS = 6 * 3600
CRITICAL_DAYS = 7


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def parse_targets(spec: str) -> list[tuple[str, int]]:
    """'host:8883, other:8884' -> [('host', 8883), ('other', 8884)]; raises ValueError."""
    out = []
    for item in spec.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        host, sep, port = item.rpartition(":")
        if not sep or not host or not port.isdigit():
            raise ValueError(f"'{item}' is not host:port")
        out.append((host.strip("[]"), int(port)))
    return out


def cert_targets(s: Settings) -> tuple[list[tuple[str, int]], bool]:
    """Where to look, and whether a missing listener is worth reporting.

    By default (CERT_CHECK=auto) the manager checks the port it connects to when it
    uses TLS itself, otherwise the broker's TLS listener ports (TLS_PORTS): a broker
    without TLS is simply not reported.
    """
    spec = s.cert_check.strip()
    if spec.lower() == "off":
        return [], False
    if spec.lower() == "auto":
        if s.mqtt_tls:
            return [(s.mqtt_host, s.mqtt_port)], True
        return [(s.mqtt_host, p) for p in sorted(s.tls_ports)], False
    return parse_targets(spec), True


def level_for(days_left: float, warn_days: int) -> str:
    if days_left < 0:
        return "expired"
    if days_left < CRITICAL_DAYS:
        return "critical"
    if days_left < warn_days:
        return "warning"
    return "ok"


def fetch_certificate(host: str, port: int, timeout: float = 5.0) -> dict[str, Any]:
    """The certificate a TLS server presents (blocking). Not verified: we want to read it
    even when it is expired or from an unknown issuer, and report that separately."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=None if _is_ip(host) else host) as tls:
            der = tls.getpeercert(binary_form=True)
    cert = x509.load_der_x509_certificate(der)

    def cn(name: x509.Name) -> str:
        attrs = name.get_attributes_for_oid(NameOID.COMMON_NAME)
        return attrs[0].value if attrs else name.rfc4514_string()

    try:
        names = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        names = []
    pub = cert.public_key()
    if isinstance(pub, ec.EllipticCurvePublicKey):
        key = f"ECDSA {pub.curve.name}"
    elif isinstance(pub, rsa.RSAPublicKey):
        key = f"RSA {pub.key_size}"
    else:
        key = type(pub).__name__
    return {
        "subject": cn(cert.subject), "issuer": cn(cert.issuer), "names": list(names),
        "serial": format(cert.serial_number, "x"), "key": key,
        "not_before": cert.not_valid_before_utc.timestamp(),
        "not_after": cert.not_valid_after_utc.timestamp(),
    }


class CertMonitor:
    def __init__(self, settings: Settings):
        self.s = settings
        self.targets, self.report_missing = cert_targets(settings)
        self.results: dict[str, dict[str, Any]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.targets)

    def _check_one(self, host: str, port: int) -> dict[str, Any]:
        entry: dict[str, Any] = {"host": host, "port": port, "checked": time.time(), "error": None}
        try:
            entry.update(fetch_certificate(host, port))
        except (OSError, ssl.SSLError) as exc:
            entry["error"] = f"cannot read the certificate from {host}:{port}: {exc}"
            return entry
        except Exception as exc:  # never let a parsing surprise stop the monitor
            log.exception("certificate check failed")
            entry["error"] = f"{type(exc).__name__}: {exc}"
            return entry
        entry["trust_error"] = diagnose_tls(host, port, self.s.mqtt_ca_file, self.s.mqtt_tls_insecure)
        return entry

    async def check_now(self) -> None:
        loop = asyncio.get_running_loop()
        for host, port in self.targets:
            entry = await loop.run_in_executor(None, self._check_one, host, port)
            key = f"{host}:{port}"
            if entry["error"] and not self.report_missing:
                self.results.pop(key, None)  # no TLS listener there: nothing to watch
                continue
            self.results[key] = entry
            if not entry["error"]:
                days = (entry["not_after"] - time.time()) / 86400
                if days < self.s.cert_warn_days:
                    log.warning("TLS certificate of %s expires in %.1f days", key, days)

    async def run(self) -> None:
        await asyncio.sleep(5)
        while True:
            try:
                await self.check_now()
            except Exception:  # pragma: no cover - defensive
                log.exception("certificate monitor")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    def snapshot(self, now: float | None = None) -> list[dict[str, Any]]:
        """Results with the remaining days computed now (they stay right between checks)."""
        now = time.time() if now is None else now
        out = []
        for entry in self.results.values():
            item = dict(entry)
            if not entry.get("error"):
                days = (entry["not_after"] - now) / 86400
                item["days_left"] = days
                item["level"] = level_for(days, self.s.cert_warn_days)
            else:
                item["level"] = "error"
            item["warn_days"] = self.s.cert_warn_days
            out.append(item)
        return out

    def primary(self, now: float | None = None) -> dict[str, Any] | None:
        """The certificate the sensors and the headline refer to: the soonest to expire."""
        valid = [x for x in self.snapshot(now) if "days_left" in x]
        return min(valid, key=lambda x: x["days_left"]) if valid else None
