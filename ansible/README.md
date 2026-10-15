# ansible/ — preserved Ansible automation

**Docker Compose on 192.168.0.50 is now the preferred deployment method**
(see the repository `README.md`: `.\deploy.ps1`). The Ansible material below is
kept for reference and for the existing environment; it is not used by the
Docker deployment and nothing here was deleted.

| Path | Target | Status |
|---|---|---|
| `ansible/scanvix_rtu/` | Windows Server **192.168.0.109** over WinRM (NSSM services, host Mosquitto, SQL Server `.\SQLEXPRESS`, win-acme) | Preserved. Describes the existing .109 environment, which is **not** part of the Docker deployment and must not be modified from here. |
| `ansible/deploy.yml`, `ansible/roles/*`, `ansible/inventory/hosts.yml`, `ansible/group_vars/*` | Generic **Linux** host (Ubuntu, systemd units, UFW, apt Mosquitto) | Preserved, Linux-specific. Superseded on Windows by Docker Compose. |

Still useful:

* `ansible/scanvix_rtu/roles/database/tasks/main.yml` documents the same
  001 → 004 creation order that `deploy.ps1 -InitDatabase` uses.
* `roles/storm_rtu/templates/storm-rtu-tcp.service.j2` (`python -m app.tcp.server`)
  now works: the TCP listener has a standalone entry point.
* The MQTT ACL / TLS / win-acme work under `scanvix_rtu/roles/mqtt/` is the
  reference for adding per-device ACLs and MQTT TLS to the Docker broker later.

Conflicts to be aware of (do not run against 192.168.0.50):

* The Linux roles install Mosquitto/UFW with systemd and assume Ubuntu.
* `scanvix_rtu` targets `.\SQLEXPRESS` and Windows services on .109 and would
  install a host Mosquitto — on .50 a host Mosquitto (PH Flowmeter) already
  owns port 1883 and must stay untouched.
