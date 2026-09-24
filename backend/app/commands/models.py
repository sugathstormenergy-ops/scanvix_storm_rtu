"""
Storm Energy RTU Platform — Command models and definitions.

Supported commands (from Scanvix V1.3 spec):
  GETFLOW, GETCONFIG, GETMODE, GETDETAILS,
  SETMODE, SETSERVER, SETPORT, SETMQTT, REBOOT, RANGE, SIT

The command routing architecture:
  FastAPI → CommandService → MQTT cmd topic / TCP channel / SMS gateway → RTU

SMS gateway is NOT directly integrated here. Storm owns SMS gateway integration.
The CommandService produces a pending command record and the MQTT publisher
delivers it. TCP and SMS channels are stubbed for future integration.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RTUCommand(str, Enum):
    GETFLOW    = "GETFLOW"
    GETCONFIG  = "GETCONFIG"
    GETMODE    = "GETMODE"
    GETDETAILS = "GETDETAILS"
    SETMODE    = "SETMODE"
    SETSERVER  = "SETSERVER"
    SETPORT    = "SETPORT"
    SETMQTT    = "SETMQTT"
    REBOOT     = "REBOOT"
    RANGE      = "RANGE"
    SIT        = "SIT"


class CommandRequest(BaseModel):
    command:  RTUCommand
    payload:  Optional[str] = Field(None, description="Command parameter, e.g. '3200' for RANGE")
    protocol: str           = Field("MQTT", description="Delivery channel: MQTT | TCP | SMS")


class CommandResponse(BaseModel):
    command_id: int
    device_id:  str
    command:    str
    status:     str
    message:    str
