# Storm Energy RTU Platform — MQTT Protocol

## Topic Hierarchy

```
storm/meters/<deviceId>/telemetry    ← RTU → Server (telemetry)
storm/meters/<deviceId>/status       ← RTU → Server (status)
storm/meters/<deviceId>/attributes   ← RTU → Server (attributes)
storm/meters/<deviceId>/cmd          ← Server → RTU (commands)
```

Example: `storm/meters/864012049873321/telemetry`

## Telemetry Payload (JSON)

Source: Scanvix RTU MODEM TECH V1.3

```json
{
  "deviceId":       "864012049873321",
  "siteid":         "BENCH",
  "ts":             "2026-09-01 14:30:00",
  "flow":           12.47,
  "flowUnit":       "m3/h",
  "totalToday":     318.6,
  "totalYesterday": 402.1,
  "sensorType":     "rs485",
  "signalDbm":      -71,
  "battery":        null,
  "fwVersion":      "1.0.0",
  "READ01":         null,
  "READ02":         null,
  "READ03":         null,
  "READ04":         null,
  "READ05":         null,
  "PRESSURE":       null
}
```

### Field Notes

| Field | Required | Notes |
|-------|----------|-------|
| `deviceId` | Yes | IMEI (15 digits) |
| `ts` | Yes | `YYYY-MM-DD HH:MM:SS` (RTU local time) |
| `flow` | No | Instantaneous flow rate |
| `battery` | No | Often null per spec — accepted |
| `READ01`–`READ05` | No | Additional Modbus registers — null when unavailable |
| `PRESSURE` | No | 4–20mA input — null when unavailable |

### Timestamp Formats Accepted

- `YYYY-MM-DD HH:MM:SS` (primary — Scanvix V1.3)
- `YYYY-MM-DDTHH:MM:SS` (ISO-8601)
- Unix epoch (seconds or milliseconds)

## QoS

QoS 1 — at-least-once delivery. Deduplication is applied server-side using
`(DeviceId, Timestamp, Protocol)` as the idempotency key.

## TLS

Port 1883 — plain MQTT  
Port 8883 — MQTT over TLS v1.2+  
Certificates managed by Ansible, stored in `/etc/storm-rtu/certs/`.
