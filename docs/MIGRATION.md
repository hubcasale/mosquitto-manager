# Moving from `password_file` + `acl_file` to Dynamic Security

Mosquitto Manager manages users through the Dynamic Security plugin. If your broker currently uses a
`password_file` and an `acl_file`, this is how to switch **without changing any device**.

> **Needs Mosquitto 2.1 or newer** to keep existing passwords. Verified on 2.1.2: the `$7$…` hashes in a
> password file are accepted unchanged by Dynamic Security. On 2.0.x the hash formats differ; create the
> users again from the UI and set new passwords on the devices.

## What the converter does

`tools/passwd_to_dynsec.py` reads your password file and your ACL file and writes a
`dynamic-security.json`:

| From | To |
|---|---|
| each `user:$7$…` line of the password file | a client with the same password |
| `user X` section of the ACL file | a role named `X`, given to client `X` |
| `topic read T` | receive + subscribe + unsubscribe on `T` |
| `topic write T` | publish on `T` |
| `topic readwrite T` (or no keyword) | all of the above |
| `topic deny T` | the same rules with *deny*, at a higher priority |
| rules before the first `user` line (anonymous clients) | role + group `anonymous`, set as the broker's anonymous group |
| *(new)* | the manager's own account `mm-admin` with a least-privilege role |

Not converted: `pattern` rules (with `%u` / `%c`), which Dynamic Security cannot express (the script lists
them), and password entries that are not `$7$` hashes (listed as "not carried over").

### Subscribing: same behaviour as before

With `acl_file`, Mosquitto accepts *any* subscription and filters messages when it delivers them: a client
that subscribes to `#` but may only read `allsky/data` simply receives `allsky/data`. Dynamic Security is
stricter by default: it refuses the subscription itself, so such a client would stop working.

So by default the converter turns on *Allow subscribing* in the default access and relies on the roles'
receive rules to filter, exactly like `acl_file`. Once everything works you can switch it off in
**Roles → Default access** (the roles already contain the subscribe rules), or pass `--strict-subscribe`.

### Verified

Using a copy of a real setup (12 users, anonymous loopback listener, per-listener anonymous settings) on
Mosquitto 2.1.2, an `acl_file` broker and the converted Dynamic Security broker were compared on 548 probes:
logins, anonymous access on both listeners, and, for every user, which of 20 topics it can read and write.
All 548 matched.

## Steps

**0. Back up** the broker's config and data folders.

**1. Generate the Dynamic Security config:**

```bash
python3 tools/passwd_to_dynsec.py \
  --passwd /path/to/mosquitto.passwd \
  --acl /path/to/acl.conf \
  --out /path/to/data/dynamic-security.json \
  --admin mm-admin
```

It prints what it carried over, any warnings, and the generated password of the manager's account
(shown once: it goes in `MQTT_PASSWORD`). Put the file in the broker's **data** folder (the official image
gives that folder to the broker's user when it starts, and the plugin rewrites the file when you make
changes).

**2. Edit `mosquitto.conf`:** load the plugin, add the log feed, and remove `password_file` and `acl_file`.
Per-listener settings such as `listener_allow_anonymous` stay as they are.

```conf
plugin /usr/lib/mosquitto_dynamic_security.so
plugin_opt_config_file /mosquitto/data/dynamic-security.json

log_dest topic            # next to your existing log_dest lines

listener 1883
listener_allow_anonymous false

listener 1884 127.0.0.1   # e.g. a local, anonymous listener for health checks
listener_allow_anonymous true
```

The anonymous rules of the old ACL file now live in the `anonymous` group, so the local listener keeps
working the same way.

**3. Restart Mosquitto** (a few seconds; devices reconnect on their own). Check its log for
`Plugin dynamic-security loaded`.

**4. Start Mosquitto Manager** with `MQTT_USERNAME=mm-admin` and the generated password. Your users are
listed, and the connected ones show as online.

**5. Tighten, at your pace.** Remove old shared accounts, narrow roles, and finally turn off *Allow
subscribing*. The *Failed logins* page shows which device still uses an old account or password.

## Rolling back

Restore the old `mosquitto.conf` (with `password_file` and `acl_file`) and restart. Neither file was
modified.
