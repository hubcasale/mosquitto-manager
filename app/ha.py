"""Publishes Mosquitto's state to Home Assistant through MQTT discovery.

Off by default (HA_DISCOVERY=true to enable). It uses a *second* MQTT connection with
a last-will message, so that a permission problem can never lock the manager itself
out of the broker, and gives its own account the few publish rights it needs through a
dedicated role (``mosquitto-manager-ha``) that is visible in the UI.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Callable

import paho.mqtt.client as mqtt

from . import __version__
from .broker import BrokerUnavailable, DynsecError, DynsecTimeout, _apply_tls
from .config import Settings
from .merge import merge_clients
from .tracker import Tracker

log = logging.getLogger("mosquitto_manager.ha")

ROLE_NAME = "mosquitto-manager-ha"
REPO_URL = "https://github.com/hubcasale/mosquitto-manager"
USERS_RESYNC_SECONDS = 300
TICK_SECONDS = 15

# key, component, name, extra discovery options
BROKER_ENTITIES: list[tuple[str, str, str, dict[str, Any]]] = [
    ("clients_connected", "sensor", "Clients connected",
     {"state_class": "measurement", "icon": "mdi:lan-connect"}),
    ("users_online", "sensor", "Users online",
     {"state_class": "measurement", "icon": "mdi:account-network"}),
    ("users_total", "sensor", "Known users",
     {"state_class": "measurement", "icon": "mdi:account-multiple"}),
    ("subscriptions", "sensor", "Subscriptions",
     {"state_class": "measurement", "icon": "mdi:playlist-check"}),
    ("retained", "sensor", "Retained messages",
     {"state_class": "measurement", "icon": "mdi:message-lock"}),
    ("msg_rate_in", "sensor", "Messages in",
     {"state_class": "measurement", "unit_of_measurement": "msg/min", "icon": "mdi:arrow-down-bold"}),
    ("msg_rate_out", "sensor", "Messages out",
     {"state_class": "measurement", "unit_of_measurement": "msg/min", "icon": "mdi:arrow-up-bold"}),
    ("failed_logins_24h", "sensor", "Failed logins (24 h)",
     {"state_class": "measurement", "icon": "mdi:account-lock"}),
    ("failed_logins_10m", "sensor", "Failed logins (10 min)",
     {"state_class": "measurement", "icon": "mdi:account-lock-open"}),
    ("last_failed_login", "sensor", "Last failed login",
     {"device_class": "timestamp", "icon": "mdi:account-cancel"}),
    ("login_attack", "binary_sensor", "Login attack", {"device_class": "problem"}),
    ("uptime", "sensor", "Uptime",
     {"device_class": "duration", "unit_of_measurement": "s", "entity_category": "diagnostic"}),
    ("version", "sensor", "Version", {"entity_category": "diagnostic", "icon": "mdi:tag"}),
    ("cert_days_left", "sensor", "TLS certificate days left",
     {"state_class": "measurement", "unit_of_measurement": "d", "icon": "mdi:certificate"}),
    ("cert_expires", "sensor", "TLS certificate expires",
     {"device_class": "timestamp", "icon": "mdi:calendar-alert"}),
    ("cert_expiring", "binary_sensor", "TLS certificate expiring", {"device_class": "problem"}),
    ("dropped", "sensor", "Dropped messages",
     {"state_class": "total_increasing", "entity_category": "diagnostic", "icon": "mdi:message-off"}),
]


# ------------------------------------------------------------------ pure helpers
def slug(text: str, maxlen: int = 40) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return cleaned[:maxlen].strip("_") or "x"


def user_key(username: str) -> str:
    """Stable, topic-safe id for a username (readable part + short hash for uniqueness)."""
    return f"{slug(username, 32)}_{hashlib.sha1(username.encode()).hexdigest()[:6]}"


def iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None


def _fmt(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".") or "0"
    return str(value)


def _json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Topics:
    def __init__(self, s: Settings):
        self.prefix, self.node, self.base = s.ha_prefix, s.ha_node, s.ha_base
        self.status = f"{self.base}/status"
        self.birth = f"{self.prefix}/status"

    def discovery(self, component: str, object_id: str) -> str:
        return f"{self.prefix}/{component}/{self.node}/{object_id}/config"

    def state(self, key: str) -> str:
        return f"{self.base}/state/{key}"

    def user_state(self, ukey: str) -> str:
        return f"{self.base}/user/{ukey}/state"

    def user_attrs(self, ukey: str) -> str:
        return f"{self.base}/user/{ukey}/attrs"


def _origin() -> dict[str, str]:
    return {"name": "Mosquitto Manager", "sw_version": __version__, "support_url": REPO_URL}


def broker_device(s: Settings, version: str | None) -> dict[str, Any]:
    dev: dict[str, Any] = {"identifiers": [f"{s.ha_node}_broker"], "name": "Mosquitto broker",
                           "manufacturer": "Eclipse Mosquitto", "model": "MQTT broker"}
    if version:
        dev["sw_version"] = version
    return dev


def broker_config(s: Settings, t: Topics, entity: tuple[str, str, str, dict[str, Any]],
                  version: str | None) -> tuple[str, str, dict[str, Any]]:
    key, component, name, extra = entity
    cfg: dict[str, Any] = {
        "name": name,
        "unique_id": f"{s.ha_node}_{key}",
        "default_entity_id": f"{component}.mosquitto_{key}",
        "state_topic": t.state(key),
        "availability_topic": t.status,
        "device": broker_device(s, version),
        "origin": _origin(),
        **extra,
    }
    if component == "binary_sensor":
        cfg.update(payload_on="ON", payload_off="OFF")
    if key == "last_failed_login":
        cfg["json_attributes_topic"] = f"{t.state(key)}/attrs"
    return component, key, cfg


def user_config(s: Settings, t: Topics, username: str) -> tuple[str, str, dict[str, Any]]:
    ukey = user_key(username)
    return "binary_sensor", f"user_{ukey}", {
        "name": username,
        "unique_id": f"{s.ha_node}_user_{ukey}",
        "default_entity_id": f"binary_sensor.mqtt_client_{slug(username)}",
        "state_topic": t.user_state(ukey),
        "json_attributes_topic": t.user_attrs(ukey),
        "availability_topic": t.status,
        "device_class": "connectivity",
        "payload_on": "ON", "payload_off": "OFF",
        "device": {"identifiers": [f"{s.ha_node}_clients"], "name": "MQTT clients",
                   "manufacturer": "Mosquitto Manager", "model": "Dynamic Security users",
                   "via_device": f"{s.ha_node}_broker"},
        "origin": _origin(),
    }


def broker_states(snap: dict[str, Any], *, users_total: int | None, users_online: int | None,
                  failed_24h: int, failed_10m: int, threshold: int,
                  last_failed: dict[str, Any] | None,
                  cert: dict[str, Any] | None = None) -> dict[str, str]:
    out = {
        "cert_days_left": _fmt(int(cert["days_left"] // 1) if cert else None),
        "cert_expires": iso(cert["not_after"]) if cert else "None",
        "cert_expiring": "ON" if cert and cert["level"] != "ok" else "OFF",
        "clients_connected": _fmt(snap.get("clients_connected")),
        "users_online": _fmt(users_online),
        "users_total": _fmt(users_total),
        "subscriptions": _fmt(snap.get("subscriptions")),
        "retained": _fmt(snap.get("retained")),
        "msg_rate_in": _fmt(snap.get("msg_rate_in")),
        "msg_rate_out": _fmt(snap.get("msg_rate_out")),
        "failed_logins_24h": str(failed_24h),
        "failed_logins_10m": str(failed_10m),
        "login_attack": "ON" if failed_10m >= threshold else "OFF",
        "uptime": _fmt(snap.get("uptime")),
        "version": _fmt(snap.get("version")),
        "dropped": _fmt(snap.get("dropped")),
        "last_failed_login": iso(last_failed["ts"]) if last_failed else "None",
        "last_failed_login/attrs": _json({
            "clientid": last_failed.get("clientid"), "address": last_failed.get("address"),
            "reason": last_failed.get("reason")} if last_failed else {}),
    }
    return out


def user_payloads(c: dict[str, Any]) -> tuple[str, str]:
    conns = c.get("connections", [])
    first = conns[0] if conns else {}
    attrs = {
        "username": c["username"], "display_name": c.get("textname") or None,
        "disabled": bool(c.get("disabled")),
        "connection_count": len(conns),
        "saved_sessions": c.get("saved_sessions", 0),
        "address": first.get("address"), "clientid": first.get("clientid"),
        "protocol": first.get("protocol"), "connected_since": iso(first.get("since")),
        "connections": [{"address": x.get("address"), "clientid": x.get("clientid")} for x in conns],
        "roles": [r["rolename"] for r in c.get("roles", [])],
        "groups": [g["groupname"] for g in c.get("groups", [])],
        "last_seen": iso((c.get("last_seen") or {}).get("ts")),
    }
    return ("ON" if c.get("online") else "OFF"), _json(attrs)


# --------------------------------------------------------------------- publisher
class HaPublisher:
    def __init__(self, settings: Settings, broker: Any, tracker: Tracker, certs: Any = None,
                 publish: Callable[[str, str, bool], None] | None = None):
        self.s = settings
        self.broker = broker
        self.tracker = tracker
        self.certs = certs
        self.topics = Topics(settings)
        self.state = "off" if not settings.ha_discovery else "starting"
        self.error: str | None = None
        self._injected = publish is not None
        self._publish_fn = publish
        self._client: mqtt.Client | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._ready = publish is not None  # injected publisher counts as connected
        self._provisioned = publish is not None
        self._need_discovery = True
        self._users_dirty = True
        self._last_users = 0.0
        self._users: dict[str, str] = {}
        self._users_data: list[dict[str, Any]] = []
        self._cache: dict[str, str] = {}

    # ------------------------------------------------------------------ public
    @property
    def enabled(self) -> bool:
        return self.s.ha_discovery

    def info(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "state": self.state, "error": self.error,
                "prefix": self.s.ha_prefix,
                "entities": len(BROKER_ENTITIES) + len(self._users) if self.state == "ok" else 0}

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if not self.enabled:
            return
        self._loop = loop
        self.broker.on_event = self._on_event
        self._task = loop.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self._client is not None:
            try:
                self._client.publish(self.topics.status, "offline", qos=1, retain=True).wait_for_publish(2)
            except Exception:  # pragma: no cover - best effort on shutdown
                pass
            self._client.disconnect()
            self._client.loop_stop()

    # ---------------------------------------------------------------- internals
    def _on_event(self, ev: Any) -> None:
        if getattr(ev, "internal", False):
            return
        if ev.kind in ("connect", "disconnect", "admin"):
            self._users_dirty = True
        if ev.kind in ("connect", "disconnect", "admin", "auth_failed"):
            self._wake.set()

    async def _run(self) -> None:
        while True:
            try:
                if not self._provisioned:
                    if not self.broker.connected:
                        self.state, self.error = "starting", "waiting for the broker"
                    else:
                        await self._provision()
                if self._provisioned and self._client is None and not self._injected:
                    self._connect()
                if self._provisioned and self._ready:
                    await self._tick()
                    self.state, self.error = "ok", None
            except (DynsecError, DynsecTimeout, BrokerUnavailable) as exc:
                self.state, self.error = "error", str(exc)
                self._provisioned = False
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never let the task die silently
                log.exception("Home Assistant publisher failed")
                self.state, self.error = "error", repr(exc)
            # retry quickly while starting up or after an error, relax once everything works
            interval = TICK_SECONDS if self.state == "ok" else 2
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=interval)
                await asyncio.sleep(1.5)  # let a burst of events settle
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _ignore_exists(self, command: str, **params: Any) -> None:
        try:
            await self.broker.dynsec(command, **params)
        except DynsecError as exc:
            if "already" in str(exc).lower() or "exists" in str(exc).lower():
                return
            raise

    async def _provision(self) -> None:
        """Give the manager's own account the few publish rights it needs (idempotent)."""
        t = self.topics
        await self._ignore_exists("createRole", rolename=ROLE_NAME,
                                  textname="Mosquitto Manager: Home Assistant sensors")
        for acltype, topic in (
                ("publishClientSend", f"{t.prefix}/+/{t.node}/+/config"),
                ("publishClientSend", f"{t.base}/#"),
                ("publishClientReceive", t.birth),
                ("subscribePattern", t.birth)):
            await self._ignore_exists("addRoleACL", rolename=ROLE_NAME, acltype=acltype,
                                      topic=topic, allow=True, priority=0)
        # Not "_ignore_exists": dynsec answers 'Internal error' (not 'already exists') when the
        # client already holds the role, so look first.
        data = await self.broker.dynsec("getClient", username=self.s.mqtt_username)
        held = {r.get("rolename") for r in data.get("client", {}).get("roles", [])}
        if ROLE_NAME not in held:
            await self.broker.dynsec("addClientRole", username=self.s.mqtt_username,
                                     rolename=ROLE_NAME, priority=0)
        self._provisioned = True
        log.info("Home Assistant publishing: role '%s' ready", ROLE_NAME)

    def _connect(self) -> None:
        s = self.s
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                        client_id=f"mosquitto-manager-ha-{secrets.token_hex(3)}",
                        protocol=mqtt.MQTTv311)
        c.username_pw_set(s.mqtt_username, s.mqtt_password)
        _apply_tls(c, s)
        c.will_set(self.topics.status, "offline", qos=1, retain=True)
        c.reconnect_delay_set(min_delay=1, max_delay=30)
        c.on_connect = self._mqtt_connected
        c.on_disconnect = lambda *_a, **_k: setattr(self, "_ready", False)
        c.on_message = self._mqtt_message
        self._client = c
        c.connect_async(s.mqtt_host, s.mqtt_port, keepalive=30)
        c.loop_start()

    def _mqtt_connected(self, client, _ud, _flags, reason_code, _props=None) -> None:
        if reason_code.is_failure:
            self._ready = False
            self.error = f"Home Assistant publisher refused by the broker: {reason_code}"
            log.error(self.error)
            return
        client.subscribe(self.topics.birth, 0)
        client.publish(self.topics.status, "online", qos=1, retain=True)
        self._ready = True
        self._need_discovery = True
        self._wake_threadsafe()

    def _mqtt_message(self, _client, _ud, msg) -> None:
        if msg.topic == self.topics.birth and msg.payload.decode(errors="replace") == "online":
            self._need_discovery = True  # Home Assistant restarted: send everything again
            self._wake_threadsafe()

    def _wake_threadsafe(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._wake.set)

    def _send(self, topic: str, payload: str, retain: bool = True) -> None:
        if self._cache.get(topic) == payload:
            return
        self._cache[topic] = payload
        if self._publish_fn is not None:
            self._publish_fn(topic, payload, retain)
        elif self._client is not None:
            self._client.publish(topic, payload, qos=1, retain=retain)

    def _send_discovery(self, component: str, object_id: str, cfg: dict[str, Any]) -> None:
        self._send(self.topics.discovery(component, object_id), _json(cfg))

    def _clear_discovery(self, component: str, object_id: str) -> None:
        topic = self.topics.discovery(component, object_id)
        self._cache.pop(topic, None)
        self._send(topic, "")

    async def _tick(self) -> None:
        resend = self._need_discovery
        if resend:
            self._cache.clear()
            self._users = {}
            self._need_discovery = False
            self._users_dirty = True
            await asyncio.sleep(random.uniform(0, 1.5) if not self._injected else 0)

        snap = self.broker.snapshot()
        for entity in BROKER_ENTITIES:
            component, key, cfg = broker_config(self.s, self.topics, entity, snap.get("version"))
            self._send_discovery(component, key, cfg)

        now = time.time()
        if self._users_dirty or now - self._last_users > USERS_RESYNC_SECONDS:
            raw = await self.broker.list_clients()
            self._users_data = merge_clients(raw, self.tracker, self.s.mqtt_username, self.s.tls_ports)
            self._users_dirty = False
            self._last_users = now
            if self.s.ha_user_sensors:
                self._sync_users()

        people = [c for c in self._users_data if not c["is_manager"]]
        states = broker_states(
            snap, users_total=len(people), users_online=sum(1 for c in people if c["online"]),
            failed_24h=self.tracker.count_events("auth_failed", now - 86400),
            failed_10m=self.tracker.count_events("auth_failed", now - 600),
            threshold=self.s.ha_failed_threshold,
            last_failed=self.tracker.last_event("auth_failed"),
            cert=self.certs.primary() if self.certs is not None else None)
        for key, payload in states.items():
            self._send(self.topics.state(key), payload)

        if self.s.ha_user_sensors:
            for c in people:
                ukey = self._users.get(c["username"])
                if ukey:
                    state, attrs = user_payloads(c)
                    self._send(self.topics.user_state(ukey), state)
                    self._send(self.topics.user_attrs(ukey), attrs)

    def _sync_users(self) -> None:
        """Create entities for new users and remove them for deleted users."""
        current = {c["username"]: user_key(c["username"])
                   for c in self._users_data if not c["is_manager"]}
        for username, ukey in list(self._users.items()):
            if username not in current:
                self._clear_discovery("binary_sensor", f"user_{ukey}")
                for topic in (self.topics.user_state(ukey), self.topics.user_attrs(ukey)):
                    self._cache.pop(topic, None)
                    self._send(topic, "")
        for username in current:
            if username not in self._users:
                component, object_id, cfg = user_config(self.s, self.topics, username)
                self._send_discovery(component, object_id, cfg)
        self._users = current
