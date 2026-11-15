import asyncio
import json

import pytest

from app.config import ConfigError, Settings
from app.ha import (BROKER_ENTITIES, HaPublisher, Topics, broker_config, broker_states, slug,
                    user_config, user_key, user_payloads)
from app.tracker import Tracker

NOW = 1_794_739_472.0


def make_settings(tmp_path, **extra):
    env = {"MQTT_HOST": "b", "MQTT_USERNAME": "mgr", "MQTT_PASSWORD": "x", "UI_PASSWORD": "password123",
           "UI_SECRET": "k", "DATA_DIR": str(tmp_path), "HA_DISCOVERY": "true", **extra}
    return Settings.from_env(env)


class FakeBroker:
    connected = True

    def __init__(self):
        self.on_event = None
        self.clients = [
            {"username": "mgr", "roles": [{"rolename": "admin"}], "groups": [],
             "connections": [{"address": "1.1.1.1"}]},
            {"username": "frigate", "textname": "Frigate", "roles": [{"rolename": "frigate"}],
             "groups": [], "connections": []},
        ]

    def snapshot(self):
        return {"version": "2.1.2", "uptime": 120, "has_sys": True, "clients_connected": 2,
                "subscriptions": 5, "retained": 7, "msg_rate_in": 12.345, "msg_rate_out": 3.0,
                "dropped": 0}

    async def list_clients(self):
        return self.clients


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def pub(tmp_path):
    published: dict[str, tuple[str, bool]] = {}
    log: list[str] = []

    def publish(topic, payload, retain):
        published[topic] = (payload, retain)
        log.append(topic)

    s = make_settings(tmp_path)
    broker = FakeBroker()
    tracker = Tracker()
    p = HaPublisher(s, broker, tracker, publish=publish)
    return p, broker, tracker, published, log


# ------------------------------------------------------------------ helpers
def test_slug_and_user_key():
    assert slug("Frigate NVR!") == "frigate_nvr"
    assert slug("###") == "x"
    assert user_key("frigate") == user_key("frigate") != user_key("Frigate ")
    assert user_key("a/b").startswith("a_b_")  # topic-safe


def test_settings_defaults_and_validation(tmp_path):
    s = make_settings(tmp_path)
    assert (s.ha_prefix, s.ha_node, s.ha_base, s.ha_failed_threshold) == (
        "homeassistant", "mosquitto_manager", "mosquitto_manager", 5)
    assert s.ha_user_sensors is True
    assert not Settings.from_env({"MQTT_HOST": "b", "MQTT_USERNAME": "u", "MQTT_PASSWORD": "p",
                                  "UI_PASSWORD": "password123", "UI_SECRET": "k",
                                  "DATA_DIR": str(tmp_path)}).ha_discovery
    for bad in ({"HA_NODE_ID": "a/b"}, {"HA_BASE_TOPIC": "x y"}, {"HA_DISCOVERY_PREFIX": "#"},
                {"HA_FAILED_THRESHOLD": "many"}):
        with pytest.raises(ConfigError):
            make_settings(tmp_path, **bad)


def test_broker_config_shape(tmp_path):
    s = make_settings(tmp_path)
    t = Topics(s)
    by_key = {e[0]: broker_config(s, t, e, "2.1.2") for e in BROKER_ENTITIES}
    comp, key, cfg = by_key["clients_connected"]
    assert comp == "sensor"
    assert cfg["unique_id"] == "mosquitto_manager_clients_connected"
    assert cfg["default_entity_id"] == "sensor.mosquitto_clients_connected"
    assert cfg["state_topic"] == "mosquitto_manager/state/clients_connected"
    assert cfg["availability_topic"] == "mosquitto_manager/status"
    assert cfg["device"]["identifiers"] == ["mosquitto_manager_broker"]
    assert cfg["device"]["sw_version"] == "2.1.2" and cfg["origin"]["name"] == "Mosquitto Manager"
    attack = by_key["login_attack"][2]
    assert attack["payload_on"] == "ON" and attack["device_class"] == "problem"
    assert by_key["last_failed_login"][2]["json_attributes_topic"].endswith("/last_failed_login/attrs")
    assert len({c[2]["unique_id"] for c in by_key.values()}) == len(BROKER_ENTITIES)


def test_user_config_shape(tmp_path):
    s = make_settings(tmp_path)
    comp, object_id, cfg = user_config(s, Topics(s), "Esp 32")
    assert comp == "binary_sensor" and object_id == f"user_{user_key('Esp 32')}"
    assert cfg["default_entity_id"] == "binary_sensor.mqtt_client_esp_32"
    assert cfg["device_class"] == "connectivity" and cfg["name"] == "Esp 32"
    assert cfg["device"]["via_device"] == "mosquitto_manager_broker"


def test_broker_states_formatting():
    snap = {"clients_connected": 3, "msg_rate_in": 12.345, "msg_rate_out": 3.0, "uptime": 60,
            "version": "2.1.2", "subscriptions": None}
    st = broker_states(snap, users_total=4, users_online=2, failed_24h=9, failed_10m=5, threshold=5,
                       last_failed={"ts": NOW, "clientid": "x", "address": "9.9.9.9", "reason": "r"})
    assert st["msg_rate_in"] == "12.35" and st["msg_rate_out"] == "3"
    assert st["subscriptions"] == "None"  # becomes 'unknown' in Home Assistant
    assert st["login_attack"] == "ON" and st["failed_logins_24h"] == "9"
    assert st["last_failed_login"].endswith("+00:00")
    assert json.loads(st["last_failed_login/attrs"])["address"] == "9.9.9.9"
    quiet = broker_states(snap, users_total=0, users_online=0, failed_24h=0, failed_10m=4,
                          threshold=5, last_failed=None)
    assert quiet["login_attack"] == "OFF" and quiet["last_failed_login"] == "None"


def test_user_payloads():
    online = {"username": "frigate", "textname": "Frigate", "online": True, "disabled": False,
              "connections": [{"address": "1.2.3.4", "clientid": "frigate-main", "protocol": "MQTT 3.1.1",
                               "since": NOW}],
              "roles": [{"rolename": "r"}], "groups": [{"groupname": "g"}], "last_seen": {"ts": NOW}}
    state, attrs = user_payloads(online)
    a = json.loads(attrs)
    assert state == "ON" and a["clientid"] == "frigate-main" and a["roles"] == ["r"] and a["groups"] == ["g"]
    state, attrs = user_payloads({"username": "x", "online": False, "connections": []})
    assert state == "OFF" and json.loads(attrs)["connection_count"] == 0


# ---------------------------------------------------------------- publisher
def test_first_tick_publishes_everything_retained(pub):
    p, broker, tracker, published, _ = pub
    run(p._tick())
    configs = [t for t in published if t.endswith("/config")]
    assert len(configs) == len(BROKER_ENTITIES) + 1  # + frigate; the manager's own account is skipped
    assert all(published[t][1] is True for t in published)  # everything retained
    assert published["mosquitto_manager/state/clients_connected"][0] == "2"
    assert published["mosquitto_manager/state/users_total"][0] == "1"
    assert published[f"mosquitto_manager/user/{user_key('frigate')}/state"][0] == "OFF"
    assert not any("mgr" in t for t in published)


def test_unchanged_values_are_not_republished(pub):
    p, _, _, _, log = pub
    run(p._tick())
    n = len(log)
    run(p._tick())
    assert len(log) == n


def test_user_state_follows_connections_and_failed_logins(pub):
    p, broker, tracker, published, log = pub
    run(p._tick())
    broker.clients[1]["connections"] = [{"address": "10.0.0.2"}]
    p._users_dirty = True
    run(p._tick())
    assert published[f"mosquitto_manager/user/{user_key('frigate')}/state"][0] == "ON"
    import time
    for i in range(5):
        tracker.ingest_log("N", f"{int(time.time())}: Client x{i} [9.9.9.9:1] disconnected: not authorised.")
    run(p._tick())
    assert published["mosquitto_manager/state/failed_logins_10m"][0] == "5"
    assert published["mosquitto_manager/state/login_attack"][0] == "ON"


def test_new_and_deleted_users_create_and_remove_entities(pub):
    p, broker, _, published, _ = pub
    run(p._tick())
    broker.clients.append({"username": "newdev", "roles": [], "groups": [], "connections": []})
    p._users_dirty = True
    run(p._tick())
    new_cfg = f"homeassistant/binary_sensor/mosquitto_manager/user_{user_key('newdev')}/config"
    assert published[new_cfg][0] != ""
    broker.clients = [c for c in broker.clients if c["username"] != "newdev"]
    p._users_dirty = True
    run(p._tick())
    assert published[new_cfg] == ("", True)  # empty retained payload removes the entity
    assert published[f"mosquitto_manager/user/{user_key('newdev')}/state"][0] == ""


def test_birth_message_triggers_full_resend(pub):
    p, _, _, published, log = pub
    run(p._tick())
    published.clear()
    p._need_discovery = True  # what a Home Assistant "online" birth message sets
    run(p._tick())
    assert len([t for t in published if t.endswith("/config")]) == len(BROKER_ENTITIES) + 1


def test_user_sensors_can_be_turned_off(tmp_path):
    published = {}
    s = make_settings(tmp_path, HA_USER_SENSORS="false")
    p = HaPublisher(s, FakeBroker(), Tracker(), publish=lambda t, pl, r: published.__setitem__(t, pl))
    run(p._tick())
    assert not any("/user/" in t or "user_" in t for t in published)
    assert published["mosquitto_manager/state/users_total"] == "1"


def test_events_wake_the_publisher(pub):
    p, _, tracker, _, _ = pub
    p._users_dirty = False
    ev = tracker.ingest_log("N", f"{int(NOW)}: New client connected from 10.0.0.2:1 as c (p4, c1, k60, u'u').", now=NOW)
    p._on_event(ev)
    assert p._users_dirty and p._wake.is_set()
    p._users_dirty = False
    p._wake.clear()
    internal = tracker.ingest_log("N", f"{int(NOW)}: New client connected from 10.0.0.2:2 as mm-test-ab (p4, c1, k60, u'u').", now=NOW)
    p._on_event(internal)
    assert not p._users_dirty and not p._wake.is_set()


def test_provisioning_is_idempotent_and_scoped(tmp_path):
    from app.broker import DynsecError
    calls = []
    holds_role = {"yes": False}

    class B(FakeBroker):
        async def dynsec(self, command, timeout=8.0, **params):
            calls.append((command, params))
            if command == "getClient":
                roles = [{"rolename": "mosquitto-manager-ha"}] if holds_role["yes"] else []
                return {"client": {"username": "mgr", "roles": roles}}
            if command == "createRole" and holds_role["yes"]:
                raise DynsecError("Role already exists")
            if command == "addRoleACL" and holds_role["yes"]:
                raise DynsecError("ACL with this topic already exists")
            if command == "addClientRole" and holds_role["yes"]:
                raise DynsecError("Internal error")  # what Mosquitto really answers on a duplicate
            return {}

    s = make_settings(tmp_path)
    p = HaPublisher(s, B(), Tracker())
    run(p._provision())
    topics = {c[1]["topic"] for c in calls if c[0] == "addRoleACL"}
    assert topics == {"homeassistant/+/mosquitto_manager/+/config", "mosquitto_manager/#",
                      "homeassistant/status"}
    assert ("addClientRole", {"username": "mgr", "rolename": "mosquitto-manager-ha", "priority": 0}) in calls
    holds_role["yes"] = True
    calls.clear()
    run(p._provision())  # second run (manager restarted): duplicates are not errors
    assert p._provisioned
    assert not [c for c in calls if c[0] == "addClientRole"]  # no duplicate assignment attempted
