"""
Storm Energy RTU Platform — Phase 5 regression test.

Confirms the acl_file fix applied to roles/mqtt/templates/mosquitto.conf.j2
during Phase 5: the 8883 TLS listener block must ALWAYS render an
`acl_file` directive whenever it renders at all (i.e. whenever
scanvix_mqtt_tls_enabled is true) -- unlike the 1883 listener, where
acl_file is gated behind the separate scanvix_mqtt_acl_enabled switch,
because 1883 is already live in production and its ACL rollout is a
deliberate, independent step.

Without this, flipping scanvix_mqtt_tls_enabled: true (turning 8883 on)
while scanvix_mqtt_acl_enabled stays false (its default) would have
produced an authenticated-but-completely-unrestricted 8883 listener --
any valid credential would get broker-wide access, defeating the entire
per-device ACL design the moment 8883 becomes production.

Uses the same ansible `bool` filter shim as the other template-rendering
tests in this suite (test_storm_acl_template.py, Phase 4).
"""
import os

import pytest

jinja2 = pytest.importorskip("jinja2")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TEMPLATE_PATH = os.path.join(
    REPO_ROOT, "ansible", "scanvix_rtu", "roles", "mqtt", "templates", "mosquitto.conf.j2"
)


def _ansible_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", "on")
    return bool(v)


def _acl_directive_lines(rendered):
    return [l for l in rendered.splitlines() if l.strip().startswith("acl_file ")]


def _render(**overrides):
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = _ansible_bool
    with open(TEMPLATE_PATH) as f:
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


class TestCurrentProductionStateUnaffected:

    def test_todays_live_vars_render_with_no_acl_file_and_no_8883_listener(self):
        # Matches the ACTUAL current inventory/group_vars/all.yml values:
        # bench on, tls off, acl off.
        out = _render(scanvix_mqtt_bench_enabled=True)
        assert _acl_directive_lines(out) == []
        assert "listener 8883" not in out
        assert "listener 1883 127.0.0.1" in out
        assert "listener 1885" in out


class Test8883CannotRunWithoutAcl:

    def test_tls_on_acl_master_switch_off_still_forces_acl_file_onto_8883(self):
        out = _render(scanvix_mqtt_tls_enabled=True, scanvix_mqtt_acl_enabled=False)
        lines = _acl_directive_lines(out)
        assert len(lines) == 1
        idx_acl = out.index(lines[0])
        idx_8883 = out.index("listener 8883")
        assert idx_8883 < idx_acl, "acl_file must be inside the 8883 block"

    def test_1883_unaffected_by_8883s_unconditional_acl_when_1883_acl_off(self):
        out = _render(scanvix_mqtt_tls_enabled=True, scanvix_mqtt_acl_enabled=False)
        idx_1883_block_end = out.index("listener 8883")
        block_1883 = out[: idx_1883_block_end]
        assert "acl_file" not in block_1883.split("password_file")[0] or True
        # More precise: no acl_file directive line appears before the 8883
        # listener starts.
        lines_before_8883 = [
            l for l in out[:idx_1883_block_end].splitlines()
            if l.strip().startswith("acl_file ")
        ]
        assert lines_before_8883 == []

    def test_tls_and_acl_both_on_yields_exactly_two_acl_file_directives(self):
        out = _render(scanvix_mqtt_tls_enabled=True, scanvix_mqtt_acl_enabled=True)
        lines = _acl_directive_lines(out)
        assert len(lines) == 2
        # both point at the same acl file (one shared storm_acl for both listeners)
        assert lines[0].split("acl_file ", 1)[1] == lines[1].split("acl_file ", 1)[1]
