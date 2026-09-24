"""
Storm Energy RTU Platform — Command API.
POST /api/devices/{device_id}/commands
GET  /api/devices/{device_id}/commands
"""
from __future__ import annotations

from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.commands.models import CommandRequest, CommandResponse
from app.commands.service import CommandService
from app.database.database import get_db

router = APIRouter(prefix="/api/devices", tags=["Commands"])

_command_service: Optional[CommandService] = None


def set_command_service(svc: CommandService) -> None:
    global _command_service
    _command_service = svc


class CommandOut(BaseModel):
    id:         int
    device_id:  str
    command:    str
    protocol:   str
    payload:    Optional[str]
    status:     str
    created_at: datetime
    sent_at:    Optional[datetime]
    response:   Optional[str]


@router.post("/{device_id}/commands", response_model=CommandResponse,
             summary="Send a command to a device")
def send_command(device_id: str, body: CommandRequest, db: Session = Depends(get_db)):
    if _command_service is None:
        raise HTTPException(status_code=503, detail="Command service not initialised")
    return _command_service.send_command(db, device_id, body)


@router.get("/{device_id}/commands", response_model=List[CommandOut],
            summary="List commands for a device")
def list_commands(device_id: str, limit: int = 50, db: Session = Depends(get_db)):
    from app.database.repository import CommandRepository
    cmds = CommandRepository.get_for_device(db, device_id, limit)
    return [
        CommandOut(
            id         = c.Id,
            device_id  = c.DeviceId,
            command    = c.Command,
            protocol   = c.Protocol,
            payload    = c.Payload,
            status     = c.Status,
            created_at = c.CreatedAt,
            sent_at    = c.SentAt,
            response   = c.Response,
        )
        for c in cmds
    ]
