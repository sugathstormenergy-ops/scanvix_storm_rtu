-- =============================================================================
-- Storm Energy RTU — dedicated least-privilege SQL login for the Docker services
-- PHASE A ONLY. Run by deploy.ps1 -InitDatabase (as a Windows sysadmin via -E),
-- never automatically. Requires:
--   * SQL Server in Mixed Mode (SERVERPROPERTY('IsIntegratedSecurityOnly') = 0)
--   * database STORM_ENERGY_RTU already created by 001..004
-- sqlcmd scripting variables (supplied from the process environment by
-- deploy.ps1 — the password never appears on a command line or in Git):
--   STORM_APP_LOGIN     e.g. storm_rtu_app
--   STORM_APP_PASSWORD  generated into the git-ignored .env
-- NOTE: never write the sqlcmd variable-reference syntax for the password in a
-- comment: sqlcmd expands variables inside comments too, which would send the
-- password to the server as plain batch text. It is referenced exactly once,
-- in the CREATE LOGIN statement below.
-- Idempotent: never alters or drops an existing login/user; only creates what
-- is missing and (re)applies the same GRANTs. Does not touch any other database.
-- Permissions = exactly what the application uses: SELECT/INSERT/UPDATE on dbo.
-- (No DELETE, no DDL, no server roles.)
-- =============================================================================
:on error exit
SET NOCOUNT ON;
USE master;
GO

IF CAST(SERVERPROPERTY('IsIntegratedSecurityOnly') AS int) = 1
    THROW 50001, 'SQL Server is in Windows-Authentication-only mode. SQL logins cannot sign in. Aborting (no changes made).', 1;
IF DB_ID(N'STORM_ENERGY_RTU') IS NULL
    THROW 50002, 'Database STORM_ENERGY_RTU does not exist. Run 001..004 first. Aborting (no changes made).', 1;
GO

IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'$(STORM_APP_LOGIN)')
BEGIN
    CREATE LOGIN [$(STORM_APP_LOGIN)]
        WITH PASSWORD = N'$(STORM_APP_PASSWORD)',
             DEFAULT_DATABASE = [STORM_ENERGY_RTU],
             CHECK_POLICY = ON,
             CHECK_EXPIRATION = OFF;
    PRINT 'Login $(STORM_APP_LOGIN) created.';
END
ELSE
    PRINT 'Login $(STORM_APP_LOGIN) already exists — left unchanged.';
GO

USE STORM_ENERGY_RTU;
GO

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'$(STORM_APP_LOGIN)')
BEGIN
    CREATE USER [$(STORM_APP_LOGIN)] FOR LOGIN [$(STORM_APP_LOGIN)] WITH DEFAULT_SCHEMA = dbo;
    PRINT 'User $(STORM_APP_LOGIN) created in STORM_ENERGY_RTU.';
END
ELSE
    PRINT 'User $(STORM_APP_LOGIN) already exists in STORM_ENERGY_RTU — left unchanged.';

GRANT SELECT, INSERT, UPDATE ON SCHEMA::dbo TO [$(STORM_APP_LOGIN)];
PRINT 'Granted SELECT, INSERT, UPDATE on schema dbo to $(STORM_APP_LOGIN).';
-- Protocol Test Log retention: DELETE on the diagnostics table ONLY (never schema-wide).
IF OBJECT_ID(N'dbo.ProtocolDiagnosticLogs', N'U') IS NOT NULL
BEGIN
    GRANT DELETE ON OBJECT::dbo.ProtocolDiagnosticLogs TO [$(STORM_APP_LOGIN)];
    PRINT 'Granted DELETE on dbo.ProtocolDiagnosticLogs (only) to $(STORM_APP_LOGIN).';
END
GO
