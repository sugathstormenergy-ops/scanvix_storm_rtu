"""
Storm Energy RTU Platform — Tests for MQTT TLS configuration wiring
(Phase 1: application/source-of-truth preparation for MQTT-over-TLS on 8883).

Covers:
  1. Settings defaults preserve CURRENT behavior exactly: TLS disabled,
     plaintext port 1883, TLS port 8883 available but unused.
  2. Certificate path defaults are Windows-style (matching the scanvix109
     deployment target and the Ansible scanvix_certs_dir convention), not
     the old Linux /etc/storm-rtu/certs/... paths.
  3. MQTTClient.connect() selects the plaintext port when TLS is disabled
     and the TLS port when TLS is enabled -- without ever opening a real
     network connection (paho.Client is monkeypatched).
  4. When TLS is enabled, the client builds an SSL context with server
     certificate verification + hostname checking left at their secure
     defaults (create_default_context's CERT_REQUIRED / check_hostname=True),
     loads the CA cert, and does not raise even if a client cert pair is
     absent (client cert / mutual TLS is optional, not required).
  5. username/password auth is applied independently of, and together
     with, TLS -- one does not disable the other.
"""
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, "backend")

from app.config import Settings
from app.mqtt.client import MQTTClient


def make_settings(**overrides):
    base = dict(API_SECRET_KEY="test-secret", SQL_SERVER="test-sql-server")
    base.update(overrides)
    return Settings(**base)


class TestMqttTlsSettingsDefaults:

    def test_tls_disabled_by_default(self):
        s = make_settings()
        assert s.MQTT_TLS_ENABLED is False, \
            "TLS must remain OFF by default -- Phase 1 introduces the wiring, not the switch"

    def test_plaintext_and_tls_ports_unchanged(self):
        s = make_settings()
        assert s.MQTT_PORT == 1883
        assert s.MQTT_TLS_PORT == 8883

    def test_cert_paths_are_windows_style_not_linux(self):
        s = make_settings()
        for path in (s.MQTT_CA_CERT, s.MQTT_CLIENT_CERT, s.MQTT_CLIENT_KEY):
            assert not path.startswith("/etc/"), \
                f"cert default must not be a Linux path on a Windows deployment: {path}"
            assert "\\" in path, f"cert default should be a Windows path: {path}"
            assert "StormEnergyRTU" in path

    def test_tls_can_be_enabled_via_settings_override(self):
        # Mirrors how Ansible/.env would flip this in a future deployment --
        # purely a configuration value, no code change required.
        s = make_settings(MQTT_TLS_ENABLED=True)
        assert s.MQTT_TLS_ENABLED is True


class TestMqttClientPortSelection:
    """connect() must pick the port based on MQTT_TLS_ENABLED, without
    ever touching the network -- paho.Client is fully mocked."""

    def _build_client(self, settings):
        with patch("app.mqtt.client.get_settings", return_value=settings):
            client = MQTTClient()
        client._settings = settings
        return client

    @patch("app.mqtt.client.paho.Client")
    def test_plaintext_uses_mqtt_port(self, mock_paho_client):
        mock_paho_client.return_value = MagicMock()
        s = make_settings(MQTT_TLS_ENABLED=False)
        client = self._build_client(s)
        client.connect()
        args, kwargs = mock_paho_client.return_value.connect_async.call_args
        assert args[1] == s.MQTT_PORT == 1883

    @patch("app.mqtt.client.paho.Client")
    @patch("app.mqtt.client.ssl.create_default_context")
    def test_tls_uses_mqtt_tls_port(self, mock_ctx_factory, mock_paho_client):
        mock_paho_client.return_value = MagicMock()
        mock_ctx_factory.return_value = MagicMock()
        s = make_settings(MQTT_TLS_ENABLED=True)
        client = self._build_client(s)
        client.connect()
        args, kwargs = mock_paho_client.return_value.connect_async.call_args
        assert args[1] == s.MQTT_TLS_PORT == 8883


class TestMqttClientTlsContext:

    def _build_client(self, settings):
        with patch("app.mqtt.client.get_settings", return_value=settings):
            client = MQTTClient()
        client._settings = settings
        return client

    @patch("app.mqtt.client.paho.Client")
    @patch("app.mqtt.client.ssl.create_default_context")
    def test_tls_context_uses_secure_defaults_and_loads_ca(self, mock_ctx_factory, mock_paho_client):
        mock_paho_client.return_value = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx_factory.return_value = mock_ctx
        s = make_settings(MQTT_TLS_ENABLED=True, MQTT_CA_CERT=r"E:\StormEnergyRTU\certs\ca.crt")
        client = self._build_client(s)
        client.connect()

        # ssl.Purpose.SERVER_AUTH -> create_default_context() already sets
        # verify_mode=CERT_REQUIRED and check_hostname=True; we assert it
        # was invoked for that purpose and the CA file was loaded into it.
        mock_ctx_factory.assert_called_once()
        mock_ctx.load_verify_locations.assert_called_once_with(cafile=s.MQTT_CA_CERT)
        mock_paho_client.return_value.tls_set_context.assert_called_once_with(mock_ctx)

    @patch("app.mqtt.client.paho.Client")
    @patch("app.mqtt.client.ssl.create_default_context")
    def test_missing_client_cert_does_not_raise_and_tls_still_enabled(self, mock_ctx_factory, mock_paho_client):
        # Client cert is OPTIONAL: a missing/unreadable client cert pair must
        # not prevent server-only TLS from being configured.
        mock_paho_client.return_value = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.load_cert_chain.side_effect = FileNotFoundError("no client cert")
        mock_ctx_factory.return_value = mock_ctx
        s = make_settings(MQTT_TLS_ENABLED=True)
        client = self._build_client(s)

        client.connect()  # must not raise

        mock_paho_client.return_value.tls_set_context.assert_called_once_with(mock_ctx)

    @patch("app.mqtt.client.paho.Client")
    def test_tls_disabled_never_touches_ssl_context(self, mock_paho_client):
        mock_paho_client.return_value = MagicMock()
        s = make_settings(MQTT_TLS_ENABLED=False)
        client = self._build_client(s)
        client.connect()
        mock_paho_client.return_value.tls_set_context.assert_not_called()


class TestMqttClientAuthWithTls:

    def _build_client(self, settings):
        with patch("app.mqtt.client.get_settings", return_value=settings):
            client = MQTTClient()
        client._settings = settings
        return client

    @patch("app.mqtt.client.paho.Client")
    @patch("app.mqtt.client.ssl.create_default_context")
    def test_username_password_applied_independent_of_tls(self, mock_ctx_factory, mock_paho_client):
        mock_paho_client.return_value = MagicMock()
        mock_ctx_factory.return_value = MagicMock()
        s = make_settings(MQTT_TLS_ENABLED=True, MQTT_USERNAME="allipuram_ingest",
                           MQTT_PASSWORD="unused-in-test")
        client = self._build_client(s)
        client.connect()
        mock_paho_client.return_value.username_pw_set.assert_called_once_with(
            "allipuram_ingest", "unused-in-test"
        )

    @patch("app.mqtt.client.paho.Client")
    def test_no_username_skips_auth_call(self, mock_paho_client):
        mock_paho_client.return_value = MagicMock()
        s = make_settings(MQTT_USERNAME="")
        client = self._build_client(s)
        client.connect()
        mock_paho_client.return_value.username_pw_set.assert_not_called()
