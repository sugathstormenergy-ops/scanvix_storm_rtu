-- =============================================================================
-- Storm Energy RTU Platform — 002: Create tables
-- Run against: STORM_ENERGY_RTU
-- =============================================================================

USE STORM_ENERGY_RTU;
GO

-- ── Devices ──────────────────────────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'Devices')
BEGIN
    CREATE TABLE dbo.Devices (
        Id                  INT           NOT NULL IDENTITY(1,1) PRIMARY KEY,
        DeviceId            NVARCHAR(50)  NOT NULL,
        IMEI                NVARCHAR(20)  NOT NULL,
        SiteId              NVARCHAR(50)      NULL,
        FirmwareVersion     NVARCHAR(20)      NULL,
        CommunicationMode   NVARCHAR(10)  NOT NULL DEFAULT 'MQTT'
                            CONSTRAINT CK_Devices_CommMode CHECK (CommunicationMode IN ('MQTT','TCP','BOTH')),
        IsActive            BIT           NOT NULL DEFAULT 1,
        LastSeenAt          DATETIME2         NULL,
        LastIPAddress       NVARCHAR(45)      NULL,
        CreatedAt           DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        UpdatedAt           DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
    );
    PRINT 'Table Devices created.';
END
GO

-- Establish uniqueness on Devices.DeviceId BEFORE any table below declares a
-- FOREIGN KEY REFERENCES dbo.Devices(DeviceId). SQL Server requires the
-- referenced column to already be covered by a PK/UNIQUE constraint at
-- FK-creation time; without this block here, CREATE TABLE for
-- DeviceConfiguration / Telemetry / DeviceCommands / DeviceEvents fails
-- (Msg 1776) on a first-time deployment. This exact statement is also
-- idempotently created later in 003_indexes.sql; both copies are
-- IF NOT EXISTS-guarded so running either or both, in either order, is safe.
IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'UQ_Devices_DeviceId'
      AND object_id = OBJECT_ID('dbo.Devices')
)
    ALTER TABLE dbo.Devices
    ADD CONSTRAINT UQ_Devices_DeviceId UNIQUE (DeviceId);
GO

-- ── DeviceConfiguration ───────────────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'DeviceConfiguration')
BEGIN
    CREATE TABLE dbo.DeviceConfiguration (
        Id                  INT           NOT NULL IDENTITY(1,1) PRIMARY KEY,
        DeviceId            NVARCHAR(50)  NOT NULL
                            CONSTRAINT FK_DevCfg_Device FOREIGN KEY REFERENCES dbo.Devices(DeviceId) ON UPDATE CASCADE,
        CommunicationMode   NVARCHAR(10)  NOT NULL DEFAULT 'MQTT',
        MqttBroker          NVARCHAR(255)     NULL,
        MqttPort            INT               NULL,
        MqttTlsEnabled      BIT           NOT NULL DEFAULT 0,
        MqttUsername        NVARCHAR(100)     NULL,
        TcpHost             NVARCHAR(255)     NULL,
        TcpPort             INT               NULL,
        ReportingInterval   INT               NULL,   -- seconds
        Apn                 NVARCHAR(100)     NULL,
        SlaveId             INT               NULL,
        BaudRate            INT               NULL,
        Parity              NVARCHAR(5)       NULL,
        Range               INT               NULL,
        CreatedAt           DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        UpdatedAt           DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
    );
    PRINT 'Table DeviceConfiguration created.';
END
GO

-- ── Telemetry ──────────────────────────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'Telemetry')
BEGIN
    CREATE TABLE dbo.Telemetry (
        Id              BIGINT        NOT NULL IDENTITY(1,1) PRIMARY KEY,
        DeviceId        NVARCHAR(50)  NOT NULL
                        CONSTRAINT FK_Telemetry_Device FOREIGN KEY REFERENCES dbo.Devices(DeviceId),
        SiteId          NVARCHAR(50)      NULL,
        Timestamp       DATETIME2     NOT NULL,
        ReceivedAt      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        Protocol        NVARCHAR(10)  NOT NULL
                        CONSTRAINT CK_Telemetry_Proto CHECK (Protocol IN ('MQTT','TCP')),
        Flow            FLOAT             NULL,
        FlowUnit        NVARCHAR(10)      NULL,
        TotalToday      FLOAT             NULL,
        TotalYesterday  FLOAT             NULL,
        SensorType      NVARCHAR(20)      NULL,
        SignalDbm       INT               NULL,
        Battery         FLOAT             NULL,
        FirmwareVersion NVARCHAR(20)      NULL,
        READ01          NVARCHAR(50)      NULL,
        READ02          NVARCHAR(50)      NULL,
        READ03          NVARCHAR(50)      NULL,
        READ04          NVARCHAR(50)      NULL,
        READ05          NVARCHAR(50)      NULL,
        Pressure        FLOAT             NULL,
        IsHistorical    BIT           NOT NULL DEFAULT 0,
        RawMessageId    BIGINT            NULL
    );
    PRINT 'Table Telemetry created.';
END
GO

-- ── RawMessages ────────────────────────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'RawMessages')
BEGIN
    CREATE TABLE dbo.RawMessages (
        Id              BIGINT        NOT NULL IDENTITY(1,1) PRIMARY KEY,
        ReceivedAt      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        Protocol        NVARCHAR(10)  NOT NULL,
        DeviceId        NVARCHAR(50)      NULL,
        SourceIP        NVARCHAR(45)      NULL,
        Topic           NVARCHAR(255)     NULL,
        Payload         NVARCHAR(MAX) NOT NULL,
        IsValid         BIT           NOT NULL DEFAULT 1,
        ErrorMessage    NVARCHAR(MAX)     NULL
    );
    PRINT 'Table RawMessages created.';
END
GO

-- ── MQTTMessages ───────────────────────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'MQTTMessages')
BEGIN
    CREATE TABLE dbo.MQTTMessages (
        Id              BIGINT        NOT NULL IDENTITY(1,1) PRIMARY KEY,
        ReceivedAt      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        Topic           NVARCHAR(255) NOT NULL,
        DeviceId        NVARCHAR(50)      NULL,
        QoS             INT           NOT NULL DEFAULT 1,
        Payload         NVARCHAR(MAX) NOT NULL,
        Status          NVARCHAR(20)  NOT NULL DEFAULT 'RECEIVED',
        RawMessageId    BIGINT            NULL
    );
    PRINT 'Table MQTTMessages created.';
END
GO

-- ── TCPMessages ────────────────────────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'TCPMessages')
BEGIN
    CREATE TABLE dbo.TCPMessages (
        Id              BIGINT        NOT NULL IDENTITY(1,1) PRIMARY KEY,
        ReceivedAt      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        DeviceId        NVARCHAR(50)      NULL,
        SourceIP        NVARCHAR(45)  NOT NULL,
        Payload         NVARCHAR(MAX) NOT NULL,
        Acknowledgement NVARCHAR(100)     NULL,
        Status          NVARCHAR(20)  NOT NULL DEFAULT 'RECEIVED',
        RawMessageId    BIGINT            NULL
    );
    PRINT 'Table TCPMessages created.';
END
GO

-- ── DeviceCommands ─────────────────────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'DeviceCommands')
BEGIN
    CREATE TABLE dbo.DeviceCommands (
        Id          BIGINT        NOT NULL IDENTITY(1,1) PRIMARY KEY,
        DeviceId    NVARCHAR(50)  NOT NULL
                    CONSTRAINT FK_DevCmd_Device FOREIGN KEY REFERENCES dbo.Devices(DeviceId),
        Protocol    NVARCHAR(10)  NOT NULL,
        Command     NVARCHAR(100) NOT NULL,
        Payload     NVARCHAR(MAX)     NULL,
        CreatedAt   DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        SentAt      DATETIME2         NULL,
        Response    NVARCHAR(MAX)     NULL,
        Status      NVARCHAR(20)  NOT NULL DEFAULT 'PENDING'
                    CONSTRAINT CK_DevCmd_Status CHECK (Status IN ('PENDING','SENT','ACKED','FAILED','EXPIRED'))
    );
    PRINT 'Table DeviceCommands created.';
END
GO

-- ── DeviceEvents ───────────────────────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'DeviceEvents')
BEGIN
    CREATE TABLE dbo.DeviceEvents (
        Id          BIGINT        NOT NULL IDENTITY(1,1) PRIMARY KEY,
        DeviceId    NVARCHAR(50)  NOT NULL
                    CONSTRAINT FK_DevEvt_Device FOREIGN KEY REFERENCES dbo.Devices(DeviceId),
        EventType   NVARCHAR(50)  NOT NULL,
        Description NVARCHAR(MAX)     NULL,
        Timestamp   DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        Protocol    NVARCHAR(10)      NULL,
        Severity    NVARCHAR(20)  NOT NULL DEFAULT 'INFO'
                    CONSTRAINT CK_DevEvt_Severity CHECK (Severity IN ('INFO','WARNING','ERROR','CRITICAL')),
        CreatedAt   DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
    );
    PRINT 'Table DeviceEvents created.';
END
GO
