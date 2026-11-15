"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path


_TOPIC_PART = re.compile(r"[A-Za-z0-9_-]+")


class ConfigError(RuntimeError):
    """Raised when the configuration is unusable (the process should exit)."""


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_secret(data_dir: Path, explicit: str | None) -> str:
    """Key used to sign session cookies.

    Taken from UI_SECRET if set, otherwise generated once and persisted in the
    data directory so sessions survive restarts. If the directory is not
    writable a random per-process key is used.
    """
    if explicit:
        return explicit
    key_file = data_dir / "secret.key"
    try:
        if key_file.exists():
            value = key_file.read_text().strip()
            if value:
                return value
        data_dir.mkdir(parents=True, exist_ok=True)
        value = secrets.token_hex(32)
        key_file.write_text(value)
        key_file.chmod(0o600)
        return value
    except OSError:
        return secrets.token_hex(32)


@dataclass(frozen=True)
class Settings:
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    mqtt_tls: bool
    mqtt_tls_insecure: bool
    mqtt_ca_file: str | None
    ui_password: str
    auth_disabled: bool
    data_dir: Path
    secret_key: str
    frame_ancestors: str
    cookie_secure: bool
    session_hours: int
    log_level: str
    ha_discovery: bool
    ha_prefix: str
    ha_node: str
    ha_base: str
    ha_failed_threshold: int
    ha_user_sensors: bool
    tls_ports: frozenset
    cert_check: str
    cert_warn_days: int

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        e = os.environ if env is None else env

        host = e.get("MQTT_HOST", "").strip()
        username = e.get("MQTT_USERNAME", "").strip()
        password = e.get("MQTT_PASSWORD", "")
        if not host:
            raise ConfigError("MQTT_HOST is required (address of your Mosquitto broker).")
        if not username or not password:
            raise ConfigError(
                "MQTT_USERNAME and MQTT_PASSWORD are required "
                "(a Dynamic Security administrator, see the README)."
            )
        try:
            port = int(e.get("MQTT_PORT", "1883"))
        except ValueError as exc:
            raise ConfigError("MQTT_PORT must be a number.") from exc

        auth_disabled = _bool(e.get("AUTH_DISABLED"))
        ui_password = e.get("UI_PASSWORD", "")
        if not auth_disabled and len(ui_password) < 8:
            raise ConfigError(
                "UI_PASSWORD is required and must be at least 8 characters. "
                "(Set AUTH_DISABLED=true only if the UI is already protected by "
                "something else, such as a reverse proxy with authentication.)"
            )

        ha_node = e.get("HA_NODE_ID", "mosquitto_manager").strip()
        ha_base = e.get("HA_BASE_TOPIC", "mosquitto_manager").strip()
        ha_prefix = e.get("HA_DISCOVERY_PREFIX", "homeassistant").strip()
        for label, value in (("HA_NODE_ID", ha_node), ("HA_BASE_TOPIC", ha_base),
                             ("HA_DISCOVERY_PREFIX", ha_prefix)):
            if not _TOPIC_PART.fullmatch(value):
                raise ConfigError(f"{label} may only contain letters, digits, '_' and '-'.")
        try:
            ha_threshold = int(e.get("HA_FAILED_THRESHOLD", "5"))
        except ValueError as exc:
            raise ConfigError("HA_FAILED_THRESHOLD must be a number.") from exc

        try:
            tls_ports = frozenset(int(x) for x in e.get("TLS_PORTS", "8883").replace(",", " ").split())
        except ValueError as exc:
            raise ConfigError("TLS_PORTS must be a list of port numbers, for example 8883.") from exc

        cert_check = e.get("CERT_CHECK", "auto").strip() or "auto"
        if cert_check.lower() not in ("auto", "off"):
            for item in cert_check.replace(";", ",").split(","):
                host, sep, port = item.strip().rpartition(":")
                if item.strip() and (not sep or not host or not port.isdigit()):
                    raise ConfigError("CERT_CHECK must be 'auto', 'off' or a list of host:port.")
        try:
            cert_warn_days = int(e.get("CERT_WARN_DAYS", "14"))
        except ValueError as exc:
            raise ConfigError("CERT_WARN_DAYS must be a number of days.") from exc

        data_dir = Path(e.get("DATA_DIR", "/data"))
        return cls(
            mqtt_host=host,
            mqtt_port=port,
            mqtt_username=username,
            mqtt_password=password,
            mqtt_tls=_bool(e.get("MQTT_TLS")),
            mqtt_tls_insecure=_bool(e.get("MQTT_TLS_INSECURE")),
            mqtt_ca_file=e.get("MQTT_CA_FILE") or None,
            ui_password=ui_password,
            auth_disabled=auth_disabled,
            data_dir=data_dir,
            secret_key=_load_secret(data_dir, e.get("UI_SECRET") or None),
            frame_ancestors=e.get("FRAME_ANCESTORS", "'self'").strip() or "'self'",
            cookie_secure=_bool(e.get("COOKIE_SECURE")),
            session_hours=int(e.get("SESSION_HOURS", "12")),
            log_level=e.get("LOG_LEVEL", "info").lower(),
            ha_discovery=_bool(e.get("HA_DISCOVERY")),
            ha_prefix=ha_prefix,
            ha_node=ha_node,
            ha_base=ha_base,
            ha_failed_threshold=max(1, ha_threshold),
            ha_user_sensors=_bool(e.get("HA_USER_SENSORS"), True),
            tls_ports=tls_ports,
            cert_check=cert_check,
            cert_warn_days=max(1, cert_warn_days),
        )
