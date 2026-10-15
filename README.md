Application was developed using the :"STORM_RTU_Production_TCP_Protocol_v1.0" requirement doc 

# Storm Energy RTU Platform

RTU communication platform for Storm Energy. Connects Scanvix RTU hardware via
MQTT and raw TCP, stores telemetry in Microsoft SQL Server, exposes a REST
API for device management, and serves a read-only monitoring web UI
(`frontend/`, see [frontend/README.md](frontend/README.md)).

> **Deployment target:** Windows server **192.168.0.50** with Docker Desktop (Docker Compose).
>
> **192.168.0.109 is an existing server and is NOT part of this Docker deployment.**
> Nothing in the Docker deployment connects to, reads from or modifies .109.
>
> The existing PH Flowmeter stack on .50 (IIS :80, PH display :8089,
> PH-Flowmeter-API :8090, host Mosquitto :1883, SQL Server, database `Storm`)
> is independent and is never stopped, reconfigured or modified by these scripts.

**Status:** Phase B (Docker infrastructure) and Phase A (SQL Server TCP on
127.0.0.1 only, Mixed Mode, `STORM_ENERGY_RTU` + `storm_rtu_app`) are complete. The
read-only web UI (`storm-frontend`) is served through the reverse proxy. The API has
**no authentication yet**: keep it on the internal network (no router/NAT exposure).

---

## 1. Prerequisites

| Item | Requirement |
|---|---|
| OS | Windows 10/11 or Windows Server with PowerShell 5.1+ |
| Docker | Docker Desktop, **Linux containers** mode, Compose v2 (`docker compose`) |
| Git | Git for Windows |
| SQL Server | Existing instance on the same host (default instance), `sqlcmd` on PATH |
| Network | Outbound HTTPS to Docker Hub, PyPI and packages.microsoft.com (image build) |
| Rights | Your Windows login must be able to run Docker; for Phase A it must be a SQL `sysadmin` |

Windows PowerShell may block unsigned scripts. Either run each script with
`powershell -ExecutionPolicy Bypass -File .\deploy.ps1`, or allow local scripts
for your user once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## 2. Clone the repository

```powershell
cd E:\scanvix_Rtu
git clone https://github.com/sugathstormenergy-ops/scanvix_storm_rtu.git
cd scanvix_storm_rtu
```

## 3. Create `.env`

`deploy.ps1` creates `.env` from `.env.example` on first run and replaces every
`__GENERATE__` placeholder (`API_SECRET_KEY`, `SQL_PASSWORD`, `MQTT_PASSWORD`)
with a random secret. You can also create it yourself first:

```powershell
Copy-Item .env.example .env
notepad .env      # adjust ports / STORM_HOST_IP if needed
```

`.env` holds deployment-specific values and secrets. It is git-ignored and
must **never** be committed. Secrets must be alphanumeric (no `$`, quotes,
spaces, `;` or braces). Back it up securely (`backup.ps1 -IncludeSecrets`).

## 4. Deploy

```powershell
.\deploy.ps1
```

The script runs 17 steps: Windows / Docker / Compose / daemon checks, required
files, `.env`, host-port conflict detection, a **read-only** SQL Server
assessment, optional database initialisation, TLS certificate, image build,
`docker compose up -d`, healthcheck wait and functional tests, then prints the
final status. Everything is logged to `.local\logs\deploy-<timestamp>.log`.

| Exit code | Meaning |
|---|---|
| `0` | Infrastructure **and** database healthy |
| `2` | Infrastructure healthy, **database unavailable** (expected until Phase A) |
| `1` | Failure — see the log. Nothing outside the `storm-rtu` project was changed |

If a required host port is already in use, the script **stops and reports the
owner**; it never stops or reconfigures another service.

Options: `-InitDatabase` (Phase A only), `-MigrateDatabase` (apply pending additive
migrations to an existing `STORM_ENERGY_RTU`, see section 12), `-SkipBuild`, `-NoCache`.

## 5. Check status

```powershell
.\status.ps1          # containers, host port listeners, API /health summary
.\health-check.ps1    # full functional test (exit 0 / 2 / 1 as above)
docker compose ps
```

`health-check.ps1` verifies real behaviour, not just "container running":
API liveness and `/health`, authenticated MQTT publish/subscribe, rejection of
anonymous MQTT clients, RTU TCP port, nginx HTTP and HTTPS routing, the served
TLS certificate (and, when `TLS_SERVER_NAME` is set, a fully verified HTTPS
request for that hostname — trusted chain + name, no `-k`), that the API is **not** reachable from the LAN, and —
reported separately as `DATABASE` — API→SQL Server and container→`host.docker.internal:1433`.

## 6. Logs

All containers log to stdout; Docker keeps at most 5 × 10 MB per container
(`json-file` rotation), so no log files grow on the host.

```powershell
docker compose logs -f storm-api
docker compose logs -f storm-tcp
docker compose logs -f mosquitto
docker compose logs -f storm-frontend
docker compose logs -f reverse-proxy
docker compose logs --since 1h --tail 200 storm-api
```

Script logs (deploy / update / health / backup / stop) are written to
`.local\logs\` (git-ignored).

## 7. Update

```powershell
.\update.ps1
```

Refuses to run if tracked files have local changes, then `git pull --ff-only`,
rebuilds, `docker compose up -d` and runs the health checks (via `deploy.ps1`).
Volumes are never removed. Options: `-NoPull`, `-AllowDirty`, `-NoCache`.

Stop / start:

```powershell
.\stop.ps1            # docker compose stop  (containers + volumes kept)
.\stop.ps1 -Down      # docker compose down  (containers removed, volumes KEPT)
.\deploy.ps1          # start again
```

> Never run `docker compose down -v` — it deletes the MQTT broker volume.

## 8. Backup

```powershell
.\backup.ps1                  # database + MQTT volume + config (no secrets)
.\backup.ps1 -IncludeSecrets  # also .env - protect the folder
```

Creates `backups\<timestamp>\` (git-ignored). Nothing is deleted or overwritten.

* `STORM_ENERGY_RTU.bak` — `BACKUP DATABASE … WITH COPY_ONLY, CHECKSUM`, written by
  SQL Server to its default backup directory and copied into the backup folder.
  Skipped while the database does not exist. The `Storm` database is never backed up or touched.
* `mosquitto-data.tgz` — snapshot of volume `storm-rtu-mosquitto-data`.
* `config\` — `compose.yml`, `docker\`, the public certificate file (+ `.env` with `-IncludeSecrets`).
  The TLS **private key is never copied**; it stays only in `TLS_CERT_DIR` (e.g. `E:\certs`).

## 9. Restore

Restore is deliberately manual (it overwrites data):

```powershell
# MQTT broker volume
.\stop.ps1
docker run --rm -v storm-rtu-mosquitto-data:/data -v "E:\path\to\backups\<ts>:/backup:ro" alpine:3.20 `
    sh -c "cd /data && tar xzf /backup/mosquitto-data.tgz"
.\deploy.ps1 -SkipBuild

# Configuration / secrets
Copy-Item backups\<ts>\config\env.backup .env      # only if taken with -IncludeSecrets
```

Database: restore `STORM_ENERGY_RTU.bak` with SQL Server Management Studio or
`RESTORE DATABASE [STORM_ENERGY_RTU] FROM DISK = N'…' WITH …` **only after
confirming with the database owner**. Never restore over the `Storm` database.

## 10. Troubleshooting

| Symptom | Cause / action |
|---|---|
| `DATABASE : UNAVAILABLE`, `/health` → `database: down` | Expected until Phase A. Check `deploy.ps1` step 8 output for the exact blocker. |
| `Port conflict … already used by …` | Another program owns the port. Nothing was changed. Pick another port in `.env` or free it yourself. |
| `Docker is in 'windows' mode` | Docker Desktop → *Switch to Linux containers*. |
| `entrypoint.sh has CRLF line endings` | `git add --renormalize .` then `git checkout -- docker/` (see `.gitattributes`). |
| Browser warns about the certificate | Use `https://mqtt.stormenergy.in` (the certificate has no IP SAN, so `https://192.168.0.50` always warns), or the bootstrap certificate is in use (`TLS_CERT_DIR=./certs`). See section 11. |
| `TLS certificate validation failed` | `deploy.ps1` step 10 lists the reason (SAN/hostname, expiry, chain, key match). Nothing was started with the bad certificate. |
| MQTT `not authorised` | Use `MQTT_USERNAME` / `MQTT_PASSWORD` from `.env`; anonymous access is disabled. The Docker broker is on **1884**, the host broker on 1883 is a different broker. |
| Container restarting | `docker compose logs --tail 100 <service>` |
| API → SQL error `Login failed` (Phase A) | Login/password in `.env` vs. SQL Server; Mixed Mode enabled? |
| API → SQL TCP timeout (Phase A) | SQL Server TCP/IP not enabled / not listening on 1433. |
| Build fails fetching packages | The host needs outbound HTTPS to Docker Hub, PyPI and packages.microsoft.com. |

## 11. Port architecture

```
LAN 192.168.0.0/24 ──► 192.168.0.50 (Windows, Docker Desktop)
                         │
   :443  HTTPS ─────────►├─ reverse-proxy (nginx, non-root) ─┬─► storm-api:8000       /api/*, /health*, /docs, /redoc, /openapi.json
   :8080 HTTP  ─────────►│                                   └─► storm-frontend:8080  everything else (web UI, SPA routes)
                         ├─ storm-frontend  static web UI (nginx, non-root; no host port)
   127.0.0.1:8000 ──────►├─ storm-api   FastAPI + MQTT consumer   (loopback only, NOT on the LAN)
   :8100 RTU TCP ───────►├─ storm-tcp   RTU TCP listener (python -m app.tcp.server)
   :1884 MQTT ──────────►├─ mosquitto   container port 1883, auth required
                         │
                         └─ SQL Server (host)  ◄── host.docker.internal:1433  (Phase A)
```

| Service | Host port | Container port | Exposure |
|---|---|---|---|
| reverse-proxy HTTPS | 443 | 8443 | LAN |
| reverse-proxy HTTP | 8080 | 8080 | LAN (internal validation) |
| storm-api | 127.0.0.1:8000 | 8000 | host loopback only |
| storm-frontend | — | 8080 | Docker network only (via reverse-proxy) |
| storm-tcp | 8100 | 8100 | LAN (RTUs) |
| mosquitto | 1884 | 1883 | LAN (RTUs / clients) |
| SQL Server (host) | 1433 | — | not exposed by Docker |

**Ports owned by existing services on .50 and never used by Docker:** 80 (IIS),
1883 (host Mosquitto), 8089 (PH display), 8090 (PH-Flowmeter-API), 1433/1434
(SQL Server), 3389 (RDP). All host ports are configurable in `.env`.

> **Firewall:** Windows Firewall is currently **disabled** on all profiles of
> 192.168.0.50, so 443, 8080, 1884 and 8100 are reachable from the whole LAN.
> The deployment does not change firewall settings. Before Internet exposure,
> enable the firewall and allow only the required ports (a separate, approved change).

**TLS.** nginx uses the existing Let's Encrypt certificate for
`mqtt.stormenergy.in` from **`E:\certs`**, bind-mounted **read-only** — nothing
is copied into the repository or the image, and `E:\certs` is never modified.

```ini
# .env on 192.168.0.50
TLS_CERT_DIR=E:/certs
TLS_CERT_FILE=mqtt.stormenergy.in-chain.pem   # leaf + intermediates (YR1, Root YR)
TLS_KEY_FILE=mqtt.stormenergy.in-key.pem
TLS_SERVER_NAME=mqtt.stormenergy.in
```

Before (re)starting nginx, `deploy.ps1` validates the files in a throwaway
container with the folder mounted read-only (`scripts\deploy\tls-check.sh`):
hostname vs SAN, expiry (warns < 14 days), chain to a trusted root, and that the
private key matches the certificate. Any failure stops the deployment.

* The certificate's SAN is `DNS:mqtt.stormenergy.in` only — use that name
  (internally via DNS/hosts entry pointing to 192.168.0.50). `https://192.168.0.50` works
  but browsers show a name mismatch.
* Let's Encrypt certificates are valid for 90 days (current one: until 2026-12-16).
  After the renewal tool writes new files into `E:\certs`, run
  `docker compose restart reverse-proxy` (or `.\deploy.ps1 -SkipBuild`, which re-validates).
* Fallback for testing: `TLS_CERT_DIR=./certs` with no files → `deploy.ps1` creates a
  clearly labelled **BOOTSTRAP / TEST** self-signed pair in the git-ignored `certs\` folder.
  Bootstrap generation never happens in an external folder.

## 12. Database architecture

* SQL Server stays on the Windows host (default instance `MSSQLSERVER`); it is **not** containerised.
* Application database: **`STORM_ENERGY_RTU`** (8 tables). The existing **`Storm`** database is a
  different database and is never touched.
* Schema scripts (run in order, all create-only / `IF NOT EXISTS`):
  `database\001_database.sql` (create DB, enable READ_COMMITTED_SNAPSHOT) →
  `002_tables.sql` → `003_indexes.sql` → `004_constraints.sql`.
* `deploy.ps1 -InitDatabase` runs 001→004 (and the migrations below) **only if `STORM_ENERGY_RTU`
  does not exist**. If it exists, nothing is run against it (no 001, no ALTER/DROP/DELETE/TRUNCATE).
* **Migrations** for an existing database (additive, idempotent, `STORM_ENERGY_RTU` only):
  `database\005_device_metadata.sql` adds nullable `Devices.Name NVARCHAR(100)`,
  `Latitude DECIMAL(9,6)`, `Longitude DECIMAL(9,6)` plus CHECK constraints (valid range,
  both-or-neither, never 0,0). No data is written; NULL coordinates mean "No location assigned".
  `deploy.ps1` detects a pending migration and **stops before building** until you run
  `.\deploy.ps1 -MigrateDatabase` (runs as your Windows login via `sqlcmd -E`; refuses if the
  database or base schema is missing; re-verifies afterwards). Fresh installs get the same
  columns from `002_tables.sql`.
  `database\006_protocol_diagnostics.sql` creates `dbo.ProtocolDiagnosticLogs` (Protocol Test Log;
  no foreign keys) and grants the app login DELETE on **that table only**, used by the 30-day
  retention task in `storm-api`. `-MigrateDatabase` runs only migrations whose objects are missing.
* **Unknown devices are not auto-registered.** Telemetry from a device ID that is not in `Devices`
  is archived (RawMessages, TCPMessages/MQTTMessages with status `UNKNOWN_DEVICE`) and shown in the
  Protocol Test Log, but no Devices or Telemetry row is created. Register a device with
  `POST /api/devices` to start storing its telemetry.
* Linux containers cannot use Windows Integrated Authentication, so the containers
  use a dedicated SQL login (`SQL_USERNAME`, default `storm_rtu_app`) with only
  `SELECT, INSERT, UPDATE` on `STORM_ENERGY_RTU.dbo`
  (`database\security\create_app_login.sql`). The password lives only in `.env`.
* Containers reach SQL Server at `host.docker.internal:1433` (`DOCKER_SQL_SERVER` / `DOCKER_SQL_PORT`).

### Phase A: SQL Server prerequisites (completed on 192.168.0.50; kept for reference / rebuilds)

State before Phase A: authentication mode **Windows only**
(`IsIntegratedSecurityOnly = 1`) and **TCP/IP disabled** (nothing listening on 1433).
Required, performed by an administrator — the deployment scripts never do this:

1. SQL Server Configuration Manager → *SQL Server Network Configuration* → *Protocols for MSSQLSERVER* →
   enable **TCP/IP** on port 1433. Preferably listen on 127.0.0.1 only
   (`Listen All = No`, enable only the 127.0.0.1 IP entry) so SQL Server is not exposed on the LAN;
   verify container reachability afterwards with `.\health-check.ps1`.
2. SSMS → Server Properties → Security → **SQL Server and Windows Authentication mode**.
3. Restart the **MSSQLSERVER** service in the maintenance window (brief interruption for all SQL clients,
   including PH Flowmeter).
4. `.\deploy.ps1 -InitDatabase` → creates `STORM_ENERGY_RTU` (if missing) and the `storm_rtu_app` login.
5. `.\health-check.ps1` → expect exit code `0`.

## 13. Router / NAT (later production exposure — NOT part of this deployment)

Do not change the router until internal validation (including Phase A) is complete.
The intended final exposure is a single rule:

```
Router 192.168.0.1   WAN TCP 443  ──►  192.168.0.50:443  (reverse-proxy)
```

Before creating it: confirm public DNS `mqtt.stormenergy.in` → WAN IP, enable Windows
Firewall with explicit allow rules, and decide separately whether RTUs reach
MQTT (1884) / TCP (8100) over the Internet. Never forward 8000, 8080 or 1433.

---

## Developer reference

### Run locally without Docker

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env    # edit SQL/MQTT settings
python -m app.main         # API + MQTT consumer + TCP listener in one process
python -m app.tcp.server   # TCP listener only
```

`ENABLE_MQTT_CONSUMER` / `ENABLE_TCP_SERVER` (default `true`) control which
components run inside the API process; Docker sets `ENABLE_TCP_SERVER=false`
for `storm-api` because `storm-tcp` runs the listener.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Platform health (database / mqtt / tcp) |
| GET | /health/live | Process liveness only (container healthcheck) |
| GET | /health/database, /health/mqtt, /health/tcp | Component status |
| GET | /api/devices | List devices |
| GET | /api/diagnostics/tcp, /api/diagnostics/mqtt | Protocol Test Log (read-only): newest first, `page`, `page_size` (50/100/250), `status`, `device_id`, `imei`, `source_ip`, `topic` |
| GET | /api/diagnostics/{tcp,mqtt}/{id} | One diagnostic record with the complete stored payload |
| GET | /api/diagnostics/server-time | Authoritative server time (IST) |
| GET | /api/devices/latest | Every device (active and inactive) with its latest telemetry (`null` if none) and `server_time`; one SQL statement |
| POST | /api/devices | Register device |
| GET | /api/telemetry/{device_id} | Query telemetry |
| POST | /api/devices/{device_id}/commands | Send command |
| GET | /api/devices/{device_id}/configuration | Get config |
| PUT | /api/devices/{device_id}/configuration | Update config |
| GET | /api/events | List events |

API docs: `http://127.0.0.1:8000/docs` on the host, or `https://<host>/docs` via the reverse proxy.

### MQTT topics

```
storm/meters/<IMEI>/telemetry
storm/meters/<IMEI>/cmd
```

### TCP

Raw TCP on port 8100. Packet format TBD with Scanvix.

### Simulators

```bash
python scripts/mqtt_client.py --device 864012049873321 --site BENCH --count 5
python scripts/tcp_client.py --device 864012049873321
python scripts/mqtt_client.py --device 864012049873321 --historical --count 10
python scripts/mqtt_client.py --device 864012049873321 --invalid
```

### Tests

```bash
pip install -r backend/requirements.txt pyyaml
pytest -c tests/pytest.ini tests
```

### Other deployment methods

Docker Compose on 192.168.0.50 is the **preferred** deployment method. The
Ansible material under `ansible/` is preserved for reference and for the
existing 192.168.0.109 environment — see `ansible/README.md`.

### Documentation

| Document | Description |
|----------|-------------|
| `docs/architecture.md` | System architecture |
| `docs/mqtt-protocol.md` | MQTT topics and payload spec |
| `docs/tcp-protocol.md` | TCP protocol (TBD items noted) |
| `docs/device-management.md` | Device registration and SMS commands |
| `docs/deployment.md` | Deployment guide (Docker first, legacy Ansible) |
| `docs/operations.md` | Monitoring and troubleshooting |

### Technology stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy, paho-mqtt
- **Database**: Microsoft SQL Server (`STORM_ENERGY_RTU`)
- **MQTT**: Eclipse Mosquitto 2.0 (Docker)
- **TCP**: asyncio raw TCP server
- **Reverse proxy**: nginx (unprivileged)
- **Deployment**: Docker Compose on Windows (preferred); Ansible (legacy, preserved)
- **Testing**: pytest

### Open items

- [ ] Phase A: SQL Server TCP/IP + Mixed Mode + `storm_rtu_app` login + `STORM_ENERGY_RTU` initialisation
- [x] Production TLS certificate for the reverse proxy (`E:\certs`, read-only mount)
- [ ] Certificate renewal hook: restart `reverse-proxy` after `E:\certs` is renewed
- [ ] Windows Firewall policy for 443 / 8080 / 1884 / 8100 (currently firewall disabled)
- [ ] Per-device MQTT credentials / ACLs on the Docker broker
- [ ] MQTT over TLS (8883) on the Docker broker
- [ ] Scanvix hardware integration, TCP frame format and ACK format
