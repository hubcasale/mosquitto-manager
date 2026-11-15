# Moving from `password_file` to Dynamic Security

Mosquitto Manager manages users through the Dynamic Security plugin. If your broker currently uses a
`password_file` (and maybe an `acl_file`), this is how to switch **without changing any device**.

> **Needs Mosquitto 2.1 or newer** to keep existing passwords. This was verified on 2.1.2: the
> `$7$…` hashes in a password file are accepted unchanged by Dynamic Security. On 2.0.x the hash
> formats differ; create the users again from the UI and set new passwords on the devices.

## What to know first

1. **Once the plugin is loaded, a user must exist in Dynamic Security to get any access**, even if the
   login would have succeeded through `password_file`. (Tested: a user present only in the password file
   authenticates but its subscriptions are refused.) So the switch is an *import*, not a coexistence.
2. The import gives users **no roles** and sets the **default access to "allow"**. That reproduces what you
   have today when no `acl_file` is configured: everybody can do everything. You then tighten things
   gradually from the UI (roles, then "default access" back to deny).
3. If you use an `acl_file`, its rules are **not** imported. Keep default access on "allow" until you
   have re-created the rules as roles, or the devices lose access they have now.
4. The broker needs **one restart** (a few seconds). Devices reconnect on their own.

## Steps

**0. Back up** the broker's config folder (`mosquitto.conf`, the password file, the persistence data).

**1. Generate the Dynamic Security config** from your password file:

```bash
python3 tools/passwd_to_dynsec.py \
  --passwd /path/to/your/passwd \
  --out /path/to/dynamic-security.json \
  --admin mm-admin
```

It prints how many users were carried over, and the generated password of the manager's account
(shown once: it goes in `MQTT_PASSWORD`). Users whose entry is not a `$7$` hash (plain text or old
`$6$` hashes) are listed as *not carried over*: create them in the UI afterwards.

**2. Edit `mosquitto.conf`**: add the plugin and the log feed
(see [mosquitto.conf.example](mosquitto.conf.example)) and remove `password_file`
(and `acl_file`, once its rules have been re-created as roles):

```conf
plugin /usr/lib/mosquitto_dynamic_security.so
plugin_opt_config_file /mosquitto/data/dynamic-security.json
log_dest topic
```

**3. Restart Mosquitto.** Check in its log that `Plugin dynamic-security loaded` appears and that your
devices reconnect.

**4. Start Mosquitto Manager** with `MQTT_USERNAME=mm-admin` and the generated password.
Open the UI: your users are listed, and the ones connected are shown as online.

**5. Tighten, at your pace.** Create roles with the topics each device really needs, give them to the
users, and finally switch *Roles → Default access* to deny. The activity log and *Failed logins* page tell
you what breaks if you go too fast; the *Test connection* page checks a username and password.

## Rolling back

Restore the old `mosquitto.conf` (with `password_file`) and restart. The password file was never modified.
