# Storm Energy RTU Platform — Deployment Guide

> **Preferred method: Docker Compose on Windows server 192.168.0.50.**
> See the repository `README.md` (sections 1–13): `.\deploy.ps1`, `.\status.ps1`,
> `.\health-check.ps1`, `.\update.ps1`, `.\stop.ps1`, `.\backup.ps1`.
> 192.168.0.109 is an existing server and is not part of the Docker deployment.
>
> The remainder of this document describes the **legacy Ansible deployment to a
> Linux host** and is kept for reference only (see `ansible/README.md`).

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Ansible | ≥ 2.14 |
| Target OS | Ubuntu 22.04 LTS (recommended) |
| Python | 3.11 (installed by Ansible role) |
| SQL Server | 2017+ (existing or new instance) |

## Initial Setup

### 1. Configure Inventory

Edit `ansible/inventory/hosts.yml`:
```yaml
rtu-server-01:
  ansible_host: <YOUR_SERVER_IP>
```

### 2. Configure Variables

Edit `ansible/group_vars/all.yml`:
- Set `sql_server` to your SQL Server IP/hostname
- Replace all `!!VAULT!!` placeholders with actual values

### 3. Encrypt Sensitive Values with Ansible Vault

```bash
# Encrypt individual values
ansible-vault encrypt_string 'my-secret-key' --name 'api_secret_key'
ansible-vault encrypt_string 'SqlPassword123' --name 'sql_password'
ansible-vault encrypt_string 'MqttPassword123' --name 'mqtt_password'

# Paste the encrypted output into group_vars/all.yml
```

### 4. Create the SQL Server Database

Run the migration scripts against your SQL Server instance:
```bash
sqlcmd -S <SQL_SERVER> -U sa -P <password> -i database/001_database.sql
sqlcmd -S <SQL_SERVER> -U <user> -d STORM_ENERGY_RTU -i database/002_tables.sql
sqlcmd -S <SQL_SERVER> -U <user> -d STORM_ENERGY_RTU -i database/003_indexes.sql
sqlcmd -S <SQL_SERVER> -U <user> -d STORM_ENERGY_RTU -i database/004_constraints.sql
```

### 5. Deploy

```bash
ansible-playbook -i ansible/inventory/hosts.yml ansible/deploy.yml --ask-vault-pass
```

## TLS Certificate Setup (for MQTT over TLS)

Generate or obtain certificates and copy to the server:
```bash
scp ca.crt server.crt server.key storm@<SERVER>:/etc/storm-rtu/certs/
```

Then set `mqtt_tls_enabled: true` in `group_vars/all.yml` and redeploy.

## Verify Deployment

```bash
# Health check
curl http://<SERVER>:8000/health

# API documentation
open http://<SERVER>:8000/docs
```

## Service Management

```bash
# Status
systemctl status storm-rtu-api
systemctl status mosquitto

# Restart
systemctl restart storm-rtu-api

# Logs
journalctl -u storm-rtu-api -f
journalctl -u mosquitto -f
```

## Ports Summary

| Port | Protocol | Service |
|------|----------|---------|
| 22   | TCP | SSH |
| 1883 | TCP | MQTT |
| 8883 | TCP | MQTT TLS |
| 8100 | TCP | RTU TCP listener |
| 8000 | TCP | Storm RTU API |
| 1433 | TCP | SQL Server (internal only) |
