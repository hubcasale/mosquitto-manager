import base64
import hashlib
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "passwd_to_dynsec", Path(__file__).parent.parent / "tools" / "passwd_to_dynsec.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def verify(password: str, encoded: str) -> bool:
    _, _, iters, salt, digest = encoded.split("$")
    got = hashlib.pbkdf2_hmac("sha512", password.encode(), base64.b64decode(salt), int(iters))
    return base64.b64encode(got).decode() == digest


def test_make_hash_matches_mosquitto_format():
    h = tool.make_hash("secret")
    assert h.startswith("$7$1000$") and h.count("$") == 4
    assert verify("secret", h) and not verify("other", h)
    assert tool.make_hash("secret") != h  # random salt


def test_read_passwd_skips_unsupported_and_comments(tmp_path):
    f = tmp_path / "passwd"
    f.write_text("a:$7$1000$c2FsdA==$aGFzaA==\n# note\n\nb:plaintext\nc:$6$salt$hash\n")
    users, skipped = tool.read_passwd(str(f))
    assert list(users) == ["a"] and skipped == ["b", "c"]


def test_build_document_shape():
    doc = tool.build({"a": "$7$1000$x$y"}, "mm", "pw", default_allow=True)
    assert doc["defaultACLAccess"] == {k: True for k in (
        "publishClientSend", "publishClientReceive", "subscribe", "unsubscribe")}
    names = [c["username"] for c in doc["clients"]]
    assert names == ["mm", "a"]
    assert doc["clients"][0]["roles"] == [{"rolename": "admin"}]
    assert doc["clients"][1]["encoded_password"] == "$7$1000$x$y"
    assert not any(a["topic"] == "#" for a in doc["roles"][0]["acls"])  # least privilege


def test_cli_refuses_to_overwrite_and_backs_up_with_force(tmp_path, capsys):
    passwd = tmp_path / "passwd"
    passwd.write_text("a:$7$1000$c2FsdA==$aGFzaA==\n")
    out = tmp_path / "dynamic-security.json"
    assert tool.main(["--passwd", str(passwd), "--out", str(out), "--admin-password", "x"]) == 0
    assert json.loads(out.read_text())["clients"][1]["username"] == "a"
    assert oct(out.stat().st_mode & 0o777) == "0o600"
    assert tool.main(["--passwd", str(passwd), "--out", str(out)]) == 1
    assert tool.main(["--passwd", str(passwd), "--out", str(out), "--force",
                      "--admin-password", "x"]) == 0
    assert len(list(tmp_path.glob("*.bak"))) == 1


def test_cli_rejects_admin_name_clash(tmp_path):
    passwd = tmp_path / "passwd"
    passwd.write_text("mm-admin:$7$1000$c2FsdA==$aGFzaA==\n")
    assert tool.main(["--passwd", str(passwd), "--out", str(tmp_path / "o.json")]) == 1


def test_fresh_config_without_passwd_denies_by_default(tmp_path):
    out = tmp_path / "d.json"
    assert tool.main(["--out", str(out), "--admin-password", "x"]) == 0
    doc = json.loads(out.read_text())
    assert [c["username"] for c in doc["clients"]] == ["mm-admin"]
    assert doc["defaultACLAccess"]["subscribe"] is False
    assert tool.main(["--out", str(tmp_path / "e.json"), "--admin-password", "x",
                      "--default-acl", "allow"]) == 0
    assert json.loads((tmp_path / "e.json").read_text())["defaultACLAccess"]["subscribe"] is True


ACL = """# header comment
topic read $SYS/#
topic write casa/watchdog

user mqtt_user
topic readwrite #

user frigate
topic readwrite frigate/#

user reader
topic read #
topic read $SYS/#
topic deny secret/#

user old
topic plain/topic
pattern readwrite clients/%c/#
"""


def test_parse_acl_sections_and_warnings(tmp_path):
    f = tmp_path / "acl.conf"
    f.write_text(ACL)
    anon, per_user, warnings = tool.parse_acl(str(f))
    assert anon == [("read", "$SYS/#"), ("write", "casa/watchdog")]
    assert per_user["mqtt_user"] == [("readwrite", "#")]  # '#' is a topic, not a comment
    assert per_user["reader"] == [("read", "#"), ("read", "$SYS/#"), ("deny", "secret/#")]
    assert per_user["old"] == [("readwrite", "plain/topic")]  # no keyword = readwrite
    assert len(warnings) == 1 and "pattern" in warnings[0]


def test_rules_to_acls_mapping():
    read = tool.rules_to_acls([("read", "a/#")])
    assert {a["acltype"] for a in read} == {"publishClientReceive", "subscribePattern",
                                            "unsubscribePattern"}
    write = tool.rules_to_acls([("write", "a")])
    assert [a["acltype"] for a in write] == ["publishClientSend"]
    both = tool.rules_to_acls([("readwrite", "a"), ("readwrite", "a"), ("write", "a")])
    assert len(both) == 4  # duplicates collapsed
    deny = tool.rules_to_acls([("deny", "s/#")])
    assert deny and all(not a["allow"] and a["priority"] > 0 for a in deny)


def test_build_with_acl_creates_roles_anonymous_group_and_denies_by_default():
    doc = tool.build({"frigate": "$7$1000$x$y", "stray": "$7$1000$x$z"}, "mm", "pw",
                     default_allow=False, anonymous=[("read", "$SYS/#")],
                     user_rules={"frigate": [("readwrite", "frigate/#")], "admin": [("read", "x")]})
    by_name = {c["username"]: c for c in doc["clients"]}
    assert by_name["frigate"]["roles"] == [{"rolename": "frigate"}]
    assert "roles" not in by_name["stray"]  # no ACL rules -> no role -> no access
    role_names = {r["rolename"] for r in doc["roles"]}
    assert {"admin", "frigate", "admin-role", "anonymous"} <= role_names  # no clash with admin
    assert doc["anonymousGroup"] == "anonymous"
    assert doc["groups"][0]["roles"] == [{"rolename": "anonymous"}]
    assert doc["defaultACLAccess"] == {"publishClientSend": False, "publishClientReceive": False,
                                       "subscribe": False, "unsubscribe": True}


def test_cli_with_acl_denies_by_default(tmp_path, capsys):
    acl = tmp_path / "acl.conf"
    acl.write_text(ACL)
    passwd = tmp_path / "passwd"
    passwd.write_text("frigate:$7$1000$c2FsdA==$aGFzaA==\nstray:$7$1000$c2FsdA==$aGFzaA==\n")
    out = tmp_path / "d.json"
    assert tool.main(["--passwd", str(passwd), "--acl", str(acl), "--out", str(out),
                      "--admin-password", "x"]) == 0
    text = capsys.readouterr().out
    assert "stray" in text and "no access" in text and "WARNING" in text
    assert "roles created but no account" in text and "mqtt_user" in text
    # like acl_file: subscribing is open, delivery is filtered by the roles
    assert json.loads(out.read_text())["defaultACLAccess"]["subscribe"] is True
    strict = tmp_path / "s.json"
    assert tool.main(["--passwd", str(passwd), "--acl", str(acl), "--out", str(strict),
                      "--admin-password", "x", "--strict-subscribe"]) == 0
    assert json.loads(strict.read_text())["defaultACLAccess"]["subscribe"] is False
