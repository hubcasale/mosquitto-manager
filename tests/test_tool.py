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
