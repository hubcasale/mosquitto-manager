# Home Assistant sensors

Mosquitto Manager can publish the broker's state to Home Assistant through
[MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery). Turn it on with:

```yaml
HA_DISCOVERY: "true"
```

Home Assistant must already use the same broker through its MQTT integration. Nothing else to configure:
the entities appear by themselves under two devices.

## What you get

**Device "Mosquitto broker"**

| Entity | |
|---|---|
| `sensor.mosquitto_clients_connected` | connections open right now |
| `sensor.mosquitto_users_online` | Dynamic Security users with at least one connection |
| `sensor.mosquitto_users_total` | users known to the broker |
| `sensor.mosquitto_subscriptions` / `_retained` | subscriptions and retained messages |
| `sensor.mosquitto_msg_rate_in` / `_out` | messages per minute (1-minute average) |
| `sensor.mosquitto_failed_logins_24h` / `_10m` | refused logins |
| `sensor.mosquitto_last_failed_login` | when; attributes: `clientid`, `address`, `reason` |
| `binary_sensor.mosquitto_login_attack` | on when failed logins in 10 minutes reach `HA_FAILED_THRESHOLD` (5) |
| `sensor.mosquitto_uptime`, `_version`, `_dropped` | diagnostics |

**Device "MQTT clients"**: one connectivity sensor per user, `binary_sensor.mqtt_client_<user>`
(on = connected). Attributes: `address`, `clientid`, `protocol`, `connected_since`, `connection_count`,
`roles`, `groups`, `last_seen`. Users you add or delete in the manager appear and disappear in Home Assistant
on their own. Turn this part off with `HA_USER_SENSORS=false`.

> Entity ids use the `default_entity_id` option of recent Home Assistant releases. On older versions they
> are derived from the names instead (for example `sensor.mosquitto_broker_clients_connected`).

## What the manager changes on the broker

Publishing needs permissions the manager's account does not have by default. On first start the manager
creates a role **`mosquitto-manager-ha`** and gives it to its own account. The role allows only:

- publish on `homeassistant/+/mosquitto_manager/+/config` (the discovery messages)
- publish on `mosquitto_manager/#` (states and availability)
- receive and subscribe `homeassistant/status` (Home Assistant's "I restarted" message)

You can see and review the role in *Roles*. The very first time, granting it makes the broker drop and
re-open the manager's main connection once (a second).

A second MQTT connection, with a last-will message, is used for publishing, so the entities turn
`unavailable` if the manager stops. A permission problem can never block the manager's main connection.

## Examples

Alert when someone keeps getting the password wrong:

```yaml
automation:
  - alias: "MQTT - attacco al login"
    triggers:
      - trigger: state
        entity_id: binary_sensor.mosquitto_login_attack
        to: "on"
    actions:
      - action: notify.notify
        data:
          title: "Mosquitto"
          message: >
            Login falliti: {{ states('sensor.mosquitto_failed_logins_10m') }} negli ultimi 10 minuti.
            Ultimo: {{ state_attr('sensor.mosquitto_last_failed_login', 'clientid') }}
            da {{ state_attr('sensor.mosquitto_last_failed_login', 'address') }}
```

Alert when a bridge disappears from the broker:

```yaml
  - alias: "MQTT - Zigbee2MQTT scollegato"
    triggers:
      - trigger: state
        entity_id: binary_sensor.mqtt_client_zigbee2mqtt
        to: "off"
        for: "00:03:00"
    actions:
      - action: notify.notify
        data:
          message: "Zigbee2MQTT non è collegato a Mosquitto da 3 minuti."
```

## Limits

- The sensors travel through the broker they describe. If the broker is down, nothing can be published:
  watch Home Assistant's own MQTT integration for that case.
- Turning `HA_DISCOVERY` off leaves the entities in Home Assistant (they become unavailable). Delete the
  two devices there if you no longer want them.
- Mosquitto does not report traffic per client, so there is no per-device message count.
