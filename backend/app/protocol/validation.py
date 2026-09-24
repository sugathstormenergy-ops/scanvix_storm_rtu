"""
Storm Energy RTU Platform — Payload validation.
Structured error types for every known failure mode.
One bad packet must never crash the platform.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ValidationErrorCode(str, Enum):
    INVALID_JSON        = "INVALID_JSON"
    MISSING_DEVICE_ID   = "MISSING_DEVICE_ID"
    MISSING_TIMESTAMP   = "MISSING_TIMESTAMP"
    INVALID_TIMESTAMP   = "INVALID_TIMESTAMP"
    INVALID_FLOW        = "INVALID_FLOW"
    UNKNOWN_DEVICE      = "UNKNOWN_DEVICE"
    INVALID_TOPIC       = "INVALID_TOPIC"
    MALFORMED_PACKET    = "MALFORMED_PACKET"
    TCP_TIMEOUT         = "TCP_TIMEOUT"
    DUPLICATE_TELEMETRY = "DUPLICATE_TELEMETRY"
    DATABASE_ERROR      = "DATABASE_ERROR"
    MQTT_AUTH_FAILURE   = "MQTT_AUTH_FAILURE"


@dataclass
class ValidationError:
    code:    ValidationErrorCode
    message: str
    raw:     Any = None   # original payload for archival


class PayloadValidationError(Exception):
    """Raised when a payload cannot be parsed or fails validation."""
    def __init__(self, code: ValidationErrorCode, message: str, raw: Any = None):
        super().__init__(message)
        self.error = ValidationError(code=code, message=message, raw=raw)
