from app.tracker import Tracker, split_address, is_internal

NOW = 1_794_739_472.0


def log(tracker, line, level="N"):
    return tracker.ingest_log(level, f"{int(NOW)}: {line}", now=NOW)


def test_split_address_ipv4_and_ipv6():
    assert split_address("192.168.1.5:5123") == ("192.168.1.5", "5123")
    assert split_address("::1:5123") == ("::1", "5123")
    assert split_address("nohost") == ("nohost", "")


def test_connect_creates_session_and_event():
    t = Tracker()
    ev = log(t, "New client connected from 192.168.1.50:51845 as shelly-abc "
                "(p5, c1, k30, u'shelly1').")
    assert ev.kind == "connect"
    assert ev.username == "shelly1" and ev.clientid == "shelly-abc"
    s = t.sessions_for("shelly1")[0]
    assert (s.address, s.port, s.protocol, s.keepalive) == ("192.168.1.50", "51845", "MQTT 5", 30)
    assert t.last_seen["shelly1"]["address"] == "192.168.1.50"


def test_protocol_numbering_of_mosquitto_2_0_and_2_1():
    t = Tracker()
    log(t, "New client connected from 10.0.0.2:1 as a (p2, c1, k60, u'u').")  # 2.0.x, MQTT 3.1.1
    log(t, "New client connected from 10.0.0.3:1 as b (p4, c1, k60, u'u').")  # 2.1.x, MQTT 3.1.1
    log(t, "New client connected from 10.0.0.4:1 as c (p5, c1, k60, u'u').")
    assert {s.clientid: s.protocol for s in t.live_sessions()} == {
        "a": "MQTT 3.1.1", "b": "MQTT 3.1.1", "c": "MQTT 5"}


def test_connect_without_username_and_with_odd_clientid():
    t = Tracker()
    ev = log(t, "New client connected from 10.0.0.2:1000 as my client (x) (p4, c0, k60).")
    assert ev.clientid == "my client (x)"
    assert ev.username is None
    assert t.live_sessions()[0].clean_session is False


def test_disconnect_removes_session_and_keeps_user():
    t = Tracker()
    log(t, "New client connected from 192.168.1.50:51845 as c1 (p4, c1, k60, u'bob').")
    ev = log(t, "Client c1 [192.168.1.50:51845] disconnected.")
    assert ev.kind == "disconnect"
    assert ev.username == "bob"
    assert not t.sessions


def test_disconnect_with_reason():
    t = Tracker()
    ev = log(t, "Client c1 [10.0.0.9:2000] disconnected: protocol error.")
    assert ev.kind == "disconnect" and ev.reason == "protocol error"


def test_closed_its_connection_matches_by_clientid():
    t = Tracker()
    log(t, "New client connected from 10.0.0.2:1000 as dev1 (p4, c1, k60, u'u1').")
    ev = log(t, "Client dev1 closed its connection.")
    assert ev.kind == "disconnect" and ev.username == "u1"
    assert not t.sessions


def test_timeout_is_a_disconnect():
    t = Tracker()
    log(t, "New client connected from 10.0.0.2:1000 as dev1 (p4, c1, k60, u'u1').")
    ev = log(t, "Client dev1 has exceeded timeout, disconnecting.")
    assert ev.kind == "disconnect"
    assert not t.sessions


def test_not_authorised_is_auth_failed():
    t = Tracker()
    ev = log(t, "Client wrongpw [192.168.65.1:49013] disconnected: not authorised.")
    assert ev.kind == "auth_failed"
    assert ev.address == "192.168.65.1" and ev.clientid == "wrongpw"
    assert ev.level == "warning"
    assert t.count_events("auth_failed", NOW - 10) == 1


def test_old_style_not_authorised_line():
    t = Tracker()
    ev = log(t, "Client ghost disconnected, not authorised.")
    assert ev.kind == "auth_failed" and ev.clientid == "ghost"


def test_dynsec_audit_line_and_password_masking():
    t = Tracker()
    ev = log(t, "dynsec: mgr/admin | setClientPassword | username=shelly1 | password=hunter2",
             "I")
    assert ev.kind == "admin"
    assert ev.actor == "mgr/admin"
    assert ev.extra["command"] == "setClientPassword"
    assert "hunter2" not in ev.message and "hunter2" not in ev.extra["args"]


def test_read_only_dynsec_commands_are_not_events():
    t = Tracker()
    assert log(t, "dynsec: mgr/admin | listClients | verbose=true | count=-1 | offset=0",
               "I") is None
    assert log(t, "dynsec: mgr/admin | getClient | username=x", "I") is None
    assert t.events() == []


def test_noise_is_ignored_and_warnings_kept():
    t = Tracker()
    assert log(t, "New connection from 1.2.3.4:5 on port 1883.") is None
    assert log(t, "mosquitto version 2.1.2 running", "I") is None
    ev = log(t, "Socket error on client x, disconnecting.", "W")
    assert ev.kind == "log" and ev.level == "warning"


def test_internal_clients_hidden_by_default():
    t = Tracker()
    log(t, "New client connected from 10.0.0.2:1000 as mm-test-ab12 (p4, c1, k10, u'x').")
    log(t, "Client mm-test-ab12 [10.0.0.2:1000] disconnected: not authorised.")
    assert is_internal("mosquitto-manager-1a2b3c")
    assert t.events() == []
    assert len(t.events(include_internal=True)) == 2
    assert t.count_events("auth_failed", NOW - 10) == 0
    assert "x" not in t.last_seen


def test_events_filter_limit_and_since():
    t = Tracker()
    for i in range(5):
        log(t, f"New client connected from 10.0.0.{i}:1 as c{i} (p4, c1, k60, u'u{i}').")
    log(t, "Client zzz [9.9.9.9:1] disconnected: not authorised.")
    assert [e["kind"] for e in t.events(kinds={"auth_failed"})] == ["auth_failed"]
    assert len(t.events(limit=3)) == 3
    assert t.events(limit=3)[0]["kind"] == "auth_failed"  # newest first
    assert len(t.events(since_id=4)) == 2


def test_reset_sessions_and_persistence_roundtrip():
    t = Tracker()
    log(t, "New client connected from 10.0.0.2:1000 as dev1 (p4, c1, k60, u'u1').")
    dump = t.dump()
    t.reset_sessions()
    assert not t.sessions
    t2 = Tracker()
    t2.load(dump)
    assert t2.last_seen["u1"]["address"] == "10.0.0.2"
    assert len(t2.events()) == 1
    t2.load({"events": [{"bad": 1}]})  # corrupt data must not raise
    assert t2.events() == []


def test_listener_port_is_taken_from_the_new_connection_line():
    t = Tracker()
    assert log(t, "New connection from 10.0.0.2:1000 on port 8883.") is None  # not an event itself
    log(t, "New client connected from 10.0.0.2:1000 as z2m (p4, c1, k60, u'zigbee2mqtt').")
    log(t, "New connection from 10.0.0.3:2000 on port 1883.")
    log(t, "New client connected from 10.0.0.3:2000 as old (p4, c1, k60, u'mqtt_user').")
    by = {s.clientid: s.listener_port for s in t.live_sessions()}
    assert by == {"z2m": 8883, "old": 1883}
    assert t.events()[0]["extra"]["listener_port"] == 1883  # newest first; connect events carry it too


def test_listener_port_is_not_mixed_up_between_addresses():
    t = Tracker()
    log(t, "New connection from 10.0.0.2:1000 on port 8883.")
    log(t, "New connection from 10.0.0.3:2000 on port 1883.")
    log(t, "New client connected from 10.0.0.3:2000 as b (p4, c1, k60, u'u').")
    log(t, "New client connected from 10.0.0.2:1000 as a (p4, c1, k60, u'u').")
    assert {s.clientid: s.listener_port for s in t.live_sessions()} == {"a": 8883, "b": 1883}
    log(t, "New client connected from 10.0.0.9:3000 as c (p4, c1, k60, u'u').")  # no preceding line
    assert {s.clientid: s.listener_port for s in t.live_sessions()}["c"] is None


def test_failed_logins_remember_the_port():
    t = Tracker()
    log(t, "New connection from 6.6.6.6:5 on port 1883.")
    ev = log(t, "Client scan [6.6.6.6:5] disconnected: not authorised.")
    assert ev.kind == "auth_failed" and ev.extra["listener_port"] == 1883


def test_encryption_summary_counts_and_unknowns():
    t = Tracker()
    log(t, "New connection from 10.0.0.2:1 on port 8883.")
    log(t, "New client connected from 10.0.0.2:1 as a (p4, c1, k60, u'u').")
    log(t, "New connection from 10.0.0.3:2 on port 1883.")
    log(t, "New client connected from 10.0.0.3:2 as b (p4, c1, k60, u'u').")
    log(t, "New connection from 10.0.0.4:3 on port 1883.")
    log(t, "New client connected from 10.0.0.4:3 as mm-test-x (p4, c1, k60, u'u').")  # this app's own probe
    log(t, "New client connected from 10.0.0.5:4 as c (p4, c1, k60, u'u').")  # port line missing
    summary = t.encryption_summary(frozenset({8883}), connected=6)
    assert summary == {"tls": 1, "plain": 1, "unknown": 1 + 2}  # c, plus 2 connections never observed
    assert t.encryption_summary(frozenset({8883, 8884}), connected=None)["tls"] == 1
