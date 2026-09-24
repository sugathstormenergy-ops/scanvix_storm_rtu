# Storm Energy RTU Platform — Device Management

## Adding a New Device

No code changes required. Use the REST API or SQL insert.

### Via API

```http
POST /api/devices
Content-Type: application/json

{
  "device_id":          "864012049873321",
  "imei":               "864012049873321",
  "site_id":            "BENCH",
  "firmware_version":   "1.0.0",
  "communication_mode": "MQTT"
}
```

### Communication Modes

| Mode | Description |
|------|-------------|
| `MQTT` | Device sends telemetry via MQTT |
| `TCP` | Device connects via raw TCP |
| `BOTH` | Device uses MQTT and TCP (redundant) |

## Auto-Registration

Unknown devices that send valid telemetry are auto-registered with `IsActive=false`.  
An operator must activate them via `PUT /api/devices/{device_id}` (`is_active: true`).  
All telemetry from unknown devices is still stored — no data is discarded.

## Device Identity

Per Scanvix specification: **IMEI is the device identity**.  
`DeviceId` = IMEI (15-digit GSM IMEI, e.g. `864012049873321`).

## Device Configuration

```http
PUT /api/devices/{device_id}/configuration
Content-Type: application/json

{
  "communication_mode": "MQTT",
  "mqtt_broker":        "mqtt.storm.in",
  "mqtt_port":          1883,
  "reporting_interval": 600,
  "apn":                "airteliot.com",
  "slave_id":           1,
  "baud_rate":          9600,
  "range_value":        3200
}
```

## SMS Commands (via RTU — not server-terminated)

These commands are sent TO the RTU via SMS by authorised mobile numbers:

| Command | Description |
|---------|-------------|
| `GETFLOW` | Returns current flow, site, totals, timestamp |
| `GETCONFIG` | Returns SITEID, RANGE, SLAVEID, SERVER, PORT |
| `SETMODE:1` / `SETMODE:2` | Set TCP (1) or MQTT (2) mode |
| `GETMODE` | Returns current mode, server, APN, period |
| `GETDETAILS` | Returns DeviceID, SITEID, IP, signal, etc. |
| `RANGE:xxxx` | Set flow meter range |
| `REBOOT` | Reboot the RTU |
| `SETSERVER` / `SETPORT` / `SETMQTT` | Configure server parameters |

Error responses: `ERROR: Unsupported Command` / `ERROR: Unauthorized`  
SMS PIN suffix: 5-digit code (default `56789`).

The Storm Energy backend exposes a Command API that queues commands for MQTT/TCP delivery. SMS gateway integration is owned by Storm Energy separately.
