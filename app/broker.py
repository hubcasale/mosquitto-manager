"""MQTT connection to the broker: $SYS statistics, log feed and Dynamic Security RPC."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import threading
import time
import uuid
from collections import deque
from typing import Any

import paho.mqtt.client as mqtt

from .config import Settings
from .tracker import Tracker

log = logging.getLogger("mosquitto_manager.broker")

DYNSEC_TOPIC = "$CONTROL/dynamic-security/v1"
DYNSEC_RESPONSE_TOPIC = "$CONTROL/dynamic-security/v1/response"
LOG_PREFIX = "$SYS/broker/log/"


class BrokerUnavailable(Exception):
    """The manager is not connected to the broker."""


class DynsecError(Exception):
    """The Dynamic Security plugin rejected a command."""


class DynsecTimeout(Exception):
    """No answer from the Dynamic Security plugin."""


_UPTIME = re.compile(r"^(\d+)")


def _num(value: str) -> int | float | str:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _apply_tls(client: mqtt.Client, s: Settings) -> None:
    if not s.mqtt_tls:
        return
    client.tls_set(ca_certs=s.mqtt_ca_file)
    if s.mqtt_tls_insecure:
        client.tls_insecure_set(True)


class Broker:
    def __init__(self, settings: Settings, tracker: Tracker):
        self.settings = settings
        self.tracker = tracker
        self.client_id = f"mosquitto-manager-{secrets.token_hex(3)}"
        self.stats: dict[str, str] = {}
        self.history: deque[dict[str, Any]] = deque(maxlen=240)  # ~1 h at 15 s
        self.connected = False
        self.last_error: str | None = None
        self.dynsec_state = "unknown"  # unknown | ok | no_response
        self.dynsec_error: str | None = None
        self.supports_connections: bool | None = None  # seen "connections" in listClients?
        self.log_feed_seen = False  # any message on $SYS/broker/log/* received?
        self.on_event = None  # optional callback(Event), called on the event loop
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._lock = threading.Lock()
        self._client: mqtt.Client | None = None

    # ----------------------------------------------------------------- lifecycle
    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        s = self.settings
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id,
                        protocol=mqtt.MQTTv311)
        c.username_pw_set(s.mqtt_username, s.mqtt_password)
        _apply_tls(c, s)
        c.reconnect_delay_set(min_delay=1, max_delay=30)
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_connect_fail = self._on_connect_fail
        c.on_message = self._on_message
        self._client = c
        c.connect_async(s.mqtt_host, s.mqtt_port, keepalive=30)
        c.loop_start()

    def stop(self) -> None:
        if self._client:
            self._client.disconnect()
            self._client.loop_stop()

    # ------------------------------------------------------------ paho callbacks
    def _on_connect(self, client, _userdata, _flags, reason_code, _props=None):
        if reason_code.is_failure:
            self.connected = False
            self.last_error = f"Broker refused the connection: {reason_code}"
            log.error(self.last_error)
            return
        log.info("Connected to broker %s:%s", self.settings.mqtt_host, self.settings.mqtt_port)
        self.connected = True
        self.last_error = None
        self.tracker.reset_sessions()
        client.subscribe([(DYNSEC_RESPONSE_TOPIC, 1), ("$SYS/#", 0)])

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _props=None):
        if self.connected:
            log.warning("Disconnected from broker: %s", reason_code)
        self.connected = False
        self.dynsec_state = "unknown"
        self.last_error = f"Disconnected: {reason_code}"

    def _on_connect_fail(self, _client, _userdata):
        self.connected = False
        self.last_error = f"Cannot reach {self.settings.mqtt_host}:{self.settings.mqtt_port}"

    def _on_message(self, _client, _userdata, msg):
        topic = msg.topic
        try:
            payload = msg.payload.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - defensive
            return
        if topic == DYNSEC_RESPONSE_TOPIC:
            self._on_dynsec_response(payload)
        elif topic.startswith(LOG_PREFIX):
            self.log_feed_seen = True
            ev = self.tracker.ingest_log(topic[len(LOG_PREFIX):], payload)
            if ev is not None and self.on_event is not None and self._loop is not None:
                self._loop.call_soon_threadsafe(self.on_event, ev)
        elif topic.startswith("$SYS/"):
            with self._lock:
                self.stats[topic[5:]] = payload

    def _on_dynsec_response(self, payload: str) -> None:
        try:
            responses = json.loads(payload).get("responses", [])
        except (ValueError, AttributeError):
            return
        for r in responses:
            cid = r.get("correlationData")
            fut = self._pending.get(cid)
            if fut is not None and self._loop is not None:
                self._loop.call_soon_threadsafe(_resolve, fut, r)

    # -------------------------------------------------------------- Dynamic Security
    async def dynsec(self, command: str, timeout: float = 8.0, **params: Any) -> dict[str, Any]:
        """Run one Dynamic Security command and return its ``data`` payload."""
        if not self.connected or self._client is None or self._loop is None:
            raise BrokerUnavailable(self.last_error or "Not connected to the broker")
        cid = uuid.uuid4().hex
        fut: asyncio.Future = self._loop.create_future()
        self._pending[cid] = fut
        body = {"commands": [{"command": command, **params, "correlationData": cid}]}
        try:
            self._client.publish(DYNSEC_TOPIC, json.dumps(body), qos=1)
            try:
                resp = await asyncio.wait_for(fut, timeout)
            except asyncio.TimeoutError:
                self.dynsec_state = "no_response"
                self.dynsec_error = (
                    "No answer from the Dynamic Security plugin. Check that the plugin is "
                    "loaded in mosquitto.conf and that the manager's user has the admin role."
                )
                raise DynsecTimeout(self.dynsec_error) from None
        finally:
            self._pending.pop(cid, None)
        self.dynsec_state = "ok"
        self.dynsec_error = None
        if "error" in resp:
            raise DynsecError(str(resp["error"]))
        return resp.get("data") or {}

    async def probe(self) -> None:
        """Cheap command used to find out whether Dynamic Security answers."""
        try:
            await self.dynsec("getDefaultACLAccess", timeout=3.0)
        except (DynsecError, DynsecTimeout, BrokerUnavailable):
            pass

    async def list_clients(self) -> list[dict[str, Any]]:
        data = await self.dynsec("listClients", verbose=True)
        clients = data.get("clients", [])
        if clients:
            self.supports_connections = any("connections" in c for c in clients)
        return clients

    # ---------------------------------------------------------------- statistics
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            st = dict(self.stats)

        def g(key: str):
            v = st.get(key)
            return _num(v) if v is not None else None

        uptime = None
        raw = st.get("broker/uptime")
        if raw and (m := _UPTIME.match(raw)):
            uptime = int(m.group(1))
        return {
            "version": (st.get("broker/version") or "").replace("mosquitto version ", "") or None,
            "uptime": uptime,
            "clients_connected": g("broker/clients/connected"),
            "clients_total": g("broker/clients/total"),
            "clients_disconnected": g("broker/clients/disconnected"),
            "subscriptions": g("broker/subscriptions/count"),
            "retained": g("broker/retained messages/count"),
            "messages_received": g("broker/messages/received"),
            "messages_sent": g("broker/messages/sent"),
            "msg_rate_in": g("broker/load/messages/received/1min"),
            "msg_rate_out": g("broker/load/messages/sent/1min"),
            "bytes_received": g("broker/bytes/received"),
            "bytes_sent": g("broker/bytes/sent"),
            "dropped": g("broker/publish/messages/dropped"),
            "heap": g("broker/heap/current"),
            "has_sys": bool(st),
        }

    def sample_history(self) -> None:
        snap = self.snapshot()
        if not snap["has_sys"]:
            return
        self.history.append({
            "t": int(time.time()),
            "connected": snap["clients_connected"],
            "in": snap["msg_rate_in"],
            "out": snap["msg_rate_out"],
        })

    # ----------------------------------------------------------------- test login
    async def test_login(self, username: str, password: str, clientid: str | None = None,
                         timeout: float = 6.0) -> dict[str, Any]:
        """Open a short-lived connection with the given credentials."""
        assert self._loop is not None
        s = self.settings
        fut: asyncio.Future = self._loop.create_future()
        started = time.monotonic()

        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                        client_id=clientid or f"mm-test-{secrets.token_hex(3)}",
                        protocol=mqtt.MQTTv311)
        c.username_pw_set(username, password)
        _apply_tls(c, s)

        def on_connect(_c, _u, _f, rc, _p=None):
            self._loop.call_soon_threadsafe(_resolve, fut, {
                "ok": not rc.is_failure, "reason": str(rc),
            })

        def on_fail(_c, _u):
            self._loop.call_soon_threadsafe(_resolve, fut, {
                "ok": False, "reason": f"Cannot reach {s.mqtt_host}:{s.mqtt_port}",
            })

        c.on_connect = on_connect
        c.on_connect_fail = on_fail
        c.reconnect_delay_set(min_delay=1, max_delay=1)
        try:
            c.connect_async(s.mqtt_host, s.mqtt_port, keepalive=10)
            c.loop_start()
            try:
                result = await asyncio.wait_for(fut, timeout)
            except asyncio.TimeoutError:
                result = {"ok": False, "reason": "Timed out waiting for the broker"}
        finally:
            try:
                c.disconnect()
            except Exception:  # pragma: no cover
                pass
            c.loop_stop()
        result["ms"] = int((time.monotonic() - started) * 1000)
        return result


def _resolve(fut: asyncio.Future, value: Any) -> None:
    if not fut.done():
        fut.set_result(value)
