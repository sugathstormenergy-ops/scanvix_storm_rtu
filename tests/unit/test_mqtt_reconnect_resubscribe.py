"""
Storm Energy RTU Platform — MQTT reconnect/resubscribe regression tests.

Root cause under test: with clean_session=True, the broker discards a
client's subscription state on every disconnect. MQTTConsumer.start() only
issued SUBSCRIBE once, right after the *first* connect. When Paho's
loop_start() background thread auto-reconnected after a drop (e.g. rc=7),
_on_connect fired again but nothing resubscribed -- the client showed
"connected" while silently receiving no telemetry.

Fix under test (app/mqtt/client.py only): MQTTClient.subscribe() records
{topic: qos} in self._subscriptions; _on_connect() reissues every recorded
subscription after every successful connect, including reconnects.

All tests mock paho.mqtt.client.Client entirely -- no real network I/O,
matching the existing convention in tests/unit/test_mqtt_tls_config.py.
"""
import sys
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, "backend")

from app.config import Settings
from app.mqtt.client import MQTTClient


def make_settings(**overrides):
    base = dict(API_SECRET_KEY="test-secret", SQL_SERVER="test-sql-server")
    base.update(overrides)
    return Settings(**base)


def build_client(settings):
    with patch("app.mqtt.client.get_settings", return_value=settings):
        client = MQTTClient()
    client._settings = settings
    return client


TOPICS = [
    ("storm/meters/+/telemetry", 1),
    ("storm/meters/+/status", 1),
    ("storm/meters/+/attributes", 1),
]


class TestInitialConnectionAndSubscriptions:
    """13a — initial connection + subscriptions."""

    @patch("app.mqtt.client.paho.Client")
    def test_first_connect_then_subscribe_issues_all_three(self, mock_paho_client):
        mock_paho_client.return_value = MagicMock()
        s = make_settings()
        client = build_client(s)
        client.connect()

        # Mirrors MQTTConsumer.start(): connect() first, subscribe() after.
        for topic, qos in TOPICS:
            client.subscribe(topic, qos=qos)

        live = mock_paho_client.return_value.subscribe
        assert live.call_count == 3
        for topic, qos in TOPICS:
            live.assert_any_call(topic, qos=qos)
        assert client._subscriptions == dict(TOPICS)

    @patch("app.mqtt.client.paho.Client")
    def test_first_on_connect_is_a_noop_when_nothing_subscribed_yet(self, mock_paho_client):
        """13f (initial connection still works correctly) — before the
        caller's own subscribe() calls run, an empty _subscriptions means
        _on_connect's resubscribe pass does nothing extra; behavior for the
        very first connect is unchanged from before this fix."""
        mock_paho_client.return_value = MagicMock()
        client = build_client(make_settings())
        client.connect()

        client._on_connect(mock_paho_client.return_value, None, {}, 0)

        mock_paho_client.return_value.subscribe.assert_not_called()
        assert client.is_connected is True


class TestReconnectResubscribes:
    """13b + 13c — unexpected disconnect+reconnect, and subscriptions are
    actually restored (this is the core fix)."""

    @patch("app.mqtt.client.time.sleep")
    @patch("app.mqtt.client.paho.Client")
    def test_unexpected_disconnect_sets_disconnected_and_backs_off(self, mock_paho_client, mock_sleep):
        mock_paho_client.return_value = MagicMock()
        client = build_client(make_settings(MQTT_RECONNECT_DELAY=5, MQTT_MAX_RECONNECT_DELAY=120))
        client.connect()
        client._on_connect(mock_paho_client.return_value, None, {}, 0)
        assert client.is_connected is True

        client._on_disconnect(mock_paho_client.return_value, None, 7)  # rc=7, matches the production log

        assert client.is_connected is False
        mock_sleep.assert_called_once_with(5)
        assert client._reconnect_delay == 10  # doubled for next time

    @patch("app.mqtt.client.time.sleep")
    @patch("app.mqtt.client.paho.Client")
    def test_subscriptions_restored_after_reconnect(self, mock_paho_client, mock_sleep):
        """The exact bug: after rc!=0 disconnect + Paho's own auto-reconnect
        firing _on_connect again, every previously-subscribed topic must be
        reissued -- without MQTTConsumer or anything else calling subscribe()
        a second time."""
        mock_paho_client.return_value = MagicMock()
        client = build_client(make_settings())
        client.connect()

        # First connect + the consumer's normal post-connect subscribe calls.
        client._on_connect(mock_paho_client.return_value, None, {}, 0)
        for topic, qos in TOPICS:
            client.subscribe(topic, qos=qos)
        mock_paho_client.return_value.subscribe.reset_mock()

        # Simulate the production scenario: disconnect (rc=7) then Paho's
        # background loop auto-reconnecting -- _on_connect fires again.
        client._on_disconnect(mock_paho_client.return_value, None, 7)
        client._on_connect(mock_paho_client.return_value, None, {}, 0)

        live = mock_paho_client.return_value.subscribe
        assert live.call_count == 3, "all three subscriptions must be reissued on reconnect"
        for topic, qos in TOPICS:
            live.assert_any_call(topic, qos=qos)
        assert client.is_connected is True

    @patch("app.mqtt.client.time.sleep")
    @patch("app.mqtt.client.paho.Client")
    def test_multiple_reconnects_keep_restoring_subscriptions(self, mock_paho_client, mock_sleep):
        """Not just once -- every subsequent reconnect must also resubscribe."""
        mock_paho_client.return_value = MagicMock()
        client = build_client(make_settings())
        client.connect()
        client._on_connect(mock_paho_client.return_value, None, {}, 0)
        client.subscribe(*TOPICS[0])

        for _ in range(3):
            mock_paho_client.return_value.subscribe.reset_mock()
            client._on_disconnect(mock_paho_client.return_value, None, 7)
            client._on_connect(mock_paho_client.return_value, None, {}, 0)
            mock_paho_client.return_value.subscribe.assert_called_once_with(
                TOPICS[0][0], qos=TOPICS[0][1]
            )


class TestNoDuplicateSubscriptions:
    """13d — duplicate subscribe calls do not create duplicate entries."""

    @patch("app.mqtt.client.paho.Client")
    def test_subscribing_same_topic_twice_keeps_one_entry(self, mock_paho_client):
        mock_paho_client.return_value = MagicMock()
        client = build_client(make_settings())
        client.connect()

        client.subscribe("storm/meters/+/telemetry", qos=1)
        client.subscribe("storm/meters/+/telemetry", qos=1)

        assert len(client._subscriptions) == 1
        assert client._subscriptions["storm/meters/+/telemetry"] == 1

    @patch("app.mqtt.client.paho.Client")
    def test_resubscribing_same_topic_with_different_qos_updates_in_place(self, mock_paho_client):
        mock_paho_client.return_value = MagicMock()
        client = build_client(make_settings())
        client.connect()

        client.subscribe("storm/meters/+/status", qos=0)
        client.subscribe("storm/meters/+/status", qos=1)

        assert len(client._subscriptions) == 1
        assert client._subscriptions["storm/meters/+/status"] == 1

    @patch("app.mqtt.client.paho.Client")
    def test_distinct_topics_each_get_their_own_entry(self, mock_paho_client):
        mock_paho_client.return_value = MagicMock()
        client = build_client(make_settings())
        client.connect()
        for topic, qos in TOPICS:
            client.subscribe(topic, qos=qos)
        assert len(client._subscriptions) == 3


class TestCleanDisconnectDoesNotReconnect:
    """13e — clean disconnect does not reconnect."""

    @patch("app.mqtt.client.time.sleep")
    @patch("app.mqtt.client.paho.Client")
    def test_clean_disconnect_no_sleep_no_backoff_change(self, mock_paho_client, mock_sleep):
        mock_paho_client.return_value = MagicMock()
        client = build_client(make_settings(MQTT_RECONNECT_DELAY=5))
        client.connect()
        client._on_connect(mock_paho_client.return_value, None, {}, 0)
        original_delay = client._reconnect_delay

        client._on_disconnect(mock_paho_client.return_value, None, 0)  # rc=0: clean

        mock_sleep.assert_not_called()
        assert client._reconnect_delay == original_delay
        assert client.is_connected is False

    @patch("app.mqtt.client.paho.Client")
    def test_public_disconnect_method_does_not_block(self, mock_paho_client):
        """disconnect() itself must not hang; it only calls into paho."""
        mock_paho_client.return_value = MagicMock()
        client = build_client(make_settings())
        client.connect()
        client.disconnect()
        mock_paho_client.return_value.loop_stop.assert_called_once()
        mock_paho_client.return_value.disconnect.assert_called_once()


class TestOnSubscribeLoggingPreserved:
    """Requirement 9 — existing on_subscribe logging/behavior untouched."""

    @patch("app.mqtt.client.paho.Client")
    def test_on_subscribe_does_not_raise_and_is_unchanged(self, mock_paho_client):
        mock_paho_client.return_value = MagicMock()
        client = build_client(make_settings())
        client.connect()
        # Must not raise; signature/behavior identical to before this change.
        client._on_subscribe(mock_paho_client.return_value, None, 42, [1])
