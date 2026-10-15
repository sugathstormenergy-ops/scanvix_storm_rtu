# Storm Energy RTU — Ansible Project

> **Note (Docker migration):** the new Storm Energy RTU deployment on
> **192.168.0.50** uses Docker Compose (repository `README.md`, `.\deploy.ps1`).
> This Ansible project targets the existing server 192.168.0.109 and is kept
> for reference (only this note was added). Do not run it against 192.168.0.50.

Ansible automation for deploying and managing the **Storm Energy RTU platform** on Windows Server `192.168.0.109`.

> **ISOLATION GUARANTEE**: This project is completely independent of the existing PFCMD/Allipuram Ansible project. It does not modify any existing inventory, playbook, service, database, firewall rule, or directory.

---

## Target

| Property | Value |
|---|---|
| Host | `192.168.0.109` |
| Ansible group | `scanvix_rtu` |
| Ansible user | `.\svc_ansible` |
| Connection | WinRM / NTLM |
| Inventory | `inventory/hosts.ini` |

---

## Quick Start

All commands must be run from **`ansible/scanvix_rtu/`**:

```powershell
cd E:\scanvix_RTU\storm-energy-rtu\ansible\scanvix_rtu
```

### 1. Install Ansible collections
```bash
ansible-galaxy collection install -r requirements.yml
```

### 2. Discover the server (read-only — always safe)
```bash
ansible-playbook -i inventory/hosts.ini playbooks/discover.yml
```

### 3. Create secrets file (Vault-encrypted)
```bash
ansible-vault create secrets.yml
```
Contents:
```yaml
scanvix_sql_username: "sa"
scanvix_sql_password: "YOUR_SQL_PASSWORD"
scanvix_mqtt_username: "allipuram_ingest"
scanvix_mqtt_password: "YOUR_MQTT_PASSWORD"
scanvix_api_secret_key: "YOUR_SECRET_KEY_MIN_32_CHARS"
```

### 4. Deploy
```bash
ansible-playbook -i inventory/hosts.ini playbooks/deploy.yml \
  -e @secrets.yml --ask-vault-pass
```

### 5. Verify
```bash
ansible-playbook -i inventory/hosts.ini playbooks/verify.yml
```

### 6. Rollback (Storm resources only)
```bash
ansible-playbook -i inventory/hosts.ini playbooks/rollback.yml
```

---

## Installation Layout

| Path | Purpose |
|---|---|
| `E:\StormEnergyRTU\` | Application root |
| `E:\StormEnergyRTU\app\` | Deployed backend Python code |
| `E:\StormEnergyRTU\logs\` | API, MQTT, TCP log files |
| `E:\StormEnergyRTU\app\.env` | Runtime configuration (Ansible-managed) |
| `E:\StormEnergyRTU.venv\` | Dedicated Python virtual environment |
| `E:\scanvix_RTU\storm-energy-rtu\backend\` | Source directory (never modified) |

---

## Ports

| Service | Port | Notes |
|---|---|---|
| Storm API | **8090** | Must be free — verify with discover.yml |
| MQTT broker | **1883** | May share existing Mosquitto — see MQTT section |
| TCP listener | **9000** | Confirm with Scanvix before deploying |
| Existing infrastructure | **8088** | **NEVER TOUCHED** |

---

## Windows Services

Three dedicated services created with NSSM:

| Service Name | Description | Log |
|---|---|---|
| `StormEnergyRTU-API` | FastAPI HTTP on port 8090 | `logs\api_*.log` |
| `StormEnergyRTU-MQTT` | MQTT telemetry consumer | `logs\mqtt_*.log` |
| `StormEnergyRTU-TCP` | TCP telemetry listener | `logs\tcp_*.log` |

---

## Database

| Property | Value |
|---|---|
| Name | `STORM_ENERGY_RTU` |
| Instance | `localhost` (SQL Server on .109) |
| Scripts | `E:\scanvix_RTU\storm-energy-rtu\database\` |
| Untouched DBs | `WATER_METERS`, `NCC_WATER_METERS`, all PFCMD databases |

The database role checks for an existing `STORM_ENERGY_RTU` before running any SQL scripts. If the database already exists, it is never overwritten.

---

## MQTT Architecture

The MQTT role inspects the server before acting:

- **Mosquitto already installed**: The role halts and prints instructions for resolving the conflict. Set `scanvix_mqtt_skip_install: true` in `group_vars/all.yml` once you have confirmed the Storm MQTT credentials are added to the existing broker's passwd file.
- **Mosquitto not installed**: Installs fresh via `winget`, deploys `mosquitto_storm.conf`, registers as a service.

**Storm MQTT topic hierarchy**: `storm/meters/<IMEI>/telemetry|status|attributes|cmd`

---

## TCP Architecture

TCP listener runs on port `9000` by default (variable: `scanvix_tcp_port`).

> **The TCP frame format and ACK protocol must be confirmed with Scanvix before enabling TCP deployment.** The current platform uses `JsonOverTcpParser` with `NullAckStrategy` (no ACK bytes sent).

---

## Isolation from Allipuram

This project **never** modifies:

- `ansible/` files outside `ansible/scanvix_rtu/`
- The existing `[pfcmd_receiver]` inventory group
- PFCMD/Allipuram Windows services
- Port 8088
- Existing SQL Server databases
- Existing firewall rules
- IIS, scheduled tasks, or any existing infrastructure

---

## Firewall Rules Created

| Rule Name | Port | Protocol |
|---|---|---|
| `StormEnergyRTU-API-8090` | 8090 | TCP inbound |
| `StormEnergyRTU-MQTT` | 1883 | TCP inbound |
| `StormEnergyRTU-TCP` | 9000 | TCP inbound |

---

## Secrets Management

Secrets are **never** stored in source-controlled YAML. Supply them at runtime:

```bash
# Interactive vault password prompt
ansible-playbook ... -e @secrets.yml --ask-vault-pass

# CI/CD — vault password from file
ansible-playbook ... -e @secrets.yml --vault-password-file .vault_pass
```

Required secrets:
- `scanvix_sql_username`
- `scanvix_sql_password`
- `scanvix_mqtt_username`
- `scanvix_mqtt_password`
- `scanvix_api_secret_key`
