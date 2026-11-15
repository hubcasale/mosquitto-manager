"""Data for the connection map: who is connected, from which host, and who was refused."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .tracker import Tracker


class HostNames:
    """Friendly names for client addresses ("192.168.178.125" -> "Dongle Zigbee")."""

    def __init__(self, path: Path):
        self.path = path
        self._names: dict[str, str] = {}
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                self._names = {str(k): str(v) for k, v in data.items()}
        except (OSError, ValueError):
            pass

    def all(self) -> dict[str, str]:
        return dict(self._names)

    def set(self, address: str, name: str) -> None:
        name = name.strip()
        if name:
            self._names[address] = name
        else:
            self._names.pop(address, None)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._names, ensure_ascii=False))
            tmp.replace(self.path)
        except OSError:
            pass  # names still work for this run


def build_map(clients: list[dict[str, Any]], tracker: Tracker, names: dict[str, str],
              now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    hosts: dict[str, dict[str, Any]] = {}
    offline: list[dict[str, Any]] = []

    def host_for(address: str) -> dict[str, Any]:
        return hosts.setdefault(address, {
            "address": address, "alias": names.get(address), "label": names.get(address) or address,
            "clients": []})

    for c in clients:
        conns = c.get("connections", [])
        if not conns:
            offline.append({"username": c["username"], "disabled": c["disabled"],
                            "is_manager": c["is_manager"],
                            "last_seen": (c.get("last_seen") or {}).get("ts")})
            continue
        for conn in conns:
            host_for(conn.get("address") or "?")["clients"].append({
                "username": c["username"], "clientid": conn.get("clientid"),
                "protocol": conn.get("protocol"), "keepalive": conn.get("keepalive"),
                "since": conn.get("since"), "is_manager": c["is_manager"],
                "disabled": c["disabled"],
                "roles": [r["rolename"] for r in c.get("roles", [])],
                "groups": [g["groupname"] for g in c.get("groups", [])],
            })

    refused: dict[str, dict[str, Any]] = {}
    for ev in tracker.events(limit=1000, kinds={"auth_failed"}):
        if ev["ts"] < now - 86400:
            continue
        addr = ev.get("address") or "?"
        r = refused.setdefault(addr, {
            "address": addr, "alias": names.get(addr), "label": names.get(addr) or addr,
            "attempts": 0, "clientids": [], "last": 0})
        r["attempts"] += 1
        r["last"] = max(r["last"], ev["ts"])
        cid = ev.get("clientid")
        if cid and cid not in r["clientids"] and len(r["clientids"]) < 6:
            r["clientids"].append(cid)

    return {
        "hosts": sorted(hosts.values(), key=lambda h: (-len(h["clients"]), h["address"])),
        "offline": sorted(offline, key=lambda o: o["username"]),
        "refused": sorted(refused.values(), key=lambda r: -r["attempts"]),
    }
