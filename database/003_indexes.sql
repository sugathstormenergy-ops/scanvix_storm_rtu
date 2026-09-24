-- =============================================================================
-- Storm Energy RTU Platform — 003: Indexes
-- =============================================================================
USE STORM_ENERGY_RTU;
GO

-- Devices
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UQ_Devices_DeviceId' AND object_id = OBJECT_ID('dbo.Devices'))
    ALTER TABLE dbo.Devices ADD CONSTRAINT UQ_Devices_DeviceId UNIQUE (DeviceId);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UQ_Devices_IMEI' AND object_id = OBJECT_ID('dbo.Devices'))
    ALTER TABLE dbo.Devices ADD CONSTRAINT UQ_Devices_IMEI UNIQUE (IMEI);
GO

-- DeviceConfiguration
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UQ_DevCfg_DeviceId' AND object_id = OBJECT_ID('dbo.DeviceConfiguration'))
    ALTER TABLE dbo.DeviceConfiguration ADD CONSTRAINT UQ_DevCfg_DeviceId UNIQUE (DeviceId);
GO

-- Telemetry — deduplication key
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UQ_Telemetry_Dedup' AND object_id = OBJECT_ID('dbo.Telemetry'))
    ALTER TABLE dbo.Telemetry ADD CONSTRAINT UQ_Telemetry_Dedup UNIQUE (DeviceId, Timestamp, Protocol);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Telemetry_Device_Ts' AND object_id = OBJECT_ID('dbo.Telemetry'))
    CREATE INDEX IX_Telemetry_Device_Ts  ON dbo.Telemetry (DeviceId, Timestamp DESC);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Telemetry_Site_Ts' AND object_id = OBJECT_ID('dbo.Telemetry'))
    CREATE INDEX IX_Telemetry_Site_Ts    ON dbo.Telemetry (SiteId, Timestamp DESC);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Telemetry_ReceivedAt' AND object_id = OBJECT_ID('dbo.Telemetry'))
    CREATE INDEX IX_Telemetry_ReceivedAt ON dbo.Telemetry (ReceivedAt DESC);
GO

-- RawMessages
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Raw_Device_Ts' AND object_id = OBJECT_ID('dbo.RawMessages'))
    CREATE INDEX IX_Raw_Device_Ts ON dbo.RawMessages (DeviceId, ReceivedAt DESC);
GO

-- DeviceEvents
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_DevEvt_Device_Ts' AND object_id = OBJECT_ID('dbo.DeviceEvents'))
    CREATE INDEX IX_DevEvt_Device_Ts ON dbo.DeviceEvents (DeviceId, Timestamp DESC);
GO

-- DeviceCommands
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_DevCmd_Device_Status' AND object_id = OBJECT_ID('dbo.DeviceCommands'))
    CREATE INDEX IX_DevCmd_Device_Status ON dbo.DeviceCommands (DeviceId, Status);
GO

PRINT 'Indexes applied.';
GO
