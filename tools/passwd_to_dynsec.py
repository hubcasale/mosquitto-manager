#!/usr/bin/env python3
"""Build a Mosquitto Dynamic Security config from an existing password_file.

Why: switching a broker from ``password_file`` to the Dynamic Security plugin
normally means re-creating every user, with new passwords, and reconfiguring
every device. With Mosquitto >= 2.1 the password hashes are compatible, so the
existing users and passwords can be carried over unchanged.

The script only needs the Python standard library. It never touches a running
broker: it writes a JSON file that you point the plugin at.

    python3 passwd_to_dynsec.py --passwd /path/to/passwd \
        --out /path/to/dynamic-security.json --admin mm-admin

Without --passwd it creates a fresh config containing only the manager account.

See docs/MIGRATION.md for the full procedure.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import secrets
import shutil
import sys
import time

ITERATIONS = 1000  # what mosquitto_passwd 2.1 uses for $7$ hashes


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


def admin_role() -> dict:
    """Least-privilege role for Mosquitto Manager (Dynamic Security + $SYS only)."""
    ctrl = "$CONTROL/dynamic-security/#"
    return {
        "rolename": "admin",
        "textname": "Mosquitto Manager",
        "acls": [
            {"acltype": "publishClientSend", "topic": ctrl, "allow": True},
            {"acltype": "publishClientReceive", "topic": ctrl, "allow": True},
            {"acltype": "subscribePattern", "topic": ctrl, "allow": True},
            {"acltype": "publishClientReceive", "topic": "$SYS/#", "allow": True},
            {"acltype": "subscribePattern", "topic": "$SYS/#", "allow": True},
        ],
    }


def build(users: dict[str, str], admin: str, admin_password: str, default_allow: bool) -> dict:
    clients = [{"username": admin, "textname": "Mosquitto Manager",
                "encoded_password": make_hash(admin_password), "roles": [{"rolename": "admin"}]}]
    clients += [{"username": u, "encoded_password": h} for u, h in sorted(users.items())
                if u != admin]
    return {
        "defaultACLAccess": {
            "publishClientSend": default_allow, "publishClientReceive": default_allow,
            "subscribe": default_allow, "unsubscribe": default_allow,
        },
        "clients": clients,
        "groups": [],
        "roles": [admin_role()],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--passwd", help="existing password_file to carry over "
                                    "(omit to create a fresh config with only the manager account)")
    p.add_argument("--out", required=True, help="dynamic-security.json to write")
    p.add_argument("--admin", default="mm-admin", help="account for Mosquitto Manager")
    p.add_argument("--admin-password", help="its password (generated if omitted)")
    p.add_argument("--default-acl", choices=["allow", "deny"],
                   help="access for users with no role. Default: allow when importing a "
                        "password_file (no restrictions yet, like a broker without ACLs; "
                        "tighten it later from the UI), deny for a fresh config")
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
    default_acl = args.default_acl or ("allow" if args.passwd else "deny")
    if args.admin in users:
        print(f"'{args.admin}' already exists in the password file; pick another --admin name.",
              file=sys.stderr)
        return 1

    admin_pw = args.admin_password or secrets.token_urlsafe(18)
    doc = build(users, args.admin, admin_pw, default_acl == "allow")

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
    print(f"  manager account: {args.admin}")
    if not args.admin_password:
        print(f"  manager password (shown once, put it in MQTT_PASSWORD): {admin_pw}")
    print(f"  default access for users without a role: {default_acl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
