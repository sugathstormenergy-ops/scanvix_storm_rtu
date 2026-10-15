-- =============================================================================
-- Storm Energy RTU Platform - 006: Protocol Test Log (diagnostics) (ADDITIVE)
-- Run against: STORM_ENERGY_RTU only (never any other database).
--
-- Creates ONE new, self-contained table dbo.ProtocolDiagnosticLogs (no foreign keys,
-- so unknown senders can be logged without creating device registrations), its
-- CHECK constraints and two indexes, and grants the application login DELETE on
-- THIS TABLE ONLY so the 30-day retention task can purge old diagnostic rows.
-- The login keeps SELECT/INSERT/UPDATE on dbo (no DELETE on any other table).
--
-- Idempotent: every change is guarded (sys.tables / sys.indexes / principal lookup),
-- so re-running is a no-op. No DROP, DELETE, UPDATE or TRUNCATE. No existing table
-- is altered. Fresh installs get the table from 002/003 and the grant from
-- security/create_app_login.sql.
-- Scripting variable: STORM_APP_LOGIN (the application SQL login, from .env
-- SQL_USERNAME), supplied by deploy.ps1 -MigrateDatabase via the environment.
-- =============================================================================
:on error exit
SET NOCOUNT ON;
GO
IF DB_ID(N'STORM_ENERGY_RTU') IS NULL
    THROW 50061, 'Database STORM_ENERGY_RTU does not exist. Run 001..004 first. No changes made.', 1;
GO
USE STORM_ENERGY_RTU;
GO
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = N'ProtocolDiagnosticLogs' AND schema_id = SCHEMA_ID(N'dbo'))
BEGIN
    CREATE TABLE dbo.ProtocolDiagnosticLogs (
        Id               BIGINT         NOT NULL IDENTITY(1,1),
        ReceivedAt       DATETIME2      NOT NULL,
        Protocol         NVARCHAR(10)   NOT NULL,
        Status           NVARCHAR(20)   NOT NULL,
        Outcome          NVARCHAR(30)       NULL,
        SourceIP         NVARCHAR(45)       NULL,
        DeviceId         NVARCHAR(50)       NULL,
        DeviceName       NVARCHAR(100)      NULL,
        IMEI             NVARCHAR(20)       NULL,
        SiteId           NVARCHAR(50)       NULL,
        IsRegistered     BIT            NOT NULL DEFAULT 0,
        Topic            NVARCHAR(255)      NULL,
        QoS              INT                NULL,
        Payload          NVARCHAR(4000) NOT NULL,
        PayloadEncoding  NVARCHAR(10)   NOT NULL,
        PayloadBytes     INT            NOT NULL,
        PayloadTruncated BIT            NOT NULL DEFAULT 0,
        ErrorReason      NVARCHAR(500)      NULL,
        CreatedAt        DATETIME2      NOT NULL,
        CONSTRAINT PK_ProtocolDiagnosticLogs PRIMARY KEY CLUSTERED (Id),
        CONSTRAINT CK_ProtocolDiagnosticLogs_Protocol CHECK (Protocol IN (N'TCP', N'MQTT')),
        CONSTRAINT CK_ProtocolDiagnosticLogs_Status   CHECK (Status IN (N'VALID', N'INVALID', N'UNKNOWN_DEVICE')),
        CONSTRAINT CK_ProtocolDiagnosticLogs_Encoding CHECK (PayloadEncoding IN (N'TEXT', N'HEX'))
    );
    PRINT 'Table ProtocolDiagnosticLogs created.';
END
ELSE PRINT 'Table ProtocolDiagnosticLogs already present - skipped.';
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_ProtocolDiagnosticLogs_Protocol_ReceivedAt' AND object_id = OBJECT_ID(N'dbo.ProtocolDiagnosticLogs'))
BEGIN
    CREATE NONCLUSTERED INDEX IX_ProtocolDiagnosticLogs_Protocol_ReceivedAt
        ON dbo.ProtocolDiagnosticLogs (Protocol, ReceivedAt DESC, Id DESC);
    PRINT 'Index IX_ProtocolDiagnosticLogs_Protocol_ReceivedAt created.';
END
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_ProtocolDiagnosticLogs_ReceivedAt' AND object_id = OBJECT_ID(N'dbo.ProtocolDiagnosticLogs'))
BEGIN
    CREATE NONCLUSTERED INDEX IX_ProtocolDiagnosticLogs_ReceivedAt
        ON dbo.ProtocolDiagnosticLogs (ReceivedAt);
    PRINT 'Index IX_ProtocolDiagnosticLogs_ReceivedAt created.';
END
GO
-- Retention purge permission: DELETE on this one table only (object-level grant).
IF EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'$(STORM_APP_LOGIN)' AND type = 'S')
BEGIN
    GRANT DELETE ON OBJECT::dbo.ProtocolDiagnosticLogs TO [$(STORM_APP_LOGIN)];
    PRINT 'Granted DELETE on dbo.ProtocolDiagnosticLogs (only) to $(STORM_APP_LOGIN).';
END
ELSE PRINT 'Database user $(STORM_APP_LOGIN) not present yet - grant is applied by security/create_app_login.sql.';
GO
PRINT '006_protocol_diagnostics applied (idempotent).';
