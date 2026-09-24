-- =============================================================================
-- Storm Energy RTU Platform — 004: Additional constraints and defaults
-- =============================================================================
USE STORM_ENERGY_RTU;
GO

-- Ensure Telemetry.Flow is not absurdly negative (sensor error guard)
-- Threshold agreed with Storm: -9999 permits flagged negative readings
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_Telemetry_Flow')
    ALTER TABLE dbo.Telemetry
        ADD CONSTRAINT CK_Telemetry_Flow CHECK (Flow IS NULL OR Flow >= -9999);
GO

-- Ensure Protocol is consistent
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_MQTT_Status')
    ALTER TABLE dbo.MQTTMessages
        ADD CONSTRAINT CK_MQTT_Status CHECK (Status IN ('RECEIVED','PROCESSED','INVALID','DUPLICATE'));
GO

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_TCP_Status')
    ALTER TABLE dbo.TCPMessages
        ADD CONSTRAINT CK_TCP_Status CHECK (Status IN ('RECEIVED','PROCESSED','INVALID','DUPLICATE'));
GO

PRINT 'Constraints applied.';
GO
