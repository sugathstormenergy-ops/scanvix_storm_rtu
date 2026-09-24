"""
Storm Energy RTU Platform — Phase 6 regression tests (ACME / public TLS
certificate preparation).

Covers the Phase 6 source additions:
  - group_vars/all.yml: new scanvix_mqtt_acme_state_dir variable, and the
    win-acme PemFiles-naming clarification comment left the existing
    scanvix_mqtt_tls_certfile/keyfile VALUES unchanged (comment-only +
    one new variable -- no behavioral change to existing vars).
  - roles/directories/tasks/main.yml: new, gated acme-state directory
    creation task, additive only.
  - roles/mqtt/files/win-acme-post-renewal.ps1: exists, is non-empty,
    and is NOT referenced by any playbook/task yet (source-only, no
    scheduled task, no live wiring this phase).
  - Preserves the Phase 5 fix: the 8883 TLS block in mosquitto.conf.j2
    must still unconditionally render acl_file whenever it renders at
    all (this test duplicates that specific check here, independent of
    tests/unit/test_mosquitto_conf_8883_acl.py, so a Phase 6 change that
    accidentally touched mosquitto.conf.j2 would be caught by two
    independent tests rather than relying on only one file).
"""
import os
import re

import pytest

yaml = pytest.importorskip("yaml")
jinja2 = pytest.importorskip("jinja2")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ANSIBLE_ROOT = os.path.join(REPO_ROOT, "ansible", "scanvix_rtu")
GROUP_VARS = os.path.join(ANSIBLE_ROOT, "inventory", "group_vars", "all.yml")
DIRECTORIES_TASKS = os.path.join(ANSIBLE_ROOT, "roles", "directories", "tasks", "main.yml")
MOSQUITTO_CONF_J2 = os.path.join(ANSIBLE_ROOT, "roles", "mqtt", "templates", "mosquitto.conf.j2")
POST_RENEWAL_SCRIPT = os.path.join(ANSIBLE_ROOT, "roles", "mqtt", "files", "win-acme-post-renewal.ps1")


def _ansible_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", "on")
    return bool(v)


def _load_group_vars_text():
    with open(GROUP_VARS) as f:
        return f.read()


class TestGroupVarsAcmeStateDir:

    def test_group_vars_is_still_valid_yaml(self):
        with open(GROUP_VARS) as f:
            docs = list(yaml.safe_load_all(f))
        assert len(docs) == 1
        assert isinstance(docs[0], dict)

    def test_acme_state_dir_variable_present_with_expected_value(self):
        text = _load_group_vars_text()
        assert r"scanvix_mqtt_acme_state_dir: '{{ scanvix_certs_dir }}\acme-state'" in text

    def test_existing_tls_certfile_keyfile_values_unchanged(self):
        # The Phase 6 comment addition must not have altered the actual
        # variable VALUES for certfile/keyfile -- only added an
        # explanatory comment above them plus the new acme_state_dir var.
        text = _load_group_vars_text()
        assert (
            r"scanvix_mqtt_tls_certfile:  '{{ scanvix_certs_dir }}\live\{{ scanvix_mqtt_tls_hostname }}\fullchain.pem'"
            in text
        )
        assert (
            r"scanvix_mqtt_tls_keyfile:   '{{ scanvix_certs_dir }}\live\{{ scanvix_mqtt_tls_hostname }}\privkey.pem'"
            in text
        )

    def test_existing_acl_and_tls_switches_still_default_false(self):
        with open(GROUP_VARS) as f:
            data = yaml.safe_load(f)
        assert data["scanvix_mqtt_tls_enabled"] is False
        assert data["scanvix_mqtt_acl_enabled"] is False


class TestDirectoriesRoleAcmeState:

    def test_directories_tasks_is_still_valid_yaml(self):
        with open(DIRECTORIES_TASKS) as f:
            docs = list(yaml.safe_load_all(f))
        assert len(docs) == 1
        tasks = docs[0]
        names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
        assert any("acme-state" in n for n in names)

    def test_acme_state_task_gated_on_variable_defined(self):
        with open(DIRECTORIES_TASKS) as f:
            data = yaml.safe_load(f)
        acme_tasks = [
            t for t in data
            if isinstance(t, dict) and "acme-state" in t.get("name", "")
        ]
        assert len(acme_tasks) == 1
        task = acme_tasks[0]
        assert task.get("when") == "scanvix_mqtt_acme_state_dir is defined"
        assert task["ansible.windows.win_file"]["state"] == "directory"

    def test_existing_certs_dir_task_unaffected(self):
        with open(DIRECTORIES_TASKS) as f:
            data = yaml.safe_load(f)
        certs_tasks = [
            t for t in data
            if isinstance(t, dict) and t.get("name", "").startswith(
                "DIRECTORIES | Create E:\\StormEnergyRTU\\certs ("
            )
        ]
        assert len(certs_tasks) == 1
        assert certs_tasks[0]["when"] == "scanvix_certs_dir is defined"


class TestWinAcmePostRenewalScriptSourceOnly:

    def test_script_exists_and_is_non_empty(self):
        assert os.path.isfile(POST_RENEWAL_SCRIPT)
        assert os.path.getsize(POST_RENEWAL_SCRIPT) > 0

    def test_script_braces_and_parens_balanced(self):
        # No PowerShell interpreter is available in this environment (or
        # the development sandbox used for Phase 5/6) to run a real
        # parser check -- this is a best-effort static sanity check only,
        # matching the brace-balance technique used elsewhere in this
        # repo's test suite for files that can't be executed directly.
        with open(POST_RENEWAL_SCRIPT) as f:
            src = f.read()
        assert src.count("{") == src.count("}")
        assert src.count("(") == src.count(")")
        assert src.count("[") == src.count("]")

    def test_script_never_deletes_the_previous_certificate(self):
        with open(POST_RENEWAL_SCRIPT) as f:
            src = f.read()
        assert "Remove-Item" not in src, (
            "post-renewal script must never delete the previous certificate; "
            "it must only Move-Item it aside for rollback"
        )

    def test_script_implements_rollback_on_failure(self):
        with open(POST_RENEWAL_SCRIPT) as f:
            src = f.read()
        assert "Restore-PreviousCertificate" in src
        assert src.count("Restore-PreviousCertificate") >= 2  # defined + called at least once

    def test_script_not_referenced_by_any_playbook_or_task(self):
        # Structural inertness: this script must not be copied, templated,
        # or executed by any current task file -- it is Phase 6 design
        # only, requiring explicit future wiring.
        offenders = []
        for root_dir, _dirs, files in os.walk(ANSIBLE_ROOT):
            for fname in files:
                if not fname.endswith(".yml"):
                    continue
                path = os.path.join(root_dir, fname)
                if path in (POST_RENEWAL_SCRIPT, GROUP_VARS):
                    # GROUP_VARS mentions the script's path only inside an
                    # explanatory comment (Phase 6 design note) -- not an
                    # actual Ansible task/module reference. Checked
                    # precisely below instead of a blanket string search.
                    continue
                with open(path, errors="ignore") as f:
                    content = f.read()
                if "win-acme-post-renewal" in content:
                    offenders.append(path)
        assert offenders == [], f"post-renewal script is now referenced by: {offenders}"

    def test_group_vars_mention_is_comment_only(self):
        with open(GROUP_VARS) as f:
            lines = f.readlines()
        for line in lines:
            if "win-acme-post-renewal" in line:
                assert line.strip().startswith("#"), (
                    f"group_vars/all.yml references the script outside a comment: {line!r}"
                )


class TestPhase5AclFixPreservedOn8883:
    """Independent re-check (separate from test_mosquitto_conf_8883_acl.py)
    that Phase 6 did not regress the Phase 5 fix: the 8883 TLS block must
    still unconditionally carry acl_file whenever it renders."""

    def _render(self, **overrides):
        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        env.filters["bool"] = _ansible_bool
        with open(MOSQUITTO_CONF_J2) as f:
            tmpl = env.from_string(f.read())
        ctx = dict(
            scanvix_mqtt_port=1883,
            scanvix_mqtt_passwd_file=r"C:\ProgramData\StormEnergyRTU\Mosquitto\storm_passwd",
            scanvix_mqtt_passwd_dir=r"C:\ProgramData\StormEnergyRTU\Mosquitto",
            scanvix_mqtt_bench_enabled=False,
            scanvix_mqtt_bench_port=1885,
            scanvix_mqtt_bench_host="192.168.0.109",
            scanvix_mqtt_bench_passwd_file=r"C:\ProgramData\StormEnergyRTU\Mosquitto\bench_passwd",
            scanvix_mqtt_tls_enabled=False,
            scanvix_mqtt_tls_hostname="mqtt.stormenergy.in",
            scanvix_mqtt_tls_port=8883,
            scanvix_mqtt_tls_certfile=r"E:\StormEnergyRTU\certs\live\mqtt.stormenergy.in\fullchain.pem",
            scanvix_mqtt_tls_keyfile=r"E:\StormEnergyRTU\certs\live\mqtt.stormenergy.in\privkey.pem",
            scanvix_mqtt_tls_version="tlsv1.2",
            scanvix_mqtt_acl_enabled=False,
            scanvix_mqtt_acl_file=r"C:\ProgramData\StormEnergyRTU\Mosquitto\storm_acl",
        )
        ctx.update(overrides)
        return tmpl.render(**ctx)

    def test_8883_still_forces_acl_file_when_tls_on_and_acl_master_switch_off(self):
        out = self._render(scanvix_mqtt_tls_enabled=True, scanvix_mqtt_acl_enabled=False)
        lines = [l for l in out.splitlines() if l.strip().startswith("acl_file ")]
        assert len(lines) == 1
        assert out.index("listener 8883") < out.index(lines[0])

    def test_todays_live_vars_still_render_with_no_acl_file_at_all(self):
        out = self._render(scanvix_mqtt_bench_enabled=True)
        assert not any(l.strip().startswith("acl_file ") for l in out.splitlines())
        assert "listener 8883" not in out
