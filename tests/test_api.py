"""API tests against a fake broker (no MQTT needed)."""

from collections import deque

import pytest
from fastapi.testclient import TestClient

from app.broker import BrokerUnavailable, DynsecError
from app.config import Settings
from app.main import create_app, merge_clients
from app.tracker import Tracker

CSRF = {"X-Requested-With": "mosquitto-manager"}
NOW = 1_794_739_472.0


class FakeBroker:
    def __init__(self):
        self.connected = True
        self.last_error = None
        self.dynsec_state = "ok"
        self.dynsec_error = None
        self.supports_connections = True
        self.log_feed_seen = True
        self.history = deque()
        self.calls: list[tuple[str, dict]] = []
        self.clients = [
            {"username": "mgr", "roles": [{"rolename": "admin"}], "groups": [], "connections": [{"address": "1.1.1.1"}]},
            {"username": "bob", "textname": "Bob", "roles": [], "groups": [], "connections": [],
             "disabled": True},
        ]
        self.responses: dict[str, dict] = {
            "getClient": {"client": {"username": "mgr", "roles": [{"rolename": "admin"}]}},
            "getGroup": {"group": {"groupname": "g", "clients": [{"username": "mgr"}]}},
            "listRoles": {"roles": [{"rolename": "admin", "acls": []}]},
            "getDefaultACLAccess": {"acls": [{"acltype": "subscribe", "allow": False}]},
        }
        self.fail_with: Exception | None = None

    def start(self, loop): pass
    def stop(self): pass
    def sample_history(self): pass
    async def probe(self): pass

    def snapshot(self):
        return {"version": "2.1.2", "uptime": 5, "has_sys": True, "clients_connected": 1}

    async def list_clients(self):
        return self.clients

    async def dynsec(self, command, timeout=8.0, **params):
        if self.fail_with:
            raise self.fail_with
        self.calls.append((command, params))
        return self.responses.get(command, {})

    async def test_login(self, username, password, clientid=None, timeout=6.0):
        return {"ok": password == "right", "reason": "Success" if password == "right" else "Not authorized", "ms": 1}


@pytest.fixture
def env(tmp_path):
    settings = Settings.from_env({
        "MQTT_HOST": "b", "MQTT_USERNAME": "mgr", "MQTT_PASSWORD": "x",
        "UI_PASSWORD": "password123", "UI_SECRET": "k", "DATA_DIR": str(tmp_path)})
    broker = FakeBroker()
    tracker = Tracker()
    with TestClient(create_app(settings, broker, tracker)) as client:
        yield client, broker, tracker


def login(client):
    assert client.post("/api/login", json={"password": "password123"}).status_code == 200


def test_health_and_session_are_public(env):
    client, *_ = env
    assert client.get("/api/health").json()["status"] == "ok"
    s = client.get("/api/session").json()
    assert s["authenticated"] is False and s["auth_required"] is True


def test_api_requires_login(env):
    client, *_ = env
    for path in ("/api/status", "/api/clients", "/api/roles", "/api/groups", "/api/events"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/clients/delete", json={"username": "bob"}, headers=CSRF).status_code == 401


def test_wrong_password_and_throttle(env):
    client, *_ = env
    for _ in range(5):
        assert client.post("/api/login", json={"password": "nope"}).status_code == 401
    r = client.post("/api/login", json={"password": "password123"})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_session_cookie_flags(env):
    client, *_ = env
    r = client.post("/api/login", json={"password": "password123"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/session").json()["authenticated"] is True


def test_post_requires_csrf_header(env):
    client, broker, _ = env
    login(client)
    assert client.post("/api/clients/delete", json={"username": "bob"}).status_code == 403
    assert not broker.calls
    assert client.post("/api/clients/delete", json={"username": "bob"}, headers=CSRF).status_code == 200
    assert broker.calls[-1] == ("deleteClient", {"username": "bob"})


def test_logout_clears_session(env):
    client, *_ = env
    login(client)
    client.post("/api/logout", headers=CSRF)
    assert client.get("/api/clients").status_code == 401


def test_security_headers(env):
    client, *_ = env
    r = client.get("/api/health")
    assert "frame-ancestors 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
    assert client.get("/").status_code == 200


def test_clients_listing_is_normalised(env):
    client, *_ = env
    login(client)
    data = client.get("/api/clients").json()
    by = {c["username"]: c for c in data["clients"]}
    assert by["mgr"]["online"] and by["mgr"]["is_manager"]
    assert by["bob"]["disabled"] and not by["bob"]["online"]
    assert by["bob"]["textname"] == "Bob" and by["bob"]["clientid"] == ""


def test_manager_account_is_protected(env):
    client, broker, _ = env
    login(client)
    for path, body in [
        ("/api/clients/delete", {"username": "mgr"}),
        ("/api/clients/enable", {"username": "mgr", "enabled": False}),
        ("/api/clients/password", {"username": "mgr", "password": "x"}),
        ("/api/clients/role-remove", {"username": "mgr", "rolename": "admin"}),
        ("/api/clients/update", {"username": "mgr", "clientid": "fixed"}),
        ("/api/roles/delete", {"rolename": "admin"}),
        ("/api/roles/acl-remove", {"rolename": "admin", "acltype": "subscribePattern", "topic": "#"}),
        ("/api/groups/delete", {"groupname": "g"}),
    ]:
        r = client.post(path, json=body, headers=CSRF)
        assert r.status_code == 409, path
    assert not [c for c in broker.calls if c[0].startswith(("delete", "disable", "set", "remove", "modify"))]


def test_other_accounts_can_be_changed(env):
    client, broker, _ = env
    login(client)
    assert client.post("/api/clients/enable", json={"username": "bob", "enabled": False},
                       headers=CSRF).status_code == 200
    assert client.post("/api/clients/enable", json={"username": "bob", "enabled": True},
                       headers=CSRF).status_code == 200
    assert [c[0] for c in broker.calls][-2:] == ["disableClient", "enableClient"]


def test_create_client_builds_dynsec_command(env):
    client, broker, _ = env
    login(client)
    r = client.post("/api/clients/create", headers=CSRF, json={
        "username": "esp", "password": "pw", "textname": "ESP", "roles": ["sensor"], "groups": ["g1"]})
    assert r.status_code == 200
    cmd, params = broker.calls[-1]
    assert cmd == "createClient"
    assert params["roles"] == [{"rolename": "sensor"}] and params["groups"] == [{"groupname": "g1"}]
    assert "clientid" not in params and "textdescription" not in params


@pytest.mark.parametrize("body", [
    {"username": "", "password": "x"},
    {"username": "a\nb", "password": "x"},
    {"username": "ok", "password": ""},
    {"username": "x" * 300, "password": "x"},
])
def test_create_client_validation(env, body):
    client, broker, _ = env
    login(client)
    assert client.post("/api/clients/create", json=body, headers=CSRF).status_code == 422
    assert not broker.calls


def test_acl_preset_adds_four_rules_and_tolerates_duplicates(env):
    client, broker, _ = env
    login(client)
    r = client.post("/api/roles/acl-add", headers=CSRF,
                    json={"rolename": "r", "topic": "a/#", "preset": "readwrite"})
    assert r.json()["added"] == 4
    assert {c[1]["acltype"] for c in broker.calls} == {
        "publishClientSend", "publishClientReceive", "subscribePattern", "unsubscribePattern"}

    async def dup(command, timeout=8.0, **params):
        raise DynsecError("ACL already exists")
    broker.dynsec = dup
    r = client.post("/api/roles/acl-add", headers=CSRF,
                    json={"rolename": "r", "topic": "a/#", "preset": "read"})
    assert r.status_code == 200 and r.json()["added"] == 0
    r = client.post("/api/roles/acl-add", headers=CSRF,
                    json={"rolename": "r", "topic": "a/#", "acltype": "publishClientSend"})
    assert r.status_code == 400 and "already" in r.json()["detail"]


def test_acl_add_needs_type_or_preset(env):
    client, *_ = env
    login(client)
    r = client.post("/api/roles/acl-add", headers=CSRF, json={"rolename": "r", "topic": "t"})
    assert r.status_code == 422


def test_errors_are_mapped(env):
    client, broker, _ = env
    login(client)
    broker.fail_with = DynsecError("Client already exists")
    r = client.post("/api/clients/create", json={"username": "a", "password": "b"}, headers=CSRF)
    assert r.status_code == 400 and r.json()["detail"] == "Client already exists"
    broker.fail_with = BrokerUnavailable("down")
    assert client.get("/api/roles").status_code == 503


def test_test_login(env):
    client, broker, _ = env
    login(client)
    ok = client.post("/api/test-login", json={"username": "bob", "password": "right"}, headers=CSRF).json()
    bad = client.post("/api/test-login", json={"username": "bob", "password": "wrong"}, headers=CSRF).json()
    assert ok["ok"] and not bad["ok"]
    broker.connected = False
    assert client.post("/api/test-login", json={"username": "bob", "password": "x"},
                       headers=CSRF).status_code == 503


def test_default_acl_roundtrip(env):
    client, broker, _ = env
    login(client)
    assert client.get("/api/default-acl").json() == {"acls": {"subscribe": False}}
    assert client.post("/api/default-acl", json={"acls": {"subscribe": True}}, headers=CSRF).status_code == 200
    assert broker.calls[-1] == ("setDefaultACLAccess", {"acls": [{"acltype": "subscribe", "allow": True}]})
    assert client.post("/api/default-acl", json={"acls": {"bogus": True}}, headers=CSRF).status_code == 422


def test_status_and_events(env):
    client, _, tracker = env
    login(client)
    tracker.ingest_log("N", f"{int(NOW)}: Client x [9.9.9.9:1] disconnected: not authorised.", now=NOW)
    s = client.get("/api/status").json()
    assert s["broker"]["connected"] and s["broker"]["version"] == "2.1.2"
    assert s["log_feed"] is True
    ev = client.get("/api/events?kind=auth_failed").json()["events"]
    assert len(ev) == 1 and ev[0]["address"] == "9.9.9.9"


def test_merge_clients_without_connections_field_uses_log_sessions():
    t = Tracker()
    t.ingest_log("N", f"{int(NOW)}: New client connected from 10.0.0.2:5 as dev (p4, c1, k60, u'bob').", now=NOW)
    out = merge_clients([{"username": "bob"}, {"username": "amy"}], t, "mgr")
    assert out[0]["online"] and out[0]["connections"][0]["clientid"] == "dev"
    assert not out[1]["online"]


def test_merge_clients_dynsec_connections_are_authoritative():
    t = Tracker()
    t.ingest_log("N", f"{int(NOW)}: New client connected from 10.0.0.2:5 as dev (p4, c1, k60, u'bob').", now=NOW)
    out = merge_clients([{"username": "bob", "connections": [{"address": "10.0.0.2"}, {"address": "10.0.0.9"}]}],
                        t, "mgr")
    conns = out[0]["connections"]
    assert conns[0]["clientid"] == "dev" and conns[1] == {"address": "10.0.0.9"}
    # dynsec says nobody is connected, even though the log still has a stale session
    assert merge_clients([{"username": "bob", "connections": []}], t, "mgr")[0]["online"] is False


def test_map_endpoint_and_host_alias(env):
    client, broker, tracker = env
    login(client)
    tracker.ingest_log("N", f"{int(NOW)}: New client connected from 1.1.1.1:5 as mgr-c (p4, c1, k60, u'mgr').", now=NOW)
    data = client.get("/api/map").json()
    assert data["broker"]["version"] == "2.1.2" and data["broker"]["connected"]
    assert data["hosts"][0]["address"] == "1.1.1.1"
    assert data["hosts"][0]["clients"][0]["is_manager"] is True
    assert [o["username"] for o in data["offline"]] == ["bob"]
    r = client.post("/api/hosts/alias", json={"address": "1.1.1.1", "name": "Server"}, headers=CSRF)
    assert r.status_code == 200
    assert client.get("/api/map").json()["hosts"][0]["label"] == "Server"
    client.post("/api/hosts/alias", json={"address": "1.1.1.1", "name": ""}, headers=CSRF)
    assert client.get("/api/map").json()["hosts"][0]["alias"] is None
    bad = client.post("/api/hosts/alias", json={"address": "", "name": "x"}, headers=CSRF)
    assert bad.status_code == 422
    assert client.post("/api/hosts/alias", json={"address": "1.1.1.1", "name": "x"}).status_code == 403


def test_status_reports_home_assistant_off_by_default(env):
    client, *_ = env
    login(client)
    ha = client.get("/api/status").json()["ha"]
    assert ha["enabled"] is False and ha["state"] == "off" and ha["entities"] == 0


def test_connections_without_address_are_saved_sessions_not_live():
    t = Tracker()
    mixed = merge_clients([{"username": "u", "roles": [], "groups": [],
                            "connections": [{}, {}, {"address": "1.1.1.1"}]}], t, "mgr")[0]
    assert mixed["online"] and len(mixed["connections"]) == 1 and mixed["saved_sessions"] == 2
    idle = merge_clients([{"username": "u", "roles": [], "groups": [], "connections": [{}, {}]}], t, "mgr")[0]
    assert idle["online"] is False and idle["connections"] == [] and idle["saved_sessions"] == 2
    log_based = merge_clients([{"username": "u", "roles": [], "groups": []}], t, "mgr")[0]
    assert log_based["saved_sessions"] == 0
