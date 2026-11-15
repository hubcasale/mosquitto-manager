#!/usr/bin/env python3
"""Build a Mosquitto Dynamic Security config from an existing password_file / acl_file.

Why: switching a broker from ``password_file`` + ``acl_file`` to the Dynamic
Security plugin normally means re-creating every user, with new passwords, and
reconfiguring every device. With Mosquitto >= 2.1 the password hashes are
compatible, so existing users keep their passwords, and the ACL file is turned
into one role per user.

The script only needs the Python standard library. It never touches a running
broker: it writes a JSON file that you point the plugin at.

    python3 passwd_to_dynsec.py --passwd /path/to/passwd --acl /path/to/acl.conf \
        --out /path/to/dynamic-security.json --admin mm-admin

Without --passwd it creates a fresh config containing only the manager account.
See docs/MIGRATION.md for the full procedure.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import sys
import time

ITERATIONS = 1000  # what mosquitto_passwd 2.1 uses for $7$ hashes
ADMIN_ROLE = "admin"
ANON_NAME = "anonymous"
DENY_PRIORITY = 10  # explicit denies must win over allows (priority 0)

READ_TYPES = ["publishClientReceive", "subscribePattern", "unsubscribePattern"]
WRITE_TYPES = ["publishClientSend"]


def make_hash(password: str) -> str:
    """Create a ``$7$`` (PBKDF2-SHA512) hash in mosquitto_passwd's format."""
    salt = os.urandom(12)
    digest = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, ITERATIONS)
    return "$7${}${}${}".format(
        ITERATIONS, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def read_passwd(path: str) -> tuple[dict[str, str], list[str]]:
    """Return ({user: hash}, [users skipped because of an unsupported hash])."""
    users: dict[str, str] = {}
    skipped: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            user, _, hashed = line.partition(":")
            if hashed.startswith("$7$"):
                users[user] = hashed
            else:
                skipped.append(user)  # plaintext or old $6$ hash: cannot be carried over
    return users, skipped


# ------------------------------------------------------------------- ACL file
Rule = tuple[str, str]  # (access, topic) with access in read|write|readwrite|deny


def parse_acl(path: str) -> tuple[list[Rule], dict[str, list[Rule]], list[str]]:
    """Parse a mosquitto acl_file.

    Returns (rules for anonymous clients, {user: rules}, warnings). Rules that
    appear before the first ``user`` line apply to anonymous clients.
    """
    anonymous: list[Rule] = []
    per_user: dict[str, list[Rule]] = {}
    warnings: list[str] = []
    current: list[Rule] = anonymous
    with open(path, encoding="utf-8") as fh:
        for number, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            keyword, _, rest = line.partition(" ")
            rest = rest.strip()
            if keyword == "user":
                current = per_user.setdefault(rest, [])
            elif keyword == "topic":
                access, _, topic = rest.partition(" ")
                if access in ("read", "write", "readwrite", "deny") and topic.strip():
                    current.append((access, topic.strip()))
                else:
                    current.append(("readwrite", rest))  # no keyword means read+write
            elif keyword == "pattern":
                warnings.append(f"line {number}: 'pattern' rules ({rest}) use %u/%c "
                                "substitution, which Dynamic Security cannot express; "
                                "re-create them as one rule per user")
            else:
                warnings.append(f"line {number}: ignored '{line}'")
    return anonymous, per_user, warnings


def rules_to_acls(rules: list[Rule]) -> list[dict]:
    acls: list[dict] = []
    seen: set[tuple[str, str, bool]] = set()
    for access, topic in rules:
        if access == "read":
            types = READ_TYPES
        elif access == "write":
            types = WRITE_TYPES
        else:  # readwrite and deny cover both directions
            types = READ_TYPES + WRITE_TYPES
        allow = access != "deny"
        for acltype in types:
            key = (acltype, topic, allow)
            if key in seen:
                continue
            seen.add(key)
            acls.append({"acltype": acltype, "topic": topic, "allow": allow,
                         "priority": 0 if allow else DENY_PRIORITY})
    return acls


# --------------------------------------------------------------- document
def admin_role() -> dict:
    """Least-privilege role for Mosquitto Manager (Dynamic Security + $SYS only)."""
    ctrl = "$CONTROL/dynamic-security/#"
    return {
        "rolename": ADMIN_ROLE,
        "textname": "Mosquitto Manager",
        "acls": [
            {"acltype": "publishClientSend", "topic": ctrl, "allow": True},
            {"acltype": "publishClientReceive", "topic": ctrl, "allow": True},
            {"acltype": "subscribePattern", "topic": ctrl, "allow": True},
            {"acltype": "publishClientReceive", "topic": "$SYS/#", "allow": True},
            {"acltype": "subscribePattern", "topic": "$SYS/#", "allow": True},
        ],
    }


def build(users: dict[str, str], admin: str, admin_password: str, default_allow: bool,
          anonymous: list[Rule] | None = None,
          user_rules: dict[str, list[Rule]] | None = None,
          loose_subscribe: bool = False) -> dict:
    roles = [admin_role()]
    role_of: dict[str, str] = {}
    for user, rules in sorted((user_rules or {}).items()):
        if not rules:
            continue
        name = user if user != ADMIN_ROLE else f"{user}-role"
        role_of[user] = name
        roles.append({"rolename": name, "textname": f"Rules of {user}",
                      "acls": rules_to_acls(rules)})

    clients = [{"username": admin, "textname": "Mosquitto Manager",
                "encoded_password": make_hash(admin_password),
                "roles": [{"rolename": ADMIN_ROLE}]}]
    for user, hashed in sorted(users.items()):
        if user == admin:
            continue
        client: dict = {"username": user, "encoded_password": hashed}
        if user in role_of:
            client["roles"] = [{"rolename": role_of[user]}]
        clients.append(client)

    doc: dict = {
        "defaultACLAccess": {
            "publishClientSend": default_allow, "publishClientReceive": default_allow,
            # loose_subscribe mimics acl_file: any subscription is accepted and messages are
            # filtered when delivered (the roles' receive rules decide what arrives).
            "subscribe": default_allow or loose_subscribe, "unsubscribe": True,
        },
        "clients": clients,
        "groups": [],
        "roles": roles,
    }
    if anonymous:
        roles.append({"rolename": ANON_NAME, "textname": "Anonymous clients",
                      "acls": rules_to_acls(anonymous)})
        doc["groups"].append({"groupname": ANON_NAME, "textname": "Anonymous clients",
                              "roles": [{"rolename": ANON_NAME}], "clients": []})
        doc["anonymousGroup"] = ANON_NAME
    return doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--passwd", help="existing password_file to carry over "
                                    "(omit to create a fresh config with only the manager account)")
    p.add_argument("--acl", help="existing acl_file to convert into roles")
    p.add_argument("--out", required=True, help="dynamic-security.json to write")
    p.add_argument("--admin", default="mm-admin", help="account for Mosquitto Manager")
    p.add_argument("--admin-password", help="its password (generated if omitted)")
    p.add_argument("--default-acl", choices=["allow", "deny"],
                   help="access for users with no matching role. Default: deny when an ACL "
                        "file is given or for a fresh config; allow when only a password_file "
                        "is imported (no restrictions yet, like a broker without ACLs)")
    p.add_argument("--strict-subscribe", action="store_true",
                   help="with --acl: refuse subscriptions that no role allows. By default "
                        "subscriptions are accepted and filtered on delivery, exactly like "
                        "acl_file does, so clients that subscribe more widely than they may "
                        "read keep working")
    p.add_argument("--force", action="store_true", help="overwrite --out (a .bak is kept)")
    args = p.parse_args(argv)

    if os.path.exists(args.out) and not args.force:
        print(f"{args.out} already exists; use --force to replace it (a backup is kept).",
              file=sys.stderr)
        return 1

    users: dict[str, str] = {}
    skipped: list[str] = []
    if args.passwd:
        try:
            users, skipped = read_passwd(args.passwd)
        except OSError as exc:
            print(f"Cannot read {args.passwd}: {exc}", file=sys.stderr)
            return 1
    anonymous: list[Rule] = []
    user_rules: dict[str, list[Rule]] = {}
    warnings: list[str] = []
    if args.acl:
        try:
            anonymous, user_rules, warnings = parse_acl(args.acl)
        except OSError as exc:
            print(f"Cannot read {args.acl}: {exc}", file=sys.stderr)
            return 1
    if args.admin in users:
        print(f"'{args.admin}' already exists in the password file; pick another --admin name.",
              file=sys.stderr)
        return 1

    default_acl = args.default_acl or ("allow" if args.passwd and not args.acl else "deny")
    admin_pw = args.admin_password or secrets.token_urlsafe(18)
    loose = bool(args.acl) and not args.strict_subscribe
    doc = build(users, args.admin, admin_pw, default_acl == "allow", anonymous, user_rules,
                loose_subscribe=loose)

    if os.path.exists(args.out):
        backup = f"{args.out}.{int(time.time())}.bak"
        shutil.copy2(args.out, backup)
        print(f"Backup of the old file: {backup}")
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    os.chmod(args.out, 0o600)

    print(f"Wrote {args.out}")
    print(f"  users carried over with their current password: {len(users)}")
    if skipped:
        print(f"  NOT carried over (unsupported hash format): {', '.join(skipped)}")
        print("  -> create these in Mosquitto Manager and set a new password on the device.")
    if args.acl:
        n_rules = sum(len(r) for r in user_rules.values())
        print(f"  ACL file: {n_rules} rule(s) for {len(user_rules)} user(s) turned into roles"
              + (f", plus {len(anonymous)} rule(s) for anonymous clients" if anonymous else ""))
        no_account = sorted(set(user_rules) - set(users))
        if no_account and args.passwd:
            print(f"  roles created but no account in the password file for: {', '.join(no_account)}")
        no_rules = sorted(set(users) - set(user_rules) - {args.admin})
        if no_rules:
            print(f"  accounts with no ACL rules (they will have no access): {', '.join(no_rules)}")
        for w in warnings:
            print(f"  WARNING {w}")
    if anonymous:
        print("  anonymous clients: rules attached to the 'anonymous' group "
              "(only matters on a listener that allows anonymous access)")
    print(f"  manager account: {args.admin}")
    if not args.admin_password:
        print(f"  manager password (shown once, put it in MQTT_PASSWORD): {admin_pw}")
    print(f"  default access for users without a matching rule: {default_acl}")
    if loose:
        print("  subscriptions: accepted for any topic, delivery limited by each role "
              "(same as acl_file). Switch 'Allow subscribing' off in Roles -> Default access "
              "to make them strict once everything works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
