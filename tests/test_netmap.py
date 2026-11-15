from app.merge import merge_clients
from app.netmap import HostNames, build_map
from app.tracker import Tracker

NOW = 1_794_739_472.0


def log(t, line):
    return t.ingest_log("N", f"{int(NOW)}: {line}", now=NOW)


def sample():
    t = Tracker()
    log(t, "New client connected from 10.0.0.2:1000 as ha-core (p4, c1, k60, u'homeassistant').")
    log(t, "New client connected from 10.0.0.2:1001 as z2m (p4, c1, k60, u'zigbee2mqtt').")
    log(t, "New client connected from 10.0.0.9:1002 as dongle (p5, c1, k30, u'dongle_m').")
    log(t, "Client scan1 [6.6.6.6:5] disconnected: not authorised.")
    log(t, "Client scan2 [6.6.6.6:6] disconnected: not authorised.")
    log(t, "Client old [10.0.0.9:7] disconnected: not authorised.")
    log(t, "Client mm-test-ab [7.7.7.7:7] disconnected: not authorised.")  # this app's own probe
    raw = [{"username": n, "roles": [{"rolename": "r"}], "groups": []} for n in
           ("homeassistant", "zigbee2mqtt", "dongle_m", "esplora", "mgr")]
    return t, merge_clients(raw, t, "mgr")


def test_build_map_groups_clients_by_host():
    t, merged = sample()
    m = build_map(merged, t, {"10.0.0.9": "Dongle"}, now=NOW)
    hosts = {h["address"]: h for h in m["hosts"]}
    assert [c["username"] for c in hosts["10.0.0.2"]["clients"]] == ["homeassistant", "zigbee2mqtt"]
    assert hosts["10.0.0.9"]["label"] == "Dongle" and hosts["10.0.0.9"]["alias"] == "Dongle"
    assert hosts["10.0.0.2"]["label"] == "10.0.0.2" and hosts["10.0.0.2"]["alias"] is None
    assert m["hosts"][0]["address"] == "10.0.0.2"  # busiest host first
    c = hosts["10.0.0.2"]["clients"][0]
    assert c["clientid"] == "ha-core" and c["protocol"] == "MQTT 3.1.1" and c["roles"] == ["r"]
    assert [o["username"] for o in m["offline"]] == ["esplora", "mgr"]


def test_build_map_refused_sources_exclude_internal_and_old():
    t, merged = sample()
    old = t.ingest_log("N", f"{int(NOW) - 2 * 86400}: Client ancient [5.5.5.5:1] disconnected: not authorised.",
                       now=NOW - 2 * 86400)
    assert old is not None
    m = build_map(merged, t, {}, now=NOW)
    refused = {r["address"]: r for r in m["refused"]}
    assert set(refused) == {"6.6.6.6", "10.0.0.9"}  # no 7.7.7.7 (internal), no 5.5.5.5 (too old)
    assert refused["6.6.6.6"]["attempts"] == 2 and refused["6.6.6.6"]["clientids"] == ["scan2", "scan1"]
    assert m["refused"][0]["address"] == "6.6.6.6"


def test_dynsec_addresses_without_log_details_still_appear():
    t = Tracker()
    merged = merge_clients([{"username": "u", "roles": [], "groups": [],
                             "connections": [{"address": "8.8.8.8"}]}], t, "mgr")
    m = build_map(merged, t, {}, now=NOW)
    assert m["hosts"][0]["clients"][0]["clientid"] is None


def test_host_names_persist(tmp_path):
    path = tmp_path / "sub" / "hosts.json"
    names = HostNames(path)
    names.set("10.0.0.2", "  Server  ")
    assert HostNames(path).all() == {"10.0.0.2": "Server"}
    names.set("10.0.0.2", "")
    assert HostNames(path).all() == {}
    path.write_text("not json")
    assert HostNames(path).all() == {}
