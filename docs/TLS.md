# Encrypted MQTT (TLS on port 8883)

Plain MQTT on port 1883 sends usernames, passwords and messages in the clear. This guide adds a TLS listener
to Mosquitto using a Let's Encrypt certificate (for example the one Nginx Proxy Manager already renews for you),
keeps the certificate fresh without restarting the broker, and moves clients over one at a time.

Everything below was checked on Mosquitto 2.1.2.

## 1. A name and a certificate

A TLS client checks that the certificate is valid **for the name it connects to**, so clients must use a
hostname (not the IP address). Pick one that resolves to your broker on the LAN, for example
`mqtt.example.com`, and make sure you have a certificate that covers it (a wildcard `*.example.com` works).
With NPM: *SSL Certificates → Add* with a DNS challenge.

## 2. Put the certificate where the broker can read it

Mosquitto starts as root but **drops privileges afterwards**, and it re-reads the certificate files when it
receives `SIGHUP`. If the files are not owned by the broker's user (`1883` in the official image), the reload
fails and the TLS listener **loses its certificate**: every new TLS connection is refused until it is fixed
(plain listeners keep working). `tools/deploy-mosquitto-cert.sh` takes care of this:

```bash
# first time only: copy the files, do not touch the broker yet
sudo ./deploy-mosquitto-cert.sh --install-only \
  --src /path/to/letsencrypt/live/npm-1 \
  --dest /path/to/mosquitto/certs
```

## 3. Add the listener

In `mosquitto.conf` (certificate options belong to the listener they follow):

```conf
listener 8883
listener_allow_anonymous false
certfile /mosquitto/certs/fullchain.pem
keyfile /mosquitto/certs/privkey.pem
```

In the container definition, mount the folder and publish the port:

```yaml
    volumes:
      - /path/to/mosquitto/certs:/mosquitto/certs
    ports:
      - 1883:1883
      - 8883:8883
```

Recreating the broker container restarts only the broker: services that merely `depends_on` it (Zigbee2MQTT,
the manager...) are left running and reconnect on their own. Check:

```bash
openssl s_client -connect mqtt.example.com:8883 -servername mqtt.example.com </dev/null 2>/dev/null | openssl x509 -noout -subject -dates
```

## 4. Keep it renewed

Run the script as root from cron. It does nothing when the certificate has not changed, and when it has:

1. checks that the certificate and key belong together and are not expired,
2. installs them owned by the broker's user,
3. signals the broker and **checks that it now presents the new certificate**; if not, it puts the previous
   files back and reloads again (and exits with an error).

```cron
17 4 * * * /path/to/deploy-mosquitto-cert.sh --src /path/to/letsencrypt/live/npm-1 --dest /path/to/mosquitto/certs --container mosquitto --server-name mqtt.example.com >> /var/log/mosquitto-cert.log 2>&1
```

## 5. Move the clients

For each client: the **hostname**, port **8883**, TLS on, verification with the system's CA certificates
(Let's Encrypt is trusted everywhere). Leave port 1883 open while you do this.

The manager shows which connections are encrypted: a **plain** badge on the *Users* page, an amber ring on
the *Map*, and a counter on the *Dashboard* ("encrypted connections", with how many are still in the clear).
It learns the broker port of each connection from the broker's log, so it only knows about connections
opened *after the manager started*; a device that was already connected shows up when it reconnects (the
counter says how many it has not seen yet). Ports counted as encrypted are set with `TLS_PORTS` (default `8883`).

For Mosquitto Manager itself:

```yaml
      MQTT_HOST: "mqtt.example.com"
      MQTT_PORT: "8883"
      MQTT_TLS: "true"
```

If the certificate is not accepted the manager now says why on its dashboard (unknown issuer, wrong
hostname, expired...). Use `MQTT_CA_FILE` for a private CA.

Quick test from any machine with the Mosquitto clients installed:

```bash
mosquitto_sub -h mqtt.example.com -p 8883 -u USER -P PASSWORD -t '$SYS/broker/version' -C 1
```

## 6. Close the plain port

When no client connects on 1883 any more, remove the `1883:1883` mapping (or publish it on `127.0.0.1` only).
A listener bound to the loopback, such as a local health-check listener, is unaffected.

## 7. Get warned before it expires

The most common way a TLS setup breaks months later is a certificate that silently stops renewing: the
Cloudflare token behind a DNS challenge is revoked, the certificate is re-created under a new folder name and
the deploy job still points to the old one, and so on. Nothing complains until the day every client refuses the
broker. Mosquitto Manager therefore reads the certificate the broker presents and shows it on the
*Dashboard* (expiry date, days left, issuer, key type, and whether the manager itself trusts it), with a
warning when fewer than `CERT_WARN_DAYS` (default 14) remain, and an error when fewer than 7 remain or it has
expired. *Check now* re-reads it immediately; it is re-read every 6 hours.

It looks at the port the manager connects to when `MQTT_TLS=true`, otherwise at the broker's TLS ports
(`TLS_PORTS`, default `8883`) and stays quiet if there are none. Set `CERT_CHECK=host:port[,host:port]` to look
elsewhere, or `CERT_CHECK=off`.

With `HA_DISCOVERY=true` three sensors follow it: `sensor.mosquitto_cert_days_left`,
`sensor.mosquitto_cert_expires` and `binary_sensor.mosquitto_cert_expiring`, for example:

```yaml
automation:
  - alias: "MQTT - certificato TLS in scadenza"
    triggers:
      - trigger: state
        entity_id: binary_sensor.mosquitto_cert_expiring
        to: "on"
    actions:
      - action: notify.notify
        data:
          title: "Mosquitto"
          message: >
            Il certificato TLS del broker scade tra
            {{ states('sensor.mosquitto_cert_days_left') }} giorni: controlla il rinnovo.
```

