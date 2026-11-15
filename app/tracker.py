"""Turns Mosquitto's log lines (published on $SYS/broker/log/*) into events and
a best-effort list of live sessions.

The broker has to be configured with ``log_dest topic`` for this to work; see
docs/mosquitto.conf.example.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

LEVELS = {"E": "error", "W": "warning", "N": "notice", "I": "info", "D": "debug"}
# Mosquitto 2.0 logs an internal enum (p1 = 3.1, p2 = 3.1.1), 2.1 logs the protocol
# version number (p3 = 3.1, p4 = 3.1.1). MQTT 5 is p5 in both.
PROTOCOLS = {"1": "MQTT 3.1", "2": "MQTT 3.1.1", "3": "MQTT 3.1", "4": "MQTT 3.1.1", "5": "MQTT 5"}

# Client ids used by this app itself; their events are flagged "internal".
INTERNAL_PREFIXES = ("mosquitto-manager", "mm-test-")

_TS = re.compile(r"^(\d{9,11}):\s+(.*)$", re.DOTALL)
_CONNECT = re.compile(
    r"^New client connected from (?P<addr>.+) as (?P<cid>.+?) "
    r"\(p(?P<proto>\d+), c(?P<clean>\d+), k(?P<ka>\d+)(?:, u'(?P<user>.*)')?\)\.?$"
)
_CLIENT_LINE = re.compile(
    r"^Client (?P<cid>.+?)(?: \[(?P<addr>[^\]]+)\])? "
    r"(?:disconnected|closed its connection|has exceeded timeout|has been disconnected)"
    r"(?P<rest>.*)$"
)
_DYNSEC = re.compile(r"^dynsec: (?P<actor>.*?) \| (?P<cmd>\S+)(?: \| (?P<args>.*))?$")
_PASSWORD = re.compile(r"(password=)\S+", re.IGNORECASE)


def split_address(addr: str) -> tuple[str, str]:
    """'192.168.1.5:5123' -> ('192.168.1.5', '5123'); IPv6 safe."""
    ip, _, port = addr.rpartition(":")
    return (ip, port) if ip else (addr, "")


def is_internal(clientid: str | None) -> bool:
    return bool(clientid) and clientid.startswith(INTERNAL_PREFIXES)


@dataclass
class Session:
    clientid: str
    address: str
    port: str
    username: str | None
    protocol: str
    keepalive: int
    clean_session: bool
    since: float

    @property
    def key(self) -> str:
        return f"{self.address}:{self.port}"


@dataclass
class Event:
    id: int
    ts: float
    kind: str  # connect | disconnect | auth_failed | admin | log
    level: str
    message: str
    clientid: str | None = None
    username: str | None = None
    address: str | None = None
    reason: str | None = None
    actor: str | None = None
    internal: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class Tracker:
    def __init__(self, max_events: int = 1000):
        self._lock = threading.Lock()
        self._events: deque[Event] = deque(maxlen=max_events)
        self._next_id = 1
        self.sessions: dict[str, Session] = {}
        self.last_seen: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ parsing
    def ingest_log(self, level_char: str, payload: str, now: float | None = None) -> Event | None:
        """Process one message received on $SYS/broker/log/<level>."""
        now = time.time() if now is None else now
        level = LEVELS.get(level_char.upper(), "info")
        ts = now
        text = payload.strip()
        m = _TS.match(text)
        if m:
            ts = float(m.group(1))
            text = m.group(2).strip()
        if not text:
            return None

        with self._lock:
            if (m := _CONNECT.match(text)):
                return self._on_connect(m, ts, level, text)
            if (m := _DYNSEC.match(text)):
                if m.group("cmd").startswith(("list", "get")):
                    return None  # read-only commands (every refresh) are just noise
                return self._add(
                    Event(0, ts, "admin", level, _PASSWORD.sub(r"\1******", text),
                          actor=m.group("actor"),
                          extra={"command": m.group("cmd"),
                                 "args": _PASSWORD.sub(r"\1******", m.group("args") or "")}))
            if (m := _CLIENT_LINE.match(text)):
                return self._on_client_line(m, ts, level, text)
            if text.startswith("New connection from "):
                return None  # noise: the following line says what happened
            if level in ("error", "warning"):
                return self._add(Event(0, ts, "log", level, text))
        return None

    def _on_connect(self, m: re.Match, ts: float, level: str, text: str) -> Event:
        ip, port = split_address(m.group("addr"))
        user = m.group("user") or None
        s = Session(
            clientid=m.group("cid"), address=ip, port=port, username=user,
            protocol=PROTOCOLS.get(m.group("proto"), f"p{m.group('proto')}"),
            keepalive=int(m.group("ka")), clean_session=m.group("clean") == "1", since=ts,
        )
        self.sessions[s.key] = s
        if user and not is_internal(s.clientid):
            self.last_seen[user] = {"ts": ts, "address": ip}
        return self._add(Event(0, ts, "connect", level, text, clientid=s.clientid,
                               username=user, address=ip, internal=is_internal(s.clientid),
                               extra={"protocol": s.protocol, "keepalive": s.keepalive}))

    def _on_client_line(self, m: re.Match, ts: float, level: str, text: str) -> Event:
        cid = m.group("cid")
        addr = m.group("addr")
        rest = (m.group("rest") or "").strip(" .:,")
        ip = port = None
        if addr:
            ip, port = split_address(addr)

        session = None
        if addr and f"{ip}:{port}" in self.sessions:
            session = self.sessions.pop(f"{ip}:{port}")
        else:
            for key, s in list(self.sessions.items()):
                if s.clientid == cid:
                    session = self.sessions.pop(key)
                    break
        user = session.username if session else None
        if session and not ip:
            ip = session.address

        failed = "not authori" in rest.lower() or "not authori" in text.lower()
        if user and not is_internal(cid):
            self.last_seen[user] = {"ts": ts, "address": ip}
        return self._add(Event(
            0, ts, "auth_failed" if failed else "disconnect",
            "warning" if failed else level, text, clientid=cid, username=user,
            address=ip, reason=rest or None, internal=is_internal(cid)))

    def _add(self, ev: Event) -> Event:
        ev.id = self._next_id
        self._next_id += 1
        self._events.append(ev)
        return ev

    # ------------------------------------------------------------------ queries
    def events(self, limit: int = 200, kinds: set[str] | None = None,
               include_internal: bool = False, since_id: int = 0) -> list[dict]:
        with self._lock:
            out = []
            for ev in reversed(self._events):
                if ev.id <= since_id:
                    break
                if kinds and ev.kind not in kinds:
                    continue
                if ev.internal and not include_internal:
                    continue
                out.append(asdict(ev))
                if len(out) >= limit:
                    break
            return out

    def count_events(self, kind: str, since_ts: float) -> int:
        with self._lock:
            return sum(1 for e in self._events
                       if e.kind == kind and e.ts >= since_ts and not e.internal)

    def last_event(self, kind: str) -> dict | None:
        with self._lock:
            for ev in reversed(self._events):
                if ev.kind == kind and not ev.internal:
                    return asdict(ev)
        return None

    def sessions_for(self, username: str) -> list[Session]:
        with self._lock:
            return [s for s in self.sessions.values() if s.username == username]

    def live_sessions(self, include_internal: bool = False) -> list[Session]:
        with self._lock:
            return [s for s in self.sessions.values()
                    if include_internal or not is_internal(s.clientid)]

    def reset_sessions(self) -> None:
        """Called when the broker connection is (re)established: old state is stale."""
        with self._lock:
            self.sessions.clear()

    # -------------------------------------------------------------- persistence
    def dump(self) -> dict[str, Any]:
        with self._lock:
            return {
                "version": 1,
                "next_id": self._next_id,
                "events": [asdict(e) for e in self._events],
                "last_seen": self.last_seen,
            }

    def load(self, data: dict[str, Any]) -> None:
        with self._lock:
            try:
                self._next_id = int(data.get("next_id", 1))
                for raw in data.get("events", []):
                    self._events.append(Event(**raw))
                self.last_seen = dict(data.get("last_seen", {}))
            except (TypeError, ValueError):
                self._events.clear()
                self.last_seen = {}


def save_state(tracker: Tracker, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(tracker.dump()))
    tmp.replace(path)


def load_state(tracker: Tracker, path: Path) -> None:
    try:
        tracker.load(json.loads(path.read_text()))
    except (OSError, ValueError):
        pass
