"""
Storm Energy RTU Platform — SQLAlchemy ORM Models.
These models mirror the SQL Server schema exactly.
All nullable optional fields use nullable=True.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from app.timezone import now_ist

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class CommunicationMode(str, enum.Enum):
    MQTT = "MQTT"
    TCP  = "TCP"
    BOTH = "BOTH"


class Protocol(str, enum.Enum):
    MQTT = "MQTT"
    TCP  = "TCP"


class CommandStatus(str, enum.Enum):
    PENDING  = "PENDING"
    SENT     = "SENT"
    ACKED    = "ACKED"
    FAILED   = "FAILED"
    EXPIRED  = "EXPIRED"


class MessageStatus(str, enum.Enum):
    RECEIVED  = "RECEIVED"
    PROCESSED = "PROCESSED"
    INVALID   = "INVALID"
    DUPLICATE = "DUPLICATE"


class EventSeverity(str, enum.Enum):
    INFO     = "INFO"
    WARNING  = "WARNING"
    ERROR    = "ERROR"
    CRITICAL = "CRITICAL"


class EventType(str, enum.Enum):
    CONNECTED            = "CONNECTED"
    DISCONNECTED         = "DISCONNECTED"
    MQTT_CONNECTED       = "MQTT_CONNECTED"
    MQTT_DISCONNECTED    = "MQTT_DISCONNECTED"
    TCP_CONNECTED        = "TCP_CONNECTED"
    TCP_DISCONNECTED     = "TCP_DISCONNECTED"
    INVALID_PAYLOAD      = "INVALID_PAYLOAD"
    CONFIG_CHANGED       = "CONFIG_CHANGED"
    COMMAND_SENT         = "COMMAND_SENT"
    COMMAND_ACK          = "COMMAND_ACK"
    FIRMWARE_CHANGED     = "FIRMWARE_CHANGED"
    DUPLICATE_TELEMETRY  = "DUPLICATE_TELEMETRY"
    HISTORICAL_TELEMETRY = "HISTORICAL_TELEMETRY"


# ─────────────────────────────────────────────────────────────────────────────
# Devices
# ─────────────────────────────────────────────────────────────────────────────

class Device(Base):
    __tablename__ = "Devices"

    Id:                 Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    DeviceId:           Mapped[str]           = mapped_column(String(50), nullable=False, unique=True, index=True)
    IMEI:               Mapped[str]           = mapped_column(String(20), nullable=False, unique=True, index=True)
    SiteId:             Mapped[str | None]    = mapped_column(String(50), nullable=True)
    FirmwareVersion:    Mapped[str | None]    = mapped_column(String(20), nullable=True)
    CommunicationMode:  Mapped[str]           = mapped_column(String(10), nullable=False, default="MQTT")
    IsActive:           Mapped[bool]          = mapped_column(Boolean, nullable=False, default=True)
    LastSeenAt:         Mapped[datetime|None] = mapped_column(DateTime, nullable=True)
    LastIPAddress:      Mapped[str | None]    = mapped_column(String(45), nullable=True)
    CreatedAt:          Mapped[datetime]      = mapped_column(DateTime, nullable=False, default=lambda: now_ist())
    UpdatedAt:          Mapped[datetime]      = mapped_column(DateTime, nullable=False, default=lambda: now_ist(), onupdate=lambda: now_ist())

    configuration: Mapped[DeviceConfiguration | None] = relationship("DeviceConfiguration", back_populates="device", uselist=False)
    telemetry:     Mapped[list[Telemetry]]             = relationship("Telemetry",           back_populates="device")
    commands:      Mapped[list[DeviceCommand]]         = relationship("DeviceCommand",        back_populates="device")
    events:        Mapped[list[DeviceEvent]]           = relationship("DeviceEvent",          back_populates="device")


class DeviceConfiguration(Base):
    __tablename__ = "DeviceConfiguration"

    Id:               Mapped[int]        = mapped_column(Integer, primary_key=True, autoincrement=True)
    DeviceId:         Mapped[str]        = mapped_column(String(50), ForeignKey("Devices.DeviceId", onupdate="CASCADE"), nullable=False, unique=True, index=True)
    CommunicationMode:Mapped[str]        = mapped_column(String(10), nullable=False, default="MQTT")
    MqttBroker:       Mapped[str | None] = mapped_column(String(255), nullable=True)
    MqttPort:         Mapped[int | None] = mapped_column(Integer, nullable=True)
    MqttTlsEnabled:   Mapped[bool]       = mapped_column(Boolean, nullable=False, default=False)
    MqttUsername:     Mapped[str | None] = mapped_column(String(100), nullable=True)
    TcpHost:          Mapped[str | None] = mapped_column(String(255), nullable=True)
    TcpPort:          Mapped[int | None] = mapped_column(Integer, nullable=True)
    ReportingInterval:Mapped[int | None] = mapped_column(Integer, nullable=True)   # seconds
    Apn:              Mapped[str | None] = mapped_column(String(100), nullable=True)
    SlaveId:          Mapped[int | None] = mapped_column(Integer, nullable=True)
    BaudRate:         Mapped[int | None] = mapped_column(Integer, nullable=True)
    Parity:           Mapped[str | None] = mapped_column(String(5), nullable=True)
    Range:            Mapped[int | None] = mapped_column(Integer, nullable=True)
    CreatedAt:        Mapped[datetime]   = mapped_column(DateTime, nullable=False, default=lambda: now_ist())
    UpdatedAt:        Mapped[datetime]   = mapped_column(DateTime, nullable=False, default=lambda: now_ist(), onupdate=lambda: now_ist())

    device: Mapped[Device] = relationship("Device", back_populates="configuration")


# ─────────────────────────────────────────────────────────────────────────────
# Telemetry
# ─────────────────────────────────────────────────────────────────────────────

class Telemetry(Base):
    __tablename__ = "Telemetry"
    __table_args__ = (
        UniqueConstraint("DeviceId", "Timestamp", "Protocol", name="uq_telemetry_device_ts_proto"),
        Index("ix_telemetry_device_ts", "DeviceId", "Timestamp"),
        Index("ix_telemetry_site_ts",   "SiteId",   "Timestamp"),
        Index("ix_telemetry_receivedat","ReceivedAt"),
    )

    Id:              Mapped[int]         = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    DeviceId:        Mapped[str]         = mapped_column(String(50), ForeignKey("Devices.DeviceId"), nullable=False, index=True)
    SiteId:          Mapped[str | None]  = mapped_column(String(50),  nullable=True)
    Timestamp:       Mapped[datetime]    = mapped_column(DateTime,    nullable=False)   # RTU measurement time
    ReceivedAt:      Mapped[datetime]    = mapped_column(DateTime,    nullable=False, default=lambda: now_ist())
    Protocol:        Mapped[str]         = mapped_column(String(10),  nullable=False)   # MQTT | TCP
    Flow:            Mapped[float|None]  = mapped_column(Float,       nullable=True)
    FlowUnit:        Mapped[str | None]  = mapped_column(String(10),  nullable=True)
    TotalToday:      Mapped[float|None]  = mapped_column(Float,       nullable=True)
    TotalYesterday:  Mapped[float|None]  = mapped_column(Float,       nullable=True)
    SensorType:      Mapped[str | None]  = mapped_column(String(20),  nullable=True)
    SignalDbm:       Mapped[int | None]  = mapped_column(Integer,     nullable=True)
    Battery:         Mapped[float|None]  = mapped_column(Float,       nullable=True)
    FirmwareVersion: Mapped[str | None]  = mapped_column(String(20),  nullable=True)
    READ01:          Mapped[str | None]  = mapped_column(String(50),  nullable=True)
    READ02:          Mapped[str | None]  = mapped_column(String(50),  nullable=True)
    READ03:          Mapped[str | None]  = mapped_column(String(50),  nullable=True)
    READ04:          Mapped[str | None]  = mapped_column(String(50),  nullable=True)
    READ05:          Mapped[str | None]  = mapped_column(String(50),  nullable=True)
    Pressure:        Mapped[float|None]  = mapped_column(Float,       nullable=True)
    IsHistorical:    Mapped[bool]        = mapped_column(Boolean,     nullable=False, default=False)
    RawMessageId:    Mapped[int | None]  = mapped_column(BigInteger,  nullable=True)

    device: Mapped[Device] = relationship("Device", back_populates="telemetry")


# ─────────────────────────────────────────────────────────────────────────────
# Raw / Protocol message archives
# ─────────────────────────────────────────────────────────────────────────────

class RawMessage(Base):
    __tablename__ = "RawMessages"
    __table_args__ = (
        Index("ix_raw_device_ts", "DeviceId", "ReceivedAt"),
    )

    Id:           Mapped[int]        = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ReceivedAt:   Mapped[datetime]   = mapped_column(DateTime,   nullable=False, default=lambda: now_ist(), index=True)
    Protocol:     Mapped[str]        = mapped_column(String(10), nullable=False)
    DeviceId:     Mapped[str|None]   = mapped_column(String(50), nullable=True)   # may be null if unparseable
    SourceIP:     Mapped[str|None]   = mapped_column(String(45), nullable=True)
    Topic:        Mapped[str|None]   = mapped_column(String(255),nullable=True)
    Payload:      Mapped[str]        = mapped_column(Text,        nullable=False)
    IsValid:      Mapped[bool]       = mapped_column(Boolean,     nullable=False, default=True)
    ErrorMessage: Mapped[str|None]   = mapped_column(Text,        nullable=True)


class MQTTMessage(Base):
    __tablename__ = "MQTTMessages"

    Id:           Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ReceivedAt:   Mapped[datetime] = mapped_column(DateTime,   nullable=False, default=lambda: now_ist())
    Topic:        Mapped[str]      = mapped_column(String(255),nullable=False)
    DeviceId:     Mapped[str|None] = mapped_column(String(50), nullable=True)
    QoS:          Mapped[int]      = mapped_column(Integer,    nullable=False, default=1)
    Payload:      Mapped[str]      = mapped_column(Text,       nullable=False)
    Status:       Mapped[str]      = mapped_column(String(20), nullable=False, default="RECEIVED")
    RawMessageId: Mapped[int|None] = mapped_column(BigInteger, nullable=True)


class TCPMessage(Base):
    __tablename__ = "TCPMessages"

    Id:              Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ReceivedAt:      Mapped[datetime] = mapped_column(DateTime,   nullable=False, default=lambda: now_ist())
    DeviceId:        Mapped[str|None] = mapped_column(String(50), nullable=True)
    SourceIP:        Mapped[str]      = mapped_column(String(45), nullable=False)
    Payload:         Mapped[str]      = mapped_column(Text,       nullable=False)
    Acknowledgement: Mapped[str|None] = mapped_column(String(100),nullable=True)
    Status:          Mapped[str]      = mapped_column(String(20), nullable=False, default="RECEIVED")
    RawMessageId:    Mapped[int|None] = mapped_column(BigInteger, nullable=True)


# ─────────────────────────────────────────────────────────────────────────────
# Commands and Events
# ─────────────────────────────────────────────────────────────────────────────

class DeviceCommand(Base):
    __tablename__ = "DeviceCommands"

    Id:        Mapped[int]         = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    DeviceId:  Mapped[str]         = mapped_column(String(50), ForeignKey("Devices.DeviceId"), nullable=False, index=True)
    Protocol:  Mapped[str]         = mapped_column(String(10), nullable=False)
    Command:   Mapped[str]         = mapped_column(String(100),nullable=False)
    Payload:   Mapped[str|None]    = mapped_column(Text,       nullable=True)
    CreatedAt: Mapped[datetime]    = mapped_column(DateTime,   nullable=False, default=lambda: now_ist())
    SentAt:    Mapped[datetime|None]= mapped_column(DateTime,  nullable=True)
    Response:  Mapped[str|None]    = mapped_column(Text,       nullable=True)
    Status:    Mapped[str]         = mapped_column(String(20), nullable=False, default="PENDING")

    device: Mapped[Device] = relationship("Device", back_populates="commands")


class DeviceEvent(Base):
    __tablename__ = "DeviceEvents"

    Id:          Mapped[int]      = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    DeviceId:    Mapped[str]      = mapped_column(String(50), ForeignKey("Devices.DeviceId"), nullable=False, index=True)
    EventType:   Mapped[str]      = mapped_column(String(50), nullable=False)
    Description: Mapped[str|None] = mapped_column(Text,       nullable=True)
    Timestamp:   Mapped[datetime] = mapped_column(DateTime,   nullable=False, default=lambda: now_ist())
    Protocol:    Mapped[str|None] = mapped_column(String(10), nullable=True)
    Severity:    Mapped[str]      = mapped_column(String(20), nullable=False, default="INFO")
    CreatedAt:   Mapped[datetime] = mapped_column(DateTime,   nullable=False, default=lambda: now_ist())

    device: Mapped[Device] = relationship("Device", back_populates="events")
