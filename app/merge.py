"""Combining Dynamic Security's client list with live connection data."""

from __future__ import annotations

from typing import Any

from .tracker import Tracker


def normalize_client(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": raw["username"],
        "textname": raw.get("textname", ""),
        "textdescription": raw.get("textdescription", ""),
        "clientid": raw.get("clientid", ""),
        "disabled": bool(raw.get("disabled", False)),
        "roles": raw.get("roles", []),
        "groups": raw.get("groups", []),
    }


def session_dict(s) -> dict[str, Any]:
    return {"address": s.address, "port": s.port, "clientid": s.clientid,
            "protocol": s.protocol, "keepalive": s.keepalive, "since": s.since}


def merge_clients(raw_clients: list[dict], tracker: Tracker, manager_user: str) -> list[dict]:
    """Combine Dynamic Security's client list with live data.

    Mosquitto >= 2.1 reports ``connections`` (addresses) for each client, which is
    authoritative. On older brokers the list is rebuilt from the log feed.
    """
    out = []
    for raw in raw_clients:
        c = normalize_client(raw)
        sessions = tracker.sessions_for(c["username"])
        saved = 0
        if "connections" in raw:
            remaining = list(sessions)
            conns = []
            for entry in raw["connections"]:
                addr = entry.get("address")
                if not addr:
                    # Mosquitto also lists persistent sessions of clients that are not connected;
                    # after a broker restart they come back from disk with no address at all.
                    saved += 1
                    continue
                match = next((s for s in remaining if s.address == addr), None)
                if match:
                    remaining.remove(match)
                    conns.append(session_dict(match))
                else:
                    conns.append({"address": addr})
        else:
            conns = [session_dict(s) for s in sessions]
        c["connections"] = conns
        c["saved_sessions"] = saved
        c["online"] = bool(conns)
        c["last_seen"] = tracker.last_seen.get(c["username"])
        c["is_manager"] = c["username"] == manager_user
        out.append(c)
    return out
