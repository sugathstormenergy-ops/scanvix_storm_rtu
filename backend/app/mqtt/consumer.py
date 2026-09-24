"""
Storm Energy RTU Platform — MQTT Consumer.
Subscribes to all Storm meter topics and routes inbound messages
through the shared telemetry pipeline.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from app.timezone import now_ist
from typing import Optional

from app.config import get_settings
from app.database.database import db_session
from app.database.repository import MQTTMessageRepository, RawMessageRepository
from app.mqtt.client import MQTTClient
from app.protocol.mqtt_parser import parse_mqtt_payload
from app.protocol.mqtt_topics import (
    SUBSCRIBE_ALL, SUBSCRIBE_ATTRIBUTES, SUBSCRIBE_STATUS, parse_topic,
)
from app.protocol.validation import PayloadValidationError
from app.services.telemetry_service import TelemetryService

logger = logging.getLogger(__name__)


class MQTTConsumer:
    """
    Runs the MQTT client in a background thread.
    Inbound telemetry is processed synchronously in the callback thread
    with a dedicated DB session per message.
    """

    def __init__(self):
        self._client      = MQTTClient()
        self._settings    = get_settings()
        self._telemetry   = TelemetryService()
        self._running     = False
        self._lock        = threading.Lock()
        self._msg_count   = 0
        self._err_count   = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True

        self._client.set_message_callback(self._handle_message)
        self._client.connect()

        # Wait for connection then subscribe
        if self._client.wait_connected(timeout=30.0):
            self._client.subscribe(SUBSCRIBE_ALL,       qos=self._settings.MQTT_QOS)
            self._client.subscribe(SUBSCRIBE_STATUS,    qos=self._settings.MQTT_QOS)
            self._client.subscribe(SUBSCRIBE_ATTRIBUTES,qos=self._settings.MQTT_QOS)
            logger.info("MQTT consumer running — subscribed to storm/meters/+/{telemetry,status,attributes}")
        else:
            logger.error("MQTT consumer failed to connect within 30s — will retry in background")

    def stop(self) -> None:
        with self._lock:
            self._running = False
        self._client.disconnect()
        logger.info("MQTT consumer stopped (processed=%d, errors=%d)", self._msg_count, self._err_count)

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    @property
    def stats(self) -> dict:
        return {"messages_processed": self._msg_count, "errors": self._err_count}

    # ── Message handling ──────────────────────────────────────────────────────

    def _handle_message(self, client, userdata, message) -> None:
        topic   = message.topic
        payload = message.payload
        qos     = message.qos

        logger.debug("MQTT RX: topic=%s qos=%d len=%d", topic, qos, len(payload))
        self._msg_count += 1

        parsed_topic = parse_topic(topic)
        if parsed_topic is None:
            logger.warning("MQTT message on unexpected topic '%s' — ignored", topic)
            return

        if parsed_topic.message_type == "telemetry":
            self._process_telemetry(topic, payload, qos)
        elif parsed_topic.message_type == "status":
            self._process_status(topic, payload)
        else:
            logger.debug("MQTT topic type '%s' received — no handler yet", parsed_topic.message_type)

    def _process_telemetry(self, topic: str, payload: bytes, qos: int) -> None:
        raw_id: Optional[int] = None

        try:
            with db_session() as db:
                # 1. Archive raw message — always, even if invalid
                raw = RawMessageRepository.create(
                    db,
                    Protocol   = "MQTT",
                    ReceivedAt = now_ist(),
                    Topic      = topic,
                    Payload    = payload.decode("utf-8", errors="replace"),
                    IsValid    = True,
                )
                raw_id = raw.Id

                # 2. Parse
                try:
                    telemetry = parse_mqtt_payload(topic, payload)
                    telemetry.raw_message_id = raw_id
                except PayloadValidationError as ve:
                    raw.IsValid    = True   # message received — invalid content
                    raw.ErrorMessage = str(ve)
                    db.flush()
                    logger.warning("MQTT parse error [%s]: %s | topic=%s", ve.error.code, ve, topic)
                    self._err_count += 1
                    # Archive MQTT message record with INVALID status
                    MQTTMessageRepository.create(
                        db,
                        Topic        = topic,
                        DeviceId     = None,
                        QoS          = qos,
                        Payload      = payload.decode("utf-8", errors="replace"),
                        Status       = "INVALID",
                        RawMessageId = raw_id,
                    )
                    return

                # 3. Archive MQTT message record
                mqtt_msg = MQTTMessageRepository.create(
                    db,
                    Topic        = topic,
                    DeviceId     = telemetry.device_id,
                    QoS          = qos,
                    Payload      = payload.decode("utf-8", errors="replace"),
                    Status       = "RECEIVED",
                    RawMessageId = raw_id,
                )

                # 4. Ingest through shared pipeline
                result = self._telemetry.ingest(db, telemetry)

                # 5. Update MQTT message status
                status = "PROCESSED" if result["status"] == "stored" else result["status"].upper()
                MQTTMessageRepository.update_status(db, mqtt_msg.Id, status)

                logger.info(
                    "MQTT telemetry ingested: device=%s ts=%s status=%s historical=%s",
                    telemetry.device_id, telemetry.timestamp,
                    result["status"], result["is_historical"],
                )

        except Exception as exc:
            self._err_count += 1
            logger.exception("Unhandled error processing MQTT telemetry on topic %s: %s", topic, exc)

    def _process_status(self, topic: str, payload: bytes) -> None:
        """Handle device status messages — update device last-seen."""
        try:
            import json
            data = json.loads(payload)
            logger.info("MQTT status message: topic=%s data=%s", topic, data)
        except Exception as exc:
            logger.warning("MQTT status parse error on %s: %s", topic, exc)
