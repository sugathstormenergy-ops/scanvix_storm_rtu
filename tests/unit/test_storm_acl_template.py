"""
Storm Energy RTU Platform — Jinja-rendering tests for the Phase 4 ACL
template (roles/mqtt/templates/storm_acl.j2).

No local Mosquitto binary is available in this environment (confirmed via
`which mosquitto mosquitto_passwd` returning nothing), so these tests
cannot exercise real broker-side ACL enforcement. They instead verify, at
the template-rendering level, the properties the rendered storm_acl file
must have for the Phase 4 security design to hold:

  - allipuram_ingest keeps its current unrestricted access (readwrite #)
  - each enabled device gets write access to its own telemetry/status/
    attributes and read access to its own cmd topic, and nothing else
  - a device's rendered stanza never contains another device's topic root
    or username (topic-isolation check)
  - a disabled device produces no stanza at all
  - no password-shaped text ever appears (the template only ever receives
    already-derived, password-free device metadata)
  - the ACL file is not wired into any playbook/role yet (structural
    inertness), checked separately via a static grep-based test here so a
    regression that accidentally starts referencing it is caught by CI
    even though it doesn't render templates.

Requires the `jinja2` package (already a transitive Ansible dependency).
"""
import glob
import os
import re
import sys

import pytest

jinja2 = pytest.importorskip("jinja2")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TEMPLATE_PATH = os.path.join(
    REPO_ROOT, "ansible", "scanvix_rtu", "roles", "mqtt", "templates", "storm_acl.j2"
)


def _ansible_bool(v):
    if isinstance(v, bool):  # noqa: keep bool spelled out in full here
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", "on")
    return bool(v)


def _render(devices=None, **overrides):
    env = jinja2.Environment(undefined=jinja2.Undefined)
    env.filters["bool"] = _ansible_bool
    with open(TEMPLATE_PATH) as f:
        tmpl = env.from_string(f.read())
    ctx = dict(
        scanvix_mqtt_username="allipuram_ingest",
        scanvix_mqtt_bench_enabled=False,
        scanvix_mqtt_devices=devices or [],
    )
    ctx.update(overrides)
    return tmpl.render(**ctx)


def _device(imei, enabled=True):
    return {
        "device_id": imei,
        "username": f"rtu_{imei}",
        "topic_root": f"storm/meters/{imei}",
        "enabled": enabled,
    }


DEVICE_A = "864012049873321"
DEVICE_B = "864012049873322"
DEVICE_C_DISABLED = "864012049873323"


class TestExistingCredentialPreserved:

    def test_allipuram_ingest_present_and_unrestricted(self):
        out = _render(devices=[])
        assert "user allipuram_ingest" in out
        assert "topic readwrite #" in out

    def test_allipuram_ingest_present_even_with_devices_configured(self):
        out = _render(devices=[_device(DEVICE_A)])
        assert "user allipuram_ingest" in out
        assert "topic readwrite #" in out


class TestDevicePermissions:

    def test_device_gets_write_on_telemetry_status_attributes(self):
        out = _render(devices=[_device(DEVICE_A)])
        assert f"topic write storm/meters/{DEVICE_A}/telemetry" in out
        assert f"topic write storm/meters/{DEVICE_A}/status" in out
        assert f"topic write storm/meters/{DEVICE_A}/attributes" in out

    def test_device_gets_read_on_cmd_only(self):
        out = _render(devices=[_device(DEVICE_A)])
        assert f"topic read storm/meters/{DEVICE_A}/cmd" in out
        # must not also grant write on cmd, or read on telemetry/status/attributes
        assert f"topic write storm/meters/{DEVICE_A}/cmd" not in out
        assert f"topic read storm/meters/{DEVICE_A}/telemetry" not in out

    def test_device_never_gets_broker_wide_hash(self):
        out = _render(devices=[_device(DEVICE_A)])
        device_section = out[out.index("Per-device RTU credentials"):]
        assert "readwrite #" not in device_section


class TestTopicIsolation:
    """Scenario 2/5 from the Phase 4 test list: Device A cannot publish to
    Device B's topics; Device B isolated from Device A."""

    def test_device_a_stanza_does_not_reference_device_b(self):
        out = _render(devices=[_device(DEVICE_A), _device(DEVICE_B)])
        start = out.index(f"user rtu_{DEVICE_A}")
        end = out.index(f"# Device {DEVICE_B}")
        block_a = out[start:end]
        assert DEVICE_B not in block_a

    def test_device_b_stanza_does_not_reference_device_a(self):
        out = _render(devices=[_device(DEVICE_A), _device(DEVICE_B)])
        start = out.index(f"user rtu_{DEVICE_B}")
        block_b = out[start:]
        assert DEVICE_A not in block_b

    def test_both_devices_present_with_distinct_topic_roots(self):
        out = _render(devices=[_device(DEVICE_A), _device(DEVICE_B)])
        assert f"storm/meters/{DEVICE_A}/telemetry" in out
        assert f"storm/meters/{DEVICE_B}/telemetry" in out


class TestDisabledDeviceExcluded:

    def test_disabled_device_produces_no_stanza(self):
        out = _render(devices=[_device(DEVICE_A), _device(DEVICE_C_DISABLED, enabled=False)])
        assert f"user rtu_{DEVICE_C_DISABLED}" not in out
        assert DEVICE_C_DISABLED not in out
        # the enabled device is unaffected by a disabled sibling
        assert f"user rtu_{DEVICE_A}" in out

    def test_all_devices_disabled_leaves_only_allipuram_ingest(self):
        out = _render(devices=[
            _device(DEVICE_A, enabled=False),
            _device(DEVICE_B, enabled=False),
        ])
        assert "user allipuram_ingest" in out
        assert f"user rtu_{DEVICE_A}" not in out
        assert f"user rtu_{DEVICE_B}" not in out


class TestNoPasswordLeakage:

    def test_no_password_shaped_text_in_rendered_output(self):
        out = _render(devices=[_device(DEVICE_A), _device(DEVICE_B, enabled=False)])
        for danger in ("password", "PASSWORD", "passwd_lookup", "secret", "SECRET"):
            assert danger not in out

    def test_template_source_itself_has_no_password_lookup(self):
        # Static check on the template source: this template must only ever
        # receive already-derived device metadata (username/topic_root),
        # never raw credentials -- it should not contain a `lookup(` call
        # or any literal that looks like a generated secret.
        with open(TEMPLATE_PATH) as f:
            src = f.read()
        assert "lookup(" not in src
        assert "password" not in src.lower() or "password_file" not in src  # defensive; template has no password_file directive at all
        assert "password_file" not in src


class TestEmptyDeviceList:

    def test_empty_device_list_renders_only_allipuram_ingest(self):
        out = _render(devices=[])
        assert "user allipuram_ingest" in out
        assert "user rtu_" not in out


class TestTemplateNotYetWiredIn:
    """Structural-inertness regression guard (static, not a render test):
    storm_acl.j2 must not be referenced by any task/playbook yet -- Phase 4
    is source-development only. This will need to be updated in the phase
    that actually wires acl_file/device provisioning into a live path."""

    def test_storm_acl_not_rendered_by_any_template_task(self):
        # Narrow, precise check: is there an actual Ansible `template:` /
        # `win_template:` task whose `src:` points at storm_acl.j2? A
        # comment or docstring merely *mentioning* the filename (as
        # device_credentials.yml and device_registry.yml both do, purely
        # as documentation of a *future* step) must NOT trip this check --
        # only a real module invocation that would cause Ansible to
        # actually render the template counts as "wired in".
        ansible_root = os.path.join(REPO_ROOT, "ansible", "scanvix_rtu")
        src_pattern = re.compile(r"(?:template|win_template)\s*:\s*[\s\S]*?\bsrc\s*:\s*.*storm_acl\.j2", re.IGNORECASE)
        offenders = []
        for path in glob.glob(os.path.join(ansible_root, "**", "*.yml"), recursive=True):
            if path.endswith(os.path.join("templates", "storm_acl.j2")):
                continue
            with open(path, errors="ignore") as f:
                content = f.read()
            if src_pattern.search(content):
                offenders.append(path)
        assert offenders == [], f"storm_acl.j2 is now rendered by a template task in: {offenders}"

    def test_storm_acl_filename_may_appear_only_in_documentation_comments(self):
        # Companion check: confirm the *only* other files mentioning the
        # filename are the two Phase 4 design files that reference it in a
        # comment (as a forward-pointer to a future phase), and that those
        # mentions are inside comment lines, not active YAML keys/values.
        ansible_root = os.path.join(REPO_ROOT, "ansible", "scanvix_rtu")
        expected = {
            os.path.join(ansible_root, "roles", "mqtt", "tasks", "device_credentials.yml"),
            os.path.join(ansible_root, "inventory", "device_registry.yml"),
        }
        found = set()
        for path in glob.glob(os.path.join(ansible_root, "**", "*.yml"), recursive=True):
            if path.endswith(os.path.join("templates", "storm_acl.j2")):
                continue
            if path.endswith(os.path.join("group_vars", "all.yml")):
                # Expected: scanvix_mqtt_acl_file's *value* is the future
                # rendered file's path (".../storm_acl", no .j2 -- it's
                # the destination path, not a template src reference).
                continue
            with open(path, errors="ignore") as f:
                lines = f.readlines()
            for line in lines:
                if "storm_acl" in line:
                    stripped = line.strip()
                    assert stripped.startswith("#"), (
                        f"{path}: non-comment line references storm_acl: {line!r}"
                    )
                    found.add(path)
        assert found <= expected, f"unexpected files reference storm_acl: {found - expected}"
