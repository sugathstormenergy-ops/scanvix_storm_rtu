# Storm Energy RTU Platform

Production-ready RTU communication platform for Storm Energy.
Connects Scanvix RTU hardware via MQTT and raw TCP, persists telemetry
to Microsoft SQL Server, and exposes a REST API for device management.

## Quick Start

```bash
# 1. Create and activate a virtual environment
cd backend
python3 -m venv venv && source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp ../.env.example .env
# Edit .env with your SQL Server, MQTT broker, and API settings

# 4. Create the database (once)
sqlcmd -S <SQL_SERVER> -U <user> -P <pass> -i ../database/001_database.sql
sqlcmd -S <SQL_SERVER> -U <user> -d STORM_ENERGY_RTU -i ../database/002_tables.sql
sqlcmd -S <SQL_SERVER> -U <user> -d STORM_ENERGY_RTU -i ../database/003_indexes.sql
sqlcmd -S <SQL_SERVER> -U <user> -d STORM_ENERGY_RTU -i ../database/004_constraints.sql

# 5. Start the platform
python -m app.main
# or: uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API Documentation

Once running: http://localhost:8000/docs

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Platform health |
| GET | /api/devices | List devices |
| POST | /api/devices | Register device |
| GET | /api/telemetry/{device_id} | Query telemetry |
| POST | /api/devices/{device_id}/commands | Send command |
| GET | /api/devices/{device_id}/configuration | Get config |
| PUT | /api/devices/{device_id}/configuration | Update config |
| GET | /api/events | List events |

## MQTT Topic

```
storm/meters/<IMEI>/telemetry
storm/meters/<IMEI>/cmd
```

## TCP

Raw TCP on port 8100. Packet format TBD with Scanvix.

## Simulators

```bash
# Send MQTT telemetry
python scripts/mqtt_client.py --device 864012049873321 --site BENCH --count 5

# Send TCP telemetry
python scripts/tcp_client.py --device 864012049873321

# Send historical batch
python scripts/mqtt_client.py --device 864012049873321 --historical --count 10

# Send invalid payload (tests error handling)
python scripts/mqtt_client.py --device 864012049873321 --invalid
```

## Run Tests

```bash
cd storm-energy-rtu
pip install pytest pytest-asyncio
pytest tests/ -v
```

## Production Deployment

```bash
# Deploy with Ansible
ansible-playbook -i ansible/inventory/hosts.yml ansible/deploy.yml --ask-vault-pass
```

See `docs/deployment.md` for full instructions.

## Documentation

| Document | Description |
|----------|-------------|
| `docs/architecture.md` | System architecture |
| `docs/mqtt-protocol.md` | MQTT topics and payload spec |
| `docs/tcp-protocol.md` | TCP protocol (TBD items noted) |
| `docs/device-management.md` | Device registration and SMS commands |
| `docs/deployment.md` | Ansible deployment guide |
| `docs/operations.md` | Monitoring and troubleshooting |

## Technology Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy, paho-mqtt
- **Database**: Microsoft SQL Server (STORM_ENERGY_RTU)
- **MQTT**: Mosquitto
- **TCP**: asyncio raw TCP server
- **Deployment**: Ansible
- **Testing**: pytest

## Definition of Done (Production Checklist)

- [x] One unified codebase
- [x] FastAPI REST API
- [x] MS SQL Server schema (8 tables, indexes, constraints)
- [x] MQTT consumer (QoS 1, deduplication, reconnect)
- [x] MQTT over TLS (configurable)
- [x] Raw TCP listener (asyncio)
- [x] TCP ACK abstraction (TBD with Scanvix — NullAck active)
- [x] Device management (register without code changes)
- [x] Telemetry ingestion (MQTT + TCP → shared pipeline)
- [x] Raw message storage (every packet archived)
- [x] Deduplication (idempotent writes)
- [x] Historical telemetry (store-and-forward)
- [x] Device status tracking
- [x] Command architecture (MQTT/TCP/SMS stubs)
- [x] RS485/Modbus support (server-side representation)
- [x] 4–20mA support (READ01–READ05, PRESSURE fields)
- [x] Health monitoring (/health + sub-endpoints)
- [x] Structured logging (no credentials logged)
- [x] Automated tests (unit + protocol)
- [x] RTU simulators (MQTT + TCP)
- [x] Ansible deployment (4 roles)
- [x] Secret management (Ansible Vault)
- [x] Firewall configuration (UFW role)
- [x] Documentation (6 docs)
- [ ] Scanvix hardware integration (Phase 5 — requires live RTU)
- [ ] MQTT TLS certificates (operational — not source-controlled)
- [ ] TCP frame format finalised with Scanvix
- [ ] TCP ACK format agreed with Scanvix
