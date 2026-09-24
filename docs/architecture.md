# Storm Energy RTU Platform — Architecture

## Overview

One unified codebase serving Development → Scanvix Integration → Commissioning → Production.

```
                         RTU DEVICES (Scanvix)
                               |
               +---------------+---------------+
               |                               |
            MQTT/TLS (1883/8883)          Raw TCP (8100)
               |                               |
               v                               v
        +--------------+               +--------------+
        | Mosquitto    |               | Python TCP   |
        | MQTT Broker  |               | Listener     |
        +------+-------+               +------+-------+
               |                              |
               v                              v
        +--------------+               +--------------+
        | MQTT Consumer|               | TCP Parser   |
        +------+-------+               +------+-------+
               |                              |
               +---------------+--------------+
                               |
                               v NormalizedTelemetry
                   +------------------------+
                   | Storm RTU Application  |
                   | TelemetryService       |
                   | DeviceService          |
                   | CommandService         |
                   | EventService           |
                   +-----------+------------+
                               |
                               v
                     +-------------------+
                     |   MS SQL Server   |
                     | STORM_ENERGY_RTU  |
                     +-------------------+
                               |
                               v
                        +-------------+
                        |  FastAPI    |
                        | REST API    |
                        | Port 8000   |
                        +-------------+
```

## Design Principles

- **Single codebase** — no test/prod split. Configuration drives behaviour.
- **Transport separation** — MQTT and TCP are independent transports sharing one telemetry pipeline.
- **Protocol neutrality** — `NormalizedTelemetry` is the integration seam. Parsers produce it; services consume it.
- **Container-ready** — no Docker today; the layering permits it without logic changes.
- **Deduplication** — QoS 1 MQTT re-deliveries and TCP retransmissions are suppressed by `(DeviceId, Timestamp, Protocol)` unique constraint.
- **Store-and-forward** — RTU timestamps older than `HISTORICAL_THRESHOLD_SECONDS` are flagged `IsHistorical=true`.

## Services

| Service | Role | Port |
|---------|------|------|
| `storm-rtu-api` | FastAPI REST + MQTT consumer + TCP server | 8000 |
| Mosquitto | MQTT broker | 1883 / 8883 |
| SQL Server | Persistence | 1433 |

## Security

- MQTT credentials via Mosquitto password file (Ansible-managed)
- MQTT TLS via Mosquitto listener on 8883
- API secret key via Ansible Vault
- SQL Server credentials via Ansible Vault
- UFW firewall managed by Ansible
- No certificates or passwords in source control
