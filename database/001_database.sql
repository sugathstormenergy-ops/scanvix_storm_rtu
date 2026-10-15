-- =============================================================================
-- Storm Energy RTU Platform — 001: Create database
-- Run as: sa or sysadmin equivalent
-- Target: Microsoft SQL Server 2017+
-- =============================================================================

USE master;
GO

IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = N'STORM_ENERGY_RTU')
BEGIN
    CREATE DATABASE STORM_ENERGY_RTU
        COLLATE SQL_Latin1_General_CP1_CI_AS;
    PRINT 'Database STORM_ENERGY_RTU created.';
END
ELSE
    PRINT 'Database STORM_ENERGY_RTU already exists — skipped.';
GO

-- Ensure READ COMMITTED SNAPSHOT isolation is enabled for better concurrency.
-- Idempotent: the ALTER runs only when the setting is currently OFF, so re-running
-- this script against an existing database is a no-op (no exclusive-access wait).
IF EXISTS (SELECT 1 FROM sys.databases
           WHERE name = N'STORM_ENERGY_RTU' AND is_read_committed_snapshot_on = 0)
BEGIN
    ALTER DATABASE STORM_ENERGY_RTU SET READ_COMMITTED_SNAPSHOT ON;
    PRINT 'READ_COMMITTED_SNAPSHOT enabled on STORM_ENERGY_RTU.';
END
ELSE
    PRINT 'READ_COMMITTED_SNAPSHOT already ON (or database absent) - skipped.';
GO
