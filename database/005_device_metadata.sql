-- =============================================================================
-- Storm Energy RTU Platform - 005: Device display / GIS metadata (ADDITIVE)
-- Run against: STORM_ENERGY_RTU only (never any other database).
--
-- Adds three NULLABLE columns to dbo.Devices and four CHECK constraints:
--   Name       NVARCHAR(100) NULL
--   Latitude   DECIMAL(9,6)  NULL    -90..90
--   Longitude  DECIMAL(9,6)  NULL   -180..180
--   Latitude/Longitude are both NULL or both set; (0,0) is rejected.
-- NULL coordinates mean "No location assigned". Values are populated later from
-- the meter register; this script writes NO data.
--
-- Idempotent: every change is guarded (COL_LENGTH / sys.check_constraints), so
-- re-running is a no-op. No DROP, DELETE, UPDATE or TRUNCATE. Adding a nullable
-- column is a metadata-only change on SQL Server (existing rows are not rewritten).
-- The CHECK constraints are created WITH CHECK: they validate existing rows, which
-- all have NULL coordinates at this point, so they cannot fail on existing data.
-- Fresh installs get the same definitions from 002_tables.sql.
-- =============================================================================
:on error exit
SET NOCOUNT ON;
GO
IF DB_ID(N'STORM_ENERGY_RTU') IS NULL
    THROW 50051, 'Database STORM_ENERGY_RTU does not exist. Run 001..004 first. No changes made.', 1;
GO
USE STORM_ENERGY_RTU;
GO
IF OBJECT_ID(N'dbo.Devices', N'U') IS NULL
    THROW 50052, 'Table dbo.Devices does not exist in STORM_ENERGY_RTU. No changes made.', 1;
GO

IF COL_LENGTH(N'dbo.Devices', N'Name') IS NULL
BEGIN
    ALTER TABLE dbo.Devices ADD Name NVARCHAR(100) NULL;
    PRINT 'Column Devices.Name added.';
END
ELSE PRINT 'Column Devices.Name already present - skipped.';
GO
IF COL_LENGTH(N'dbo.Devices', N'Latitude') IS NULL
BEGIN
    ALTER TABLE dbo.Devices ADD Latitude DECIMAL(9,6) NULL;
    PRINT 'Column Devices.Latitude added.';
END
ELSE PRINT 'Column Devices.Latitude already present - skipped.';
GO
IF COL_LENGTH(N'dbo.Devices', N'Longitude') IS NULL
BEGIN
    ALTER TABLE dbo.Devices ADD Longitude DECIMAL(9,6) NULL;
    PRINT 'Column Devices.Longitude added.';
END
ELSE PRINT 'Column Devices.Longitude already present - skipped.';
GO

-- CHECK constraints are added in separate batches: the new columns must exist at
-- compile time of the batch that references them.
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = N'CK_Devices_Latitude' AND parent_object_id = OBJECT_ID(N'dbo.Devices'))
BEGIN
    ALTER TABLE dbo.Devices WITH CHECK ADD CONSTRAINT CK_Devices_Latitude CHECK (Latitude IS NULL OR (Latitude BETWEEN -90 AND 90));
    PRINT 'Constraint CK_Devices_Latitude added.';
END
GO
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = N'CK_Devices_Longitude' AND parent_object_id = OBJECT_ID(N'dbo.Devices'))
BEGIN
    ALTER TABLE dbo.Devices WITH CHECK ADD CONSTRAINT CK_Devices_Longitude CHECK (Longitude IS NULL OR (Longitude BETWEEN -180 AND 180));
    PRINT 'Constraint CK_Devices_Longitude added.';
END
GO
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = N'CK_Devices_LatLngPair' AND parent_object_id = OBJECT_ID(N'dbo.Devices'))
BEGIN
    ALTER TABLE dbo.Devices WITH CHECK ADD CONSTRAINT CK_Devices_LatLngPair CHECK ((Latitude IS NULL AND Longitude IS NULL) OR (Latitude IS NOT NULL AND Longitude IS NOT NULL));
    PRINT 'Constraint CK_Devices_LatLngPair added.';
END
GO
IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = N'CK_Devices_NotNullIsland' AND parent_object_id = OBJECT_ID(N'dbo.Devices'))
BEGIN
    ALTER TABLE dbo.Devices WITH CHECK ADD CONSTRAINT CK_Devices_NotNullIsland CHECK (NOT (Latitude = 0 AND Longitude = 0));
    PRINT 'Constraint CK_Devices_NotNullIsland added.';
END
GO
PRINT '005_device_metadata applied (idempotent).';
GO
