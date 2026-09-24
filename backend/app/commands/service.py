"""
Storm Energy RTU Platform — Command service.
Creates command records and dispatches via the configured channel.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.commands.models import CommandRequest, CommandResponse
from app.database.repository import CommandRepository

logger = logging.getLogger(__name__)


class CommandService:

    def __init__(self, mqtt_client=None):
        # mqtt_client is injected at startup — avoids circular import
        self._mqtt = mqtt_client

    def send_command(
        self,
        db: Session,
        device_id: str,
        request: CommandRequest,
    ) -> CommandResponse:
        # 1. Persist command record
        cmd = CommandRepository.create(
            db,
            DeviceId  = device_id,
            Protocol  = request.protocol,
            Command   = request.command,
            Payload   = request.payload,
            Status    = "PENDING",
        )
        db.commit()

        # 2. Dispatch
        if request.protocol == "MQTT" and self._mqtt and self._mqtt.is_connected:
            self._dispatch_mqtt(device_id, cmd.Id, request)
        elif request.protocol == "TCP":
            logger.info("TCP command dispatch not yet implemented — command queued: %s", request.command)
        elif request.protocol == "SMS":
            logger.info("SMS gateway not integrated — command queued: %s", request.command)
        else:
            logger.warning(
                "No dispatch channel available for %s on protocol %s",
                request.command, request.protocol
            )

        return CommandResponse(
            command_id = cmd.Id,
            device_id  = device_id,
            command    = request.command,
            status     = cmd.Status,
            message    = f"Command '{request.command}' queued via {request.protocol}",
        )

    def _dispatch_mqtt(self, device_id: str, cmd_id: int, request: CommandRequest) -> None:
        from app.protocol.mqtt_topics import cmd_topic
        from app.database.database import db_session
        from app.database.repository import CommandRepository as CR

        topic   = cmd_topic(device_id)
        payload = json.dumps({
            "commandId": cmd_id,
            "command":   request.command,
            "payload":   request.payload,
            "ts":        datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
        })
        self._mqtt.publish(topic, payload)

        with db_session() as db:
            CR.mark_sent(db, cmd_id)

        logger.info("Command dispatched via MQTT: device=%s cmd=%s topic=%s", device_id, request.command, topic)
