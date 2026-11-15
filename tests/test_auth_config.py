import pytest

from app.auth import LoginThrottle, check_password, make_token, verify_token
from app.config import ConfigError, Settings


def test_token_roundtrip_and_tamper():
    tok = make_token("s3cret", 1, now=1000)
    assert verify_token("s3cret", tok, now=1500)
    assert not verify_token("other", tok, now=1500)
    assert not verify_token("s3cret", tok, now=1000 + 3601)  # expired
    payload, _, sig = tok.partition(".")
    assert not verify_token("s3cret", payload + "." + sig[:-2] + "xx", now=1500)
    assert not verify_token("s3cret", None)
    assert not verify_token("s3cret", "garbage")


def test_check_password():
    assert check_password("correct horse", "correct horse")
    assert not check_password("correct horse", "correct")


def test_throttle_blocks_then_expires():
    t = LoginThrottle(limit=3, window=100)
    for _ in range(3):
        assert t.retry_after("a", now=0) == 0
        t.record_failure("a", now=0)
    assert t.retry_after("a", now=10) > 0
    assert t.retry_after("b", now=10) == 0
    assert t.retry_after("a", now=101) == 0
    t.record_failure("a", now=101)
    t.reset("a")
    assert t.retry_after("a", now=102) == 0


BASE = {"MQTT_HOST": "broker", "MQTT_USERNAME": "mgr", "MQTT_PASSWORD": "x",
        "UI_PASSWORD": "longenough", "UI_SECRET": "k"}


def test_settings_ok(tmp_path):
    s = Settings.from_env({**BASE, "DATA_DIR": str(tmp_path)})
    assert s.mqtt_port == 1883 and s.frame_ancestors == "'self'"


@pytest.mark.parametrize("override", [
    {"MQTT_HOST": ""},
    {"MQTT_PASSWORD": ""},
    {"MQTT_PORT": "abc"},
    {"UI_PASSWORD": "short"},
])
def test_settings_rejects_bad_config(tmp_path, override):
    with pytest.raises(ConfigError):
        Settings.from_env({**BASE, "DATA_DIR": str(tmp_path), **override})


def test_auth_can_be_disabled_explicitly(tmp_path):
    env = {**BASE, "DATA_DIR": str(tmp_path), "AUTH_DISABLED": "true", "UI_PASSWORD": ""}
    assert Settings.from_env(env).auth_disabled


def test_secret_is_persisted(tmp_path):
    env = {k: v for k, v in BASE.items() if k != "UI_SECRET"} | {"DATA_DIR": str(tmp_path)}
    a = Settings.from_env(env).secret_key
    b = Settings.from_env(env).secret_key
    assert a == b and len(a) == 64
