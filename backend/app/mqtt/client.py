"""
Storm Energy RTU Platform — Paho MQTT client wrapper.
Handles connection, TLS, authentication, reconnection, and subscription.
"""
from __future__ import annotations

import logging
import ssl
import threading
import time
from typing import Callable, Optional

import paho.mqtt.client as paho

from app.config import get_settings

logger = logging.getLogger(__name__)


class MQTTClient:
    """
    Thread-safe wrapper around paho-mqtt.
    Reconnects automatically with exponential back-off.
    """

    def __init__(self):
        self._settings = get_settings()
        self._client: Optional[paho.Client] = None
        self._connected = threading.Event()
        self._on_message_cb: Optional[Callable] = None
        self._reconnect_delay = self._settings.MQTT_RECONNECT_DELAY
        # Requested subscriptions {topic: qos}, reissued after every successful
        # connect (including reconnects) so a dropped/renewed session doesn't
        # silently stop delivering telemetry. A dict naturally de-duplicates by
        # topic: re-subscribing the same topic just updates its qos in place.
        self._subscriptions: dict[str, int] = {}

    # ── Public interface ─────────────────────────────────────────────────────

    def set_message_callback(self, cb: Callable) -> None:
        """Register a callback: cb(client, userdata, message)."""
        self._on_message_cb = cb

    def connect(self) -> None:
        s = self._settings
        client_id = f"{s.MQTT_CLIENT_ID}-{int(time.time())}"
        self._client = paho.Client(
            callback_api_version = paho.CallbackAPIVersion.VERSION1,
            client_id   = client_id,
            clean_session = True,
            protocol    = paho.MQTTv311,
        )

        # Credentials
        if s.MQTT_USERNAME:
            self._client.username_pw_set(s.MQTT_USERNAME, s.MQTT_PASSWORD)

        # TLS
        if s.MQTT_TLS_ENABLED:
            ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            ctx.load_verify_locations(cafile=s.MQTT_CA_CERT)
            try:
                ctx.load_cert_chain(certfile=s.MQTT_CLIENT_CERT, keyfile=s.MQTT_CLIENT_KEY)
                logger.info("MQTT TLS client certificate loaded (mutual TLS active)")
            except Exception as exc:
                # Client cert/key is OPTIONAL: server-only TLS (CA verification +
                # hostname check, both already configured above) still applies.
                # Logged at warning (not silently swallowed) so a genuinely
                # missing/broken cert pair is visible instead of masking mTLS
                # being unintentionally disabled.
                logger.warning(
                    "MQTT TLS client certificate not loaded (%s) -- "
                    "continuing with server-only TLS, no mutual TLS", exc
                )
            self._client.tls_set_context(ctx)
            logger.info("MQTT TLS enabled (CA=%s)", s.MQTT_CA_CERT)

        # Callbacks
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message
        self._client.on_subscribe  = self._on_subscribe

        port = s.MQTT_TLS_PORT if s.MQTT_TLS_ENABLED else s.MQTT_PORT
        logger.info("Connecting to MQTT broker %s:%d …", s.MQTT_HOST, port)
        self._client.connect_async(s.MQTT_HOST, port, keepalive=s.MQTT_KEEPALIVE)
        self._client.loop_start()

    def disconnect(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    def subscribe(self, topic: str, qos: int = 1) -> None:
        # Record first so this topic is included in any future (re)subscribe
        # pass regardless of whether the live client exists/is connected yet.
        self._subscriptions[topic] = qos
        if self._client:
            self._client.subscribe(topic, qos=qos)

    def publish(self, topic: str, payload: str, qos: int = 1) -> None:
        if self._client and self._connected.is_set():
            self._client.publish(topic, payload=payload, qos=qos)
        else:
            logger.warning("MQTT publish attempted while disconnected — topic=%s", topic)

    def wait_connected(self, timeout: float = 30.0) -> bool:
        return self._connected.wait(timeout=timeout)

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    # ── paho callbacks ────────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected.set()
            self._reconnect_delay = self._settings.MQTT_RECONNECT_DELAY
            logger.info("MQTT connected to %s:%s",
                        self._settings.MQTT_HOST,
                        self._settings.MQTT_TLS_PORT if self._settings.MQTT_TLS_ENABLED
                        else self._settings.MQTT_PORT)
            # Restore subscriptions on EVERY successful connect, not just the
            # first one. clean_session=True means the broker discards prior
            # subscription state on disconnect, so a reconnect otherwise
            # leaves the client connected but silently unsubscribed -- the
            # root cause of telemetry ingestion stopping after rc!=0 drops.
            # On the very first connect this is a no-op: the caller's own
            # subscribe() calls (issued after connect() returns, per the
            # existing MQTTConsumer.start() flow) populate _subscriptions
            # and issue their own live SUBSCRIBE immediately afterward, same
            # as before this change.
            self._resubscribe_all()
        else:
            codes = {
                1: "UNACCEPTABLE_PROTOCOL",
                2: "IDENTIFIER_REJECTED",
                3: "SERVER_UNAVAILABLE",
                4: "BAD_CREDENTIALS",
                5: "NOT_AUTHORISED",
            }
            reason = codes.get(rc, f"rc={rc}")
            logger.error("MQTT connection refused: %s", reason)

    def _resubscribe_all(self) -> None:
        """Reissue every recorded subscription. Called after every successful
        (re)connect. Does not block: iterates and calls the non-blocking
        paho subscribe() for each topic, no sleeps/waits."""
        # Iterate over a snapshot: this runs on the paho network thread while
        # MQTTConsumer.start() may be adding subscriptions from the main thread.
        # Iterating the live dict raised "dictionary changed size during
        # iteration" and killed the paho network thread (consumer silently deaf).
        subscriptions = list(self._subscriptions.items())
        if not subscriptions:
            return
        for topic, qos in subscriptions:
            self._client.subscribe(topic, qos=qos)
        logger.info("MQTT resubscribed to %d topic(s) after (re)connect",
                    len(subscriptions))

    def _on_disconnect(self, client, userdata, rc):
        self._connected.clear()
        if rc != 0:
            delay = min(self._reconnect_delay, self._settings.MQTT_MAX_RECONNECT_DELAY)
            logger.warning("MQTT disconnected (rc=%d), reconnecting in %ds …", rc, delay)
            time.sleep(delay)
            self._reconnect_delay = min(self._reconnect_delay * 2,
                                        self._settings.MQTT_MAX_RECONNECT_DELAY)
        else:
            logger.info("MQTT cleanly disconnected")

    def _on_message(self, client, userdata, message):
        if self._on_message_cb:
            try:
                self._on_message_cb(client, userdata, message)
            except Exception as exc:
                logger.exception("Unhandled error in MQTT message callback: %s", exc)

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        logger.info("MQTT subscription confirmed (mid=%d, qos=%s)", mid, granted_qos)
