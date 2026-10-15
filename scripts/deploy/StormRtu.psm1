# =============================================================================
# Storm Energy RTU - shared functions for deploy.ps1 / update.ps1 / stop.ps1 /
# status.ps1 / health-check.ps1 / backup.ps1  (Windows PowerShell 5.1+)
#
# SAFETY CONTRACT
#   * Never stops, reconfigures or kills anything that is not part of the
#     "storm-rtu" Docker Compose project.
#   * SQL Server access in this module is READ-ONLY (SELECT via sqlcmd -E),
#     except Invoke-StormDatabaseInit, which runs only when deploy.ps1 is
#     called with -InitDatabase and never drops/alters/deletes anything.
#   * Never touches the "Storm" database, IIS, the host Mosquitto service,
#     the PH Flowmeter services, the firewall or the router.
#   * Never removes Docker volumes.
# =============================================================================
Set-StrictMode -Version 2.0

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script:LogFile = $null
$script:ComposeProject = 'storm-rtu'
$script:Services = @('mosquitto', 'storm-api', 'storm-tcp', 'storm-frontend', 'reverse-proxy')
# Base schema (created by -InitDatabase on a fresh server) and ordered, additive, idempotent
# migrations for an EXISTING database (applied only by deploy.ps1 -MigrateDatabase).
$script:SchemaFiles = @('002_tables.sql', '003_indexes.sql', '004_constraints.sql')
$script:MigrationFiles = @('005_device_metadata.sql', '006_protocol_diagnostics.sql')

function Get-StormRepoRoot { return $script:RepoRoot }

# ----------------------------------------------------------------------------- logging
function Initialize-StormLog {
    param([Parameter(Mandatory)][string]$Name)
    $dir = Join-Path $script:RepoRoot '.local\logs'
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $script:LogFile = Join-Path $dir ("{0}-{1}.log" -f $Name, (Get-Date -Format 'yyyyMMdd-HHmmss'))
    Set-Content -Path $script:LogFile -Value ("# {0} started {1} on {2} by {3}" -f $Name, (Get-Date -Format o), $env:COMPUTERNAME, $env:USERNAME) -Encoding UTF8
    return $script:LogFile
}

function Write-StormLog {
    param([string]$Message = '', [ValidateSet('INFO', 'OK', 'WARN', 'FAIL', 'STEP', 'DETAIL')][string]$Level = 'INFO')
    $color = @{ INFO = 'Gray'; OK = 'Green'; WARN = 'Yellow'; FAIL = 'Red'; STEP = 'Cyan'; DETAIL = 'DarkGray' }[$Level]
    $prefix = @{ INFO = '      '; OK = '  OK  '; WARN = ' WARN '; FAIL = ' FAIL '; STEP = '>>>   '; DETAIL = '      ' }[$Level]
    $line = "{0}{1}" -f $prefix, $Message
    Write-Host $line -ForegroundColor $color
    if ($script:LogFile) { Add-Content -Path $script:LogFile -Value ("{0} [{1}] {2}" -f (Get-Date -Format 'HH:mm:ss'), $Level, $Message) -Encoding UTF8 }
}

function Write-StormStep {
    param([int]$Number, [string]$Title)
    Write-StormLog '' 'INFO'
    Write-StormLog ("[{0:00}] {1}" -f $Number, $Title) 'STEP'
}

# ----------------------------------------------------------------------------- native commands
function Invoke-StormNative {
    <#
      Runs a native command, streams every output line (stdout+stderr) to the
      console and the log, and returns an object with ExitCode and Output.
    #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [switch]$Quiet
    )
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $lines = New-Object System.Collections.Generic.List[string]
    try {
        & $FilePath @ArgumentList 2>&1 | ForEach-Object {
            $text = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" }
            $lines.Add($text)
            if (-not $Quiet) { Write-Host "        $text" -ForegroundColor DarkGray }
            if ($script:LogFile) { Add-Content -Path $script:LogFile -Value "        $text" -Encoding UTF8 }
        }
        $code = $LASTEXITCODE
    } catch {
        $lines.Add($_.Exception.Message)
        $code = 9009
    } finally {
        $ErrorActionPreference = $saved
    }
    if ($null -eq $code) { $code = 0 }
    return [pscustomobject]@{ ExitCode = [int]$code; Output = ($lines -join "`n") }
}

function Invoke-StormCompose {
    param([string[]]$ArgumentList, [switch]$Quiet)
    Push-Location $script:RepoRoot
    try { return Invoke-StormNative -FilePath 'docker' -ArgumentList (@('compose') + $ArgumentList) -Quiet:$Quiet }
    finally { Pop-Location }
}

# ----------------------------------------------------------------------------- .env handling
function Read-StormDotEnv {
    param([string]$Path = (Join-Path $script:RepoRoot '.env'))
    $map = @{}
    if (-not (Test-Path $Path)) { return $map }
    foreach ($raw in Get-Content -Path $Path) {
        $line = $raw.Trim()
        if ($line -eq '' -or $line.StartsWith('#')) { continue }
        $idx = $line.IndexOf('=')
        if ($idx -lt 1) { continue }
        $key = $line.Substring(0, $idx).Trim()
        $val = $line.Substring($idx + 1).Trim()
        if ($val.Length -ge 2 -and (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'")))) {
            $val = $val.Substring(1, $val.Length - 2)
        }
        $map[$key] = $val
    }
    return $map
}

function Get-StormEnvValue {
    param([hashtable]$Env, [string]$Key, [string]$Default = '')
    if ($Env.ContainsKey($Key) -and $Env[$Key] -ne '') { return $Env[$Key] }
    return $Default
}

function New-StormSecret {
    # Alphanumeric only: safe in .env, docker compose interpolation, ODBC
    # connection strings, sqlcmd variables and mosquitto_passwd. Always mixes
    # upper/lower/digit so SQL Server CHECK_POLICY complexity is satisfied.
    param([int]$Length = 32)
    $upper = 'ABCDEFGHJKLMNPQRSTUVWXYZ'; $lower = 'abcdefghijkmnopqrstuvwxyz'; $digit = '23456789'
    $all = $upper + $lower + $digit
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    $bytes = New-Object byte[] ($Length)
    $rng.GetBytes($bytes)
    $chars = for ($i = 0; $i -lt $Length; $i++) { $all[$bytes[$i] % $all.Length] }
    $chars[0] = $upper[$bytes[0] % $upper.Length]
    $chars[1] = $lower[$bytes[1] % $lower.Length]
    $chars[2] = $digit[$bytes[2] % $digit.Length]
    return (-join $chars)
}

function Initialize-StormDotEnv {
    <#
      Creates .env from .env.example on first run and replaces every
      __GENERATE__ placeholder with a random secret. Existing values are never
      overwritten. Returns the list of generated keys (names only).
    #>
    $envPath = Join-Path $script:RepoRoot '.env'
    $examplePath = Join-Path $script:RepoRoot '.env.example'
    $created = $false
    if (-not (Test-Path $envPath)) {
        if (-not (Test-Path $examplePath)) { throw ".env.example not found" }
        Copy-Item -Path $examplePath -Destination $envPath
        $created = $true
    }
    $lines = Get-Content -Path $envPath
    $generated = @()
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*([A-Z0-9_]+)\s*=\s*__GENERATE__\s*$') {
            $key = $Matches[1]
            $len = if ($key -eq 'API_SECRET_KEY') { 64 } else { 32 }
            $lines[$i] = "{0}={1}" -f $key, (New-StormSecret -Length $len)
            $generated += $key
        }
    }
    if ($generated.Count -gt 0 -or $created) {
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllLines($envPath, [string[]]$lines, $utf8NoBom)
    }
    return [pscustomobject]@{ Created = $created; Generated = $generated; Path = $envPath }
}

# ----------------------------------------------------------------------------- network helpers
function Test-StormTcpPort {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 3000)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($iar)
        return $true
    } catch { return $false }
    finally { $client.Close() }
}

function Get-StormPortListener {
    param([int]$Port)
    $conns = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    foreach ($c in $conns) {
        $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        [pscustomobject]@{
            Port    = $Port
            Address = $c.LocalAddress
            Pid     = $c.OwningProcess
            Process = if ($p) { $p.ProcessName } else { '?' }
        }
    }
}

function Invoke-StormHttp {
    <# Uses curl.exe (ships with Windows 10/11). Returns StatusCode + Body. #>
    param([string]$Url, [switch]$Insecure, [int]$TimeoutSec = 10, [string]$Resolve = '', [switch]$RevokeBestEffort)
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        $curlArgs = @('-s', '-S', '-o', $tmp, '-w', '%{http_code}', '--max-time', "$TimeoutSec")
        if ($Insecure) { $curlArgs += '-k' }
        # --resolve host:port:ip  -> connect to ip but validate the certificate for host (SNI + name check)
        if ($Resolve) { $curlArgs += @('--resolve', $Resolve) }
        # Windows curl (Schannel) fails closed when a CRL/OCSP endpoint is unreachable; best-effort keeps
        # full chain + hostname validation but tolerates an unreachable revocation server.
        if ($RevokeBestEffort) { $curlArgs += '--ssl-revoke-best-effort' }
        $curlArgs += $Url
        $saved = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        $code = & curl.exe @curlArgs 2>$null
        $ErrorActionPreference = $saved
        $body = if (Test-Path $tmp) { Get-Content -Path $tmp -Raw -ErrorAction SilentlyContinue } else { '' }
        $status = 0
        [void][int]::TryParse(("$code").Trim(), [ref]$status)
        return [pscustomobject]@{ StatusCode = $status; Body = $body }
    } finally { Remove-Item -Path $tmp -Force -ErrorAction SilentlyContinue }
}

function Get-StormHttpHeader {
    param([string]$Url, [string]$Name)
    $saved = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $lines = & curl.exe -s -k -D - -o NUL --max-time 10 $Url 2>$null
    $ErrorActionPreference = $saved
    foreach ($l in @($lines)) { if ("$l" -match "^$([regex]::Escape($Name)):\s*(.*)$") { return $Matches[1].Trim() } }
    return ''
}

function Get-StormTlsCertificate {
    <# Returns the certificate the server presents (no validation). -ConnectTo sets the IP; HostName is sent as SNI. #>
    param([string]$HostName, [int]$Port, [string]$ConnectTo = '')
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect($(if ($ConnectTo) { $ConnectTo } else { $HostName }), $Port)
        $callback = [System.Net.Security.RemoteCertificateValidationCallback] { param($s, $c, $ch, $e) return $true }
        $ssl = New-Object System.Net.Security.SslStream($client.GetStream(), $false, $callback)
        $ssl.AuthenticateAsClient($HostName)
        $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($ssl.RemoteCertificate)
        $result = [pscustomobject]@{ Subject = $cert.Subject; Issuer = $cert.Issuer; NotAfter = $cert.NotAfter; Protocol = "$($ssl.SslProtocol)" }
        $ssl.Dispose()
        return $result
    } catch { return $null }
    finally { $client.Close() }
}

function Test-StormTlsMaterial {
    <#
      Validates reverse-proxy TLS files WITHOUT modifying or copying them: the
      certificate directory is mounted READ-ONLY into a throwaway alpine container
      running scripts/deploy/tls-check.sh. Returns a hashtable of KEY=VALUE results
      (SUBJECT, ISSUER, NOTAFTER, SAN, CHAIN_CERTS, EXPIRED, EXPIRES_14D, HOST_MATCH,
      KEY_MATCH, CHAIN_VERIFY) plus Error. Private key material is never printed.
    #>
    param([string]$CertDir, [string]$CertFile, [string]$KeyFile, [string]$HostName = '', [hashtable]$DotEnv = @{})
    $helper = 'alpine:' + (Get-StormEnvValue $DotEnv 'HELPER_IMAGE_TAG' '3.20')
    $scriptDir = Join-Path $script:RepoRoot 'scripts\deploy'
    $args2 = @('run', '--rm', '--network', 'bridge',
        '-v', "$($CertDir):/certs:ro", '-v', "$($scriptDir):/storm-scripts:ro",
        '-e', "STORM_TLS_CERT_FILE=$CertFile", '-e', "STORM_TLS_KEY_FILE=$KeyFile")
    if ($HostName) { $args2 += @('-e', "STORM_TLS_HOST=$HostName") }
    $args2 += @($helper, 'sh', '/storm-scripts/tls-check.sh')
    $r = Invoke-StormNative -FilePath 'docker' -ArgumentList $args2 -Quiet
    $res = @{ Error = '' }
    foreach ($line in ($r.Output -split "`n")) {
        if ($line -match '^([A-Z_0-9]+)=(.*)$') { $res[$Matches[1]] = $Matches[2].Trim() }
    }
    if ($res.ContainsKey('ERROR')) { $res.Error = $res['ERROR'] }
    elseif ($r.ExitCode -ne 0) { $res.Error = "tls-check exited $($r.ExitCode): $($r.Output)" }
    foreach ($k in @('SUBJECT', 'ISSUER', 'NOTAFTER', 'SAN', 'CHAIN_CERTS', 'EXPIRED', 'EXPIRES_14D', 'HOST_MATCH', 'KEY_MATCH', 'CHAIN_VERIFY')) {
        if (-not $res.ContainsKey($k)) { $res[$k] = '' }
    }
    return $res
}

# ----------------------------------------------------------------------------- docker helpers
function Get-StormComposeState {
    <# Returns one object per compose service: Service, State, Health. #>
    Push-Location $script:RepoRoot
    try {
        $saved = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        $raw = & docker compose ps --all --format json 2>$null
        $ErrorActionPreference = $saved
    } finally { Pop-Location }
    $items = @()
    if (-not $raw) { return $items }
    $text = ($raw -join "`n").Trim()
    if ($text.StartsWith('[')) {
        $items = @($text | ConvertFrom-Json)
    } else {
        $items = @($raw | Where-Object { $_.Trim().StartsWith('{') } | ForEach-Object { $_ | ConvertFrom-Json })
    }
    foreach ($i in $items) {
        $health = ''
        if ($i.PSObject.Properties.Name -contains 'Health') { $health = "$($i.Health)" }
        [pscustomobject]@{ Service = "$($i.Service)"; State = "$($i.State)"; Health = $health; Name = "$($i.Name)" }
    }
}

function Wait-StormHealthy {
    param([int]$TimeoutSec = 240)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        $state = @(Get-StormComposeState)
        $pending = @()
        foreach ($svc in $script:Services) {
            $s = $state | Where-Object { $_.Service -eq $svc } | Select-Object -First 1
            if (-not $s -or $s.State -ne 'running' -or $s.Health -ne 'healthy') { $pending += $svc }
        }
        if ($pending.Count -eq 0) { return $true }
        Write-StormLog ("waiting for: {0}" -f ($pending -join ', ')) 'DETAIL'
        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Show-StormComposeState {
    foreach ($s in @(Get-StormComposeState)) {
        $level = if ($s.State -eq 'running' -and $s.Health -eq 'healthy') { 'OK' } else { 'WARN' }
        Write-StormLog ("{0,-14} state={1,-8} health={2}" -f $s.Service, $s.State, $s.Health) $level
    }
}

# ----------------------------------------------------------------------------- SQL Server (read-only)
function Invoke-StormSqlScalarRow {
    <# Runs a read-only query through sqlcmd -E (shared memory/local). Returns the first data row split on '|'. #>
    param([string]$Query)
    $r = Invoke-StormNative -FilePath 'sqlcmd' -ArgumentList @('-S', 'localhost', '-E', '-C', '-b', '-W', '-h', '-1', '-s', '|', '-l', '10', '-Q', "SET NOCOUNT ON; $Query") -Quiet
    if ($r.ExitCode -ne 0) { throw "sqlcmd failed (exit $($r.ExitCode)): $($r.Output)" }
    $row = ($r.Output -split "`n" | Where-Object { $_.Trim() -ne '' } | Select-Object -First 1)
    # The comma operator keeps a single-column row as an array (otherwise PowerShell unrolls it
    # to a bare string and [0] returns its first CHARACTER).
    if ($null -eq $row) { return , @() }
    return , @($row.Trim() -split '\|' | ForEach-Object { $_.Trim() })
}

function Invoke-StormSqlRows {
    <#
      Runs a read-only query through sqlcmd -E. Returns EVERY non-empty output line (one per
      result row), trimmed. Use for lists: sqlcmd truncates any variable-length column to
      256 characters in its text output (-y default), so a long list must never be returned
      as a single aggregated string.
    #>
    param([string]$Query)
    $r = Invoke-StormNative -FilePath 'sqlcmd' -ArgumentList @('-S', 'localhost', '-E', '-C', '-b', '-W', '-h', '-1', '-l', '10', '-Q', "SET NOCOUNT ON; $Query") -Quiet
    if ($r.ExitCode -ne 0) { throw "sqlcmd failed (exit $($r.ExitCode)): $($r.Output)" }
    # Plain pipeline output (NOT the comma operator): callers collect it with @(...).
    return $r.Output -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }
}

function Get-StormAppLoginName {
    <# SQL_USERNAME from .env (default storm_rtu_app), validated as a plain identifier. #>
    param([hashtable]$DotEnv)
    $login = Get-StormEnvValue $DotEnv 'SQL_USERNAME' 'storm_rtu_app'
    if ($login -notmatch '^[A-Za-z_][A-Za-z0-9_]{0,63}$') { throw "SQL_USERNAME '$login' is not a simple identifier." }
    return $login
}

function Get-StormSqlFileObjects {
    <# Object keys (KIND:Name) created by one database script (comments stripped). #>
    param([Parameter(Mandatory)][string]$FileName)
    $text = [System.IO.File]::ReadAllText((Join-Path (Join-Path $script:RepoRoot 'database') $FileName))
    $text = [regex]::Replace($text, '--[^\r\n]*', '')
    $keys = @()
    foreach ($p in @(@{ K = 'TABLE'; Rx = '(?i)\bCREATE\s+TABLE\s+(?:dbo\.)?\[?(\w+)\]?' },
                     @{ K = 'CONSTRAINT'; Rx = '(?i)\bCONSTRAINT\s+\[?(\w+)\]?' },
                     @{ K = 'INDEX'; Rx = '(?i)\bCREATE\s+(?:UNIQUE\s+)?(?:(?:NON)?CLUSTERED\s+)?INDEX\s+\[?(\w+)\]?' })) {
        foreach ($m in [regex]::Matches($text, $p.Rx)) { $keys += "$($p.K):$($m.Groups[1].Value)" }
    }
    return $keys | Select-Object -Unique      # callers wrap with @()
}

function Invoke-StormSqlFile {
    <# sqlcmd -E -b -i <file> with the app login name exposed as scripting variable STORM_APP_LOGIN. #>
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$AppLogin)
    $env:STORM_APP_LOGIN = $AppLogin
    try { return Invoke-StormNative -FilePath 'sqlcmd' -ArgumentList @('-S', 'localhost', '-E', '-C', '-b', '-i', $Path) }
    finally { Remove-Item Env:\STORM_APP_LOGIN -ErrorAction SilentlyContinue }
}

function Get-StormRequiredSchema {
    <#
      Derives the objects STORM_ENERGY_RTU must contain FROM THE REPOSITORY SCRIPTS
      (base schema 002..004 plus the ordered migrations, e.g. 005), so the check can
      never drift from what initialisation/migration creates. Comments are stripped.
      Returns: Kind (TABLE | CONSTRAINT | INDEX), Name, InMigration (object is created
      by a migration file -> may be added to an existing database by -MigrateDatabase).
    #>
    $dbDir = Join-Path $script:RepoRoot 'database'
    $seen = @{}
    $out = New-Object System.Collections.Generic.List[object]
    $migrationObjects = @{}
    foreach ($f in @($script:SchemaFiles) + @($script:MigrationFiles)) {
        $isMigration = $script:MigrationFiles -contains $f
        $text = [System.IO.File]::ReadAllText((Join-Path $dbDir $f))
        $text = [regex]::Replace($text, '--[^\r\n]*', '')
        $patterns = @(
            @{ Kind = 'TABLE'; Rx = '(?i)\bCREATE\s+TABLE\s+(?:dbo\.)?\[?(\w+)\]?' },
            @{ Kind = 'CONSTRAINT'; Rx = '(?i)\bCONSTRAINT\s+\[?(\w+)\]?' },
            @{ Kind = 'INDEX'; Rx = '(?i)\bCREATE\s+(?:UNIQUE\s+)?(?:(?:NON)?CLUSTERED\s+)?INDEX\s+\[?(\w+)\]?' }
        )
        foreach ($p in $patterns) {
            foreach ($m in [regex]::Matches($text, $p.Rx)) {
                $key = "$($p.Kind):$($m.Groups[1].Value)"
                if ($isMigration) { $migrationObjects[$key] = $true }
                if (-not $seen.ContainsKey($key)) { $seen[$key] = $true; $out.Add([pscustomobject]@{ Kind = $p.Kind; Name = $m.Groups[1].Value; InMigration = $false }) }
            }
        }
    }
    foreach ($o in $out) { if ($migrationObjects.ContainsKey("$($o.Kind):$($o.Name)")) { $o.InMigration = $true } }
    return $out
}

function Get-StormSchemaState {
    <#
      READ-ONLY. Compares STORM_ENERGY_RTU with Get-StormRequiredSchema plus the
      READ_COMMITTED_SNAPSHOT setting from 001. Queries only STORM_ENERGY_RTU catalog
      views and master.sys.databases (never the "Storm" database).
      Returns: Exists, Complete, Missing (string[]), Expected (int), TablesPresent (int).
    #>
    $required = @(Get-StormRequiredSchema)
    $state = [ordered]@{ Exists = $false; Complete = $false; Missing = @(); Expected = $required.Count + 1; TablesPresent = 0; MigrationOnly = $false }
    $exists = Invoke-StormSqlScalarRow "SELECT CASE WHEN DB_ID(N'STORM_ENERGY_RTU') IS NULL THEN 0 ELSE 1 END;"
    if ($exists[0] -ne '1') { $state.Missing = @('DATABASE:STORM_ENERGY_RTU'); return [pscustomobject]$state }
    $state.Exists = $true
    $values = ($required | ForEach-Object { "(N'$($_.Kind)',N'$($_.Name)')" }) -join ','
    $missingFrom = "FROM (VALUES $values) AS v(k, n) WHERE NOT (" +
         "(v.k = N'TABLE' AND EXISTS (SELECT 1 FROM STORM_ENERGY_RTU.sys.tables t WHERE t.name = v.n AND t.schema_id = 1)) OR " +
         "(v.k = N'CONSTRAINT' AND EXISTS (SELECT 1 FROM STORM_ENERGY_RTU.sys.objects o WHERE o.name = v.n AND o.schema_id = 1 AND o.type IN ('PK','UQ','C','F','D'))) OR " +
         "(v.k = N'INDEX' AND EXISTS (SELECT 1 FROM STORM_ENERGY_RTU.sys.indexes i JOIN STORM_ENERGY_RTU.sys.tables t2 ON t2.object_id = i.object_id WHERE i.name = v.n AND t2.schema_id = 1)))"
    $q = "SELECT (SELECT COUNT(*) $missingFrom), " +
         "(SELECT CAST(is_read_committed_snapshot_on AS int) FROM sys.databases WHERE name = N'STORM_ENERGY_RTU'), " +
         "(SELECT COUNT(*) FROM STORM_ENERGY_RTU.sys.tables WHERE schema_id = 1);"
    $row = Invoke-StormSqlScalarRow $q
    # Missing object names come back ONE PER ROW. (They used to be returned as one
    # STRING_AGG value, which sqlcmd cut at 256 characters: the 7 missing 006 objects became
    # "...,IN", a name that is in no migration, so a pending migration was misreported as a
    # base-schema failure.) The count cross-check fails closed on any incomplete output.
    $missing = @()
    if ([int]$row[0] -gt 0) {
        $missing = @(Invoke-StormSqlRows "SELECT v.k + N':' + v.n $missingFrom ORDER BY v.k, v.n;")
        $bad = @($missing | Where-Object { $_ -notmatch '^(TABLE|CONSTRAINT|INDEX):\w+$' })
        if ($missing.Count -ne [int]$row[0] -or $bad.Count) {
            throw ("Schema check output is incomplete (expected {0} missing object name(s), read {1}). Nothing was changed." -f $row[0], $missing.Count)
        }
    }
    if ($row[1] -ne '1') { $missing += 'SETTING:READ_COMMITTED_SNAPSHOT' }
    $state.TablesPresent = [int]$row[2]
    $state.Missing = $missing
    $state.Complete = ($missing.Count -eq 0)
    # Every missing object is created by a migration file -> the base schema is complete and
    # only additive migrations are pending (eligible for deploy.ps1 -MigrateDatabase).
    $migratable = @{}; foreach ($o in $required) { if ($o.InMigration) { $migratable["$($o.Kind):$($o.Name)"] = $true } }
    $state.MigrationOnly = ($missing.Count -gt 0 -and -not ($missing | Where-Object { -not $migratable.ContainsKey($_) }))
    return [pscustomobject]$state
}

function Get-StormSqlStatus {
    <#
      READ-ONLY assessment of the host SQL Server for the Docker deployment.
      Never changes SQL Server. Never touches the "Storm" database.
    #>
    param([string]$AppLogin = 'storm_rtu_app', [int]$SqlPort = 1433)
    $st = [ordered]@{
        SqlcmdFound = $false; Reachable = $false; IntegratedSecurityOnly = $null
        TcpListening = $false; DatabaseExists = $false; TableCount = 0
        SchemaComplete = $false; SchemaMissing = @(); SchemaExpected = 0; SchemaMigrationPending = $false
        LoginExists = $false; Blockers = @(); Error = ''
    }
    if (-not (Get-Command sqlcmd -ErrorAction SilentlyContinue)) {
        $st.Error = 'sqlcmd.exe not found on PATH'
        $st.Blockers += 'sqlcmd.exe is not installed / not on PATH on this host'
        return [pscustomobject]$st
    }
    $st.SqlcmdFound = $true
    $safeLogin = $AppLogin.Replace("'", "''")
    try {
        $row = Invoke-StormSqlScalarRow ("SELECT CAST(SERVERPROPERTY('IsIntegratedSecurityOnly') AS int), " +
            "CASE WHEN DB_ID(N'STORM_ENERGY_RTU') IS NULL THEN 0 ELSE 1 END, " +
            "(SELECT COUNT(*) FROM sys.server_principals WHERE name = N'$safeLogin');")
        $st.Reachable = $true
        $st.IntegratedSecurityOnly = ($row[0] -eq '1')
        $st.DatabaseExists = ($row[1] -eq '1')
        $st.LoginExists = ([int]$row[2] -gt 0)
        if ($st.DatabaseExists) {
            $schema = Get-StormSchemaState
            $st.TableCount = $schema.TablesPresent
            $st.SchemaComplete = $schema.Complete
            $st.SchemaMissing = @($schema.Missing)
            $st.SchemaExpected = $schema.Expected
            $st.SchemaMigrationPending = [bool]$schema.MigrationOnly
        }
    } catch {
        $st.Error = $_.Exception.Message
        $st.Blockers += "SQL Server not reachable locally with Windows authentication (sqlcmd -S localhost -E): $($st.Error)"
    }
    $st.TcpListening = Test-StormTcpPort -HostName '127.0.0.1' -Port $SqlPort -TimeoutMs 2000
    if (-not $st.TcpListening) {
        $st.Blockers += "SQL Server is not accepting TCP connections on port $SqlPort (TCP/IP protocol disabled). Docker containers can only reach SQL Server over TCP."
    }
    if ($st.IntegratedSecurityOnly -eq $true) {
        $st.Blockers += "SQL Server authentication mode is Windows-only (IsIntegratedSecurityOnly=1). Linux containers need a SQL login (Mixed Mode)."
    }
    if ($st.Reachable -and $st.DatabaseExists -and -not $st.SchemaComplete) {
        if ($st.SchemaMigrationPending) {
            $st.Blockers += ("Database schema migration pending ({0}) - run .\deploy.ps1 -MigrateDatabase. Missing: {1}" -f ($script:MigrationFiles -join ', '), ($st.SchemaMissing -join ', '))
        } else {
            $st.Blockers += ("Database STORM_ENERGY_RTU exists but initialisation is INCOMPLETE - missing: {0}" -f ($st.SchemaMissing -join ', '))
        }
    }
    if ($st.Reachable -and -not $st.DatabaseExists) {
        $st.Blockers += "Database STORM_ENERGY_RTU does not exist yet (created by deploy.ps1 -InitDatabase in Phase A)."
    }
    if ($st.Reachable -and -not $st.LoginExists) {
        $st.Blockers += "SQL login '$AppLogin' does not exist yet (created by deploy.ps1 -InitDatabase once Mixed Mode is enabled)."
    }
    return [pscustomobject]$st
}

function Invoke-StormDatabaseMigrate {
    <#
      deploy.ps1 -MigrateDatabase ONLY. Applies the ordered, additive, idempotent migration
      files ($script:MigrationFiles, e.g. 005_device_metadata.sql) to an EXISTING
      STORM_ENERGY_RTU whose base schema (001..004) is complete. Runs as the current
      Windows login via sqlcmd -E. Refuses when the database is missing or when anything
      OTHER than migration objects is missing. No DROP / DELETE / UPDATE / TRUNCATE.
      Never touches the "Storm" database.
    #>
    param([Parameter(Mandatory)][pscustomobject]$SqlStatus, [hashtable]$DotEnv = (Read-StormDotEnv))
    if (-not $SqlStatus.Reachable) { throw 'SQL Server not reachable locally; cannot migrate.' }
    $appLogin = Get-StormAppLoginName $DotEnv
    $dbDir = Join-Path $script:RepoRoot 'database'
    $schema = Get-StormSchemaState
    if (-not $schema.Exists) { throw 'STORM_ENERGY_RTU does not exist - use -InitDatabase for a fresh server (it applies the migrations too).' }
    if ($schema.Complete) { Write-StormLog ("No pending migrations ({0} required objects present) - nothing executed." -f $schema.Expected) 'OK'; return }
    if (-not $schema.MigrationOnly) {
        throw ("Base schema objects are missing ({0}) - this is not a pending migration. Nothing executed; see the -InitDatabase remediation." -f ($schema.Missing -join ', '))
    }
    Write-StormLog ("Pending migration objects: {0}" -f ($schema.Missing -join ', ')) 'INFO'
    foreach ($f in $script:MigrationFiles) {
        $path = Join-Path $dbDir $f
        if (-not (Test-Path $path)) { throw "Missing $path" }
        # Run ONLY migrations that still have missing objects; fully applied ones are not re-run.
        $pending = @(Get-StormSqlFileObjects $f | Where-Object { $schema.Missing -contains $_ })
        if ($pending.Count -eq 0) { Write-StormLog "$f already applied - not re-run" 'DETAIL'; continue }
        Write-StormLog "sqlcmd -E -b -i $f   (pending: $($pending -join ', '))" 'DETAIL'
        $r = Invoke-StormSqlFile -Path $path -AppLogin $appLogin
        if ($r.ExitCode -ne 0) { throw "$f failed (exit $($r.ExitCode)). Stopped; later migrations were not run. The migration is idempotent and can be re-run after the cause is fixed." }
    }
    $schema = Get-StormSchemaState
    if (-not $schema.Complete) { throw ("Migrations ran but objects are still missing: {0}" -f ($schema.Missing -join ', ')) }
    Write-StormLog ("Migrations applied and verified ({0} required objects present)" -f $schema.Expected) 'OK'
}

function Invoke-StormDatabaseInit {
    <#
      PHASE A ONLY - called by deploy.ps1 -InitDatabase.
      * STORM_ENERGY_RTU missing -> runs database\001..004 in order (sqlcmd -E -b).
      * STORM_ENERGY_RTU present -> runs NOTHING against its schema (no 001, no ALTER).
      * App login: created only when Mixed Mode is already enabled; the password is
        passed through the process environment (sqlcmd scripting variable), never
        on the command line. Existing logins/users are left unchanged.
      Never DROP / DELETE / TRUNCATE / ALTER DATABASE on an existing database.
      Never touches the "Storm" database.
    #>
    param([Parameter(Mandatory)][pscustomobject]$SqlStatus, [Parameter(Mandatory)][hashtable]$DotEnv)
    $dbDir = Join-Path $script:RepoRoot 'database'
    if (-not $SqlStatus.Reachable) { throw "SQL Server not reachable locally; cannot initialise database." }

    # Always re-read the live schema state: never trust a possibly stale status object.
    $schema = Get-StormSchemaState
    if (-not $schema.Exists) {
        Write-StormLog ("STORM_ENERGY_RTU does not exist -> running 001..004 + {0} (idempotent, create-only scripts)" -f ($script:MigrationFiles -join ', ')) 'INFO'
        $appLogin = Get-StormAppLoginName $DotEnv
        foreach ($f in @('001_database.sql') + @($script:SchemaFiles) + @($script:MigrationFiles)) {
            $path = Join-Path $dbDir $f
            if (-not (Test-Path $path)) { throw "Missing $path" }
            Write-StormLog "sqlcmd -E -b -i $f" 'DETAIL'
            $r = Invoke-StormSqlFile -Path $path -AppLogin $appLogin
            if ($r.ExitCode -ne 0) {
                throw ("$f failed (exit $($r.ExitCode)). Stopped; later scripts were not run. STORM_ENERGY_RTU may now be PARTIALLY " +
                       "initialised - a re-run of -InitDatabase will detect this and stop. Nothing was dropped.")
            }
        }
        $schema = Get-StormSchemaState
        if (-not $schema.Complete) {
            throw ("001..004 completed but the schema check still reports missing objects: {0}. Stopping before any login is created." -f ($schema.Missing -join ', '))
        }
        Write-StormLog ("Database STORM_ENERGY_RTU initialised from 001..004 and verified ({0} required objects present)" -f $schema.Expected) 'OK'
    } elseif ($schema.Complete) {
        Write-StormLog ("STORM_ENERGY_RTU already exists and is fully initialised ({0} required objects present) -> NOT re-run, NOT altered" -f $schema.Expected) 'OK'
    } elseif ($schema.MigrationOnly) {
        Write-StormLog ("STORM_ENERGY_RTU base schema is complete; additive migration(s) pending: {0}" -f ($schema.Missing -join ', ')) 'FAIL'
        Write-StormLog 'Nothing was executed and no login was created. Apply them explicitly with: .\deploy.ps1 -MigrateDatabase' 'FAIL'
        throw 'STORM_ENERGY_RTU has pending migrations - run deploy.ps1 -MigrateDatabase.'
    } else {
        # Existing but partially initialised: fail closed. No automatic recovery, no DROP.
        Write-StormLog ("STORM_ENERGY_RTU exists but initialisation is INCOMPLETE. Missing: {0}" -f ($schema.Missing -join ', ')) 'FAIL'
        Write-StormLog 'Nothing was executed against the database and no login was created.' 'FAIL'
        Write-StormLog 'Remediation (manual, by an administrator, after reviewing the database):' 'FAIL'
        Write-StormLog '  001..004 are guarded (IF NOT EXISTS / setting only if OFF) and add only what is missing.' 'FAIL'
        Write-StormLog '  Run them in order, one at a time, checking the output of each:' 'FAIL'
        Write-StormLog '    sqlcmd -S localhost -E -C -b -i database\001_database.sql   (then 002_tables.sql, 003_indexes.sql, 004_constraints.sql)' 'FAIL'
        Write-StormLog '  then re-run: .\deploy.ps1 -InitDatabase   (the database is never dropped or recreated automatically)' 'FAIL'
        throw 'STORM_ENERGY_RTU initialisation is incomplete - see the listed missing objects and remediation above.'
    }

    $login = Get-StormEnvValue $DotEnv 'SQL_USERNAME' 'storm_rtu_app'
    $password = Get-StormEnvValue $DotEnv 'SQL_PASSWORD' ''
    if ($SqlStatus.IntegratedSecurityOnly -ne $false) {
        Write-StormLog "Mixed Mode is NOT enabled -> SQL login '$login' NOT created (Phase A prerequisite)." 'WARN'
        return
    }
    if ($login -notmatch '^[A-Za-z_][A-Za-z0-9_]{0,63}$') { throw "SQL_USERNAME '$login' is not a simple identifier." }
    if ($password -eq '' -or $password -eq '__GENERATE__' -or $password -match "['\]]") { throw 'SQL_PASSWORD in .env is empty/placeholder or contains quote/bracket characters.' }
    $env:STORM_APP_LOGIN = $login
    $env:STORM_APP_PASSWORD = $password
    try {
        $r = Invoke-StormNative -FilePath 'sqlcmd' -ArgumentList @('-S', 'localhost', '-E', '-C', '-b', '-i', (Join-Path $dbDir 'security\create_app_login.sql'))
        if ($r.ExitCode -ne 0) { throw "create_app_login.sql failed (exit $($r.ExitCode))" }
    } finally {
        Remove-Item Env:\STORM_APP_PASSWORD -ErrorAction SilentlyContinue
        Remove-Item Env:\STORM_APP_LOGIN -ErrorAction SilentlyContinue
    }
    Write-StormLog "SQL login/user '$login' present with SELECT/INSERT/UPDATE on STORM_ENERGY_RTU.dbo" 'OK'
}

# ----------------------------------------------------------------------------- health checks
function Invoke-StormHealthCheck {
    <#
      Real functional checks (not just "container running"). Returns:
        InfraHealthy, DatabaseAvailable, Results (list), ExitCode
      ExitCode: 0 = infrastructure + database OK
                2 = infrastructure OK, database unavailable (expected before Phase A)
                1 = infrastructure failure
    #>
    param([hashtable]$DotEnv = (Read-StormDotEnv))
    $hostIp = Get-StormEnvValue $DotEnv 'STORM_HOST_IP' ''
    $apiPort = [int](Get-StormEnvValue $DotEnv 'API_HOST_PORT' '8000')
    $httpPort = [int](Get-StormEnvValue $DotEnv 'HTTP_HOST_PORT' '8080')
    $httpsPort = [int](Get-StormEnvValue $DotEnv 'HTTPS_HOST_PORT' '443')
    $mqttPort = [int](Get-StormEnvValue $DotEnv 'MQTT_HOST_PORT' '1884')
    $tcpPort = [int](Get-StormEnvValue $DotEnv 'TCP_HOST_PORT' '8100')
    $helperTag = Get-StormEnvValue $DotEnv 'MOSQUITTO_IMAGE_TAG' '2.0.22'
    $results = New-Object System.Collections.Generic.List[object]
    function Add-Result([string]$Group, [string]$Name, [bool]$Ok, [string]$Detail) {
        $results.Add([pscustomobject]@{ Group = $Group; Check = $Name; Ok = $Ok; Detail = $Detail })
        Write-StormLog ("{0,-9} {1,-44} {2}" -f $Group, $Name, $Detail) $(if ($Ok) { 'OK' } else { 'FAIL' })
    }

    # 1. Containers
    $state = @(Get-StormComposeState)
    foreach ($svc in $script:Services) {
        $s = $state | Where-Object { $_.Service -eq $svc } | Select-Object -First 1
        $ok = [bool]($s -and $s.State -eq 'running' -and $s.Health -eq 'healthy')
        $detail = if ($s) { "state=$($s.State) health=$($s.Health)" } else { 'not found' }
        Add-Result 'INFRA' "container $svc" $ok $detail
    }

    # 2. API
    $live = Invoke-StormHttp "http://127.0.0.1:$apiPort/health/live"
    Add-Result 'INFRA' "API /health/live (127.0.0.1:$apiPort)" ($live.StatusCode -eq 200) "HTTP $($live.StatusCode)"
    $healthObj = $null
    $h = Invoke-StormHttp "http://127.0.0.1:$apiPort/health" -TimeoutSec 20
    if ($h.StatusCode -eq 200) { try { $healthObj = $h.Body | ConvertFrom-Json } catch { $healthObj = $null } }
    Add-Result 'INFRA' 'API /health responds with JSON' ($null -ne $healthObj) "HTTP $($h.StatusCode)"
    if ($healthObj) {
        Add-Result 'INFRA' 'API MQTT consumer connected to broker' ($healthObj.mqtt.status -eq 'ok') "mqtt=$($healthObj.mqtt.status) ($($healthObj.mqtt.details))"
        Add-Result 'INFRA' 'API reports TCP listener as separate service' ($healthObj.tcp.status -eq 'disabled') "tcp=$($healthObj.tcp.status)"
    }
    if ($hostIp) {
        $exposed = Test-StormTcpPort -HostName $hostIp -Port $apiPort -TimeoutMs 2000
        Add-Result 'INFRA' "API NOT reachable on LAN ($($hostIp):$apiPort)" (-not $exposed) $(if ($exposed) { 'EXPOSED - expected loopback only' } else { 'loopback only (correct)' })
    }

    # 3. MQTT broker
    $sh = 'T=storm/healthcheck/$(date +%s); mosquitto_sub -h 127.0.0.1 -p 1883 -u $MQTT_USERNAME -P $MQTT_PASSWORD -t $T -C 1 -W 10 > /tmp/storm-hc.out & S=$!; sleep 1; mosquitto_pub -h 127.0.0.1 -p 1883 -u $MQTT_USERNAME -P $MQTT_PASSWORD -q 1 -t $T -m storm-hc-ok; wait $S; cat /tmp/storm-hc.out; rm -f /tmp/storm-hc.out'
    $r = Invoke-StormCompose -ArgumentList @('exec', '-T', 'mosquitto', 'sh', '-c', $sh) -Quiet
    Add-Result 'INFRA' 'MQTT authenticated publish/subscribe' ($r.ExitCode -eq 0 -and $r.Output -match 'storm-hc-ok') $(if ($r.Output -match 'storm-hc-ok') { 'message round-trip OK' } else { "exit $($r.ExitCode): $($r.Output)" })
    $net = "$($script:ComposeProject)-net"
    $mqttUser = Get-StormEnvValue $DotEnv 'MQTT_USERNAME' ''
    $mqttPass = Get-StormEnvValue $DotEnv 'MQTT_PASSWORD' ''
    $pubArgs = @('run', '--rm', '--network', $net, '--entrypoint', 'mosquitto_pub', "eclipse-mosquitto:$helperTag", '-h', 'host.docker.internal', '-p', "$mqttPort", '-t', 'storm/healthcheck/published-port', '-m', 'x')
    $anon = Invoke-StormNative -FilePath 'docker' -ArgumentList $pubArgs -Quiet
    Add-Result 'INFRA' "MQTT anonymous client rejected (host :$mqttPort)" ($anon.ExitCode -ne 0 -and $anon.Output -match 'not authori') $(if ($anon.Output -match 'not authori') { 'refused: not authorised (correct)' } else { "exit $($anon.ExitCode): $($anon.Output)" })
    $env:STORM_HC_MQTT_USER = $mqttUser; $env:STORM_HC_MQTT_PASS = $mqttPass
    try {
        $authArgs = @('run', '--rm', '--network', $net, '-e', 'STORM_HC_MQTT_USER', '-e', 'STORM_HC_MQTT_PASS', '--entrypoint', 'sh', "eclipse-mosquitto:$helperTag", '-c',
            "mosquitto_pub -h host.docker.internal -p $mqttPort -u `$STORM_HC_MQTT_USER -P `$STORM_HC_MQTT_PASS -q 1 -t storm/healthcheck/published-port -m ok")
        $auth = Invoke-StormNative -FilePath 'docker' -ArgumentList $authArgs -Quiet
    } finally { Remove-Item Env:\STORM_HC_MQTT_USER, Env:\STORM_HC_MQTT_PASS -ErrorAction SilentlyContinue }
    Add-Result 'INFRA' "MQTT authenticated publish via host :$mqttPort" ($auth.ExitCode -eq 0) "exit $($auth.ExitCode)"
    Add-Result 'INFRA' "MQTT port 127.0.0.1:$mqttPort open" (Test-StormTcpPort '127.0.0.1' $mqttPort) ''
    if ($hostIp) { Add-Result 'INFRA' "MQTT port $($hostIp):$mqttPort open" (Test-StormTcpPort $hostIp $mqttPort) '' }

    # 4. RTU TCP listener
    Add-Result 'INFRA' "RTU TCP 127.0.0.1:$tcpPort accepts connections" (Test-StormTcpPort '127.0.0.1' $tcpPort) ''
    if ($hostIp) { Add-Result 'INFRA' "RTU TCP $($hostIp):$tcpPort accepts connections" (Test-StormTcpPort $hostIp $tcpPort) '' }

    # 5. Reverse proxy
    $fe = Invoke-StormHttp "http://127.0.0.1:$httpPort/"
    Add-Result 'INFRA' "frontend via proxy :$httpPort /" ($fe.StatusCode -eq 200 -and $fe.Body -match 'id="root"') "HTTP $($fe.StatusCode)"
    $spa = Invoke-StormHttp "https://127.0.0.1:$httpsPort/gis" -Insecure
    Add-Result 'INFRA' "SPA refresh on route /gis (HTTPS)" ($spa.StatusCode -eq 200 -and $spa.Body -match 'id="root"') "HTTP $($spa.StatusCode) (index.html fallback)"
    $tl = Invoke-StormHttp "https://127.0.0.1:$httpsPort/test-logs" -Insecure
    Add-Result 'INFRA' 'SPA route /test-logs (Protocol Test Log)' ($tl.StatusCode -eq 200 -and $tl.Body -match 'id="root"') "HTTP $($tl.StatusCode)"
    foreach ($route in '/dma-analytics', '/nrw-analytics', '/schematic', '/consumer-analytics', '/testing', '/production') {
        $sp = Invoke-StormHttp "https://127.0.0.1:$httpsPort$route" -Insecure
        Add-Result 'INFRA' "SPA route $route" ($sp.StatusCode -eq 200 -and $sp.Body -match 'id="root"') "HTTP $($sp.StatusCode)"
    }
    $pk = Invoke-StormHttp "https://127.0.0.1:$httpsPort/api/diagnostics/packets?page=1&page_size=50" -Insecure -TimeoutSec 20
    Add-Result 'INFRA' 'Testing API /api/diagnostics/packets' ($pk.StatusCode -eq 200 -and $pk.Body -match 'server_time') "HTTP $($pk.StatusCode)"
    $an = Invoke-StormHttp "https://127.0.0.1:$httpsPort/api/analytics/overview" -Insecure -TimeoutSec 30
    Add-Result 'INFRA' 'Analytics API /api/analytics/overview' ($an.StatusCode -eq 200 -and $an.Body -match 'total_kl') "HTTP $($an.StatusCode)"
    $idxCache = Get-StormHttpHeader "https://127.0.0.1:$httpsPort/" 'Cache-Control'
    Add-Result 'INFRA' 'index.html is not cached' ($idxCache -match 'no-cache|no-store') "Cache-Control: $idxCache"
    $api404 = Invoke-StormHttp "https://127.0.0.1:$httpsPort/api/does-not-exist" -Insecure
    Add-Result 'INFRA' '/api/* routed to storm-api (not the SPA)' ($api404.StatusCode -eq 404 -and $api404.Body -notmatch 'id="root"') "HTTP $($api404.StatusCode)"
    $n1 = Invoke-StormHttp "http://127.0.0.1:$httpPort/nginx-health"
    Add-Result 'INFRA' "nginx HTTP :$httpPort /nginx-health" ($n1.StatusCode -eq 200) "HTTP $($n1.StatusCode)"
    $n2 = Invoke-StormHttp "http://127.0.0.1:$httpPort/health/live"
    Add-Result 'INFRA' "nginx HTTP :$httpPort -> API /health/live" ($n2.StatusCode -eq 200) "HTTP $($n2.StatusCode)"
    $n3 = Invoke-StormHttp "https://127.0.0.1:$httpsPort/health/live" -Insecure
    Add-Result 'INFRA' "nginx HTTPS :$httpsPort -> API /health/live" ($n3.StatusCode -eq 200) "HTTP $($n3.StatusCode)"
    $n4 = Invoke-StormHttp "https://127.0.0.1:$httpsPort/api/devices" -Insecure -TimeoutSec 20
    Add-Result 'INFRA' "nginx HTTPS :$httpsPort /api/ routed to API" ($n4.StatusCode -ne 0 -and $n4.StatusCode -ne 502 -and $n4.StatusCode -ne 504) "HTTP $($n4.StatusCode) (5xx other than 502/504 = API reached, DB unavailable)"
    if ($hostIp) {
        $n5 = Invoke-StormHttp "http://$($hostIp):$httpPort/nginx-health"
        Add-Result 'INFRA' "nginx HTTP $($hostIp):$httpPort" ($n5.StatusCode -eq 200) "HTTP $($n5.StatusCode)"
        $n6 = Invoke-StormHttp "https://$($hostIp):$httpsPort/nginx-health" -Insecure
        Add-Result 'INFRA' "nginx HTTPS $($hostIp):$httpsPort" ($n6.StatusCode -eq 200) "HTTP $($n6.StatusCode)"
    }
    $tlsName = Get-StormEnvValue $DotEnv 'TLS_SERVER_NAME' ''
    $cert = Get-StormTlsCertificate $(if ($tlsName) { $tlsName } else { '127.0.0.1' }) $httpsPort -ConnectTo '127.0.0.1'
    if ($cert) {
        $bootstrap = $cert.Subject -match 'bootstrap'
        Add-Result 'INFRA' 'TLS certificate served' $true ("{0} | {1} | expires {2:yyyy-MM-dd}{3}" -f $cert.Subject, $cert.Protocol, $cert.NotAfter, $(if ($bootstrap) { ' | BOOTSTRAP/TEST cert' } else { '' }))
    } else {
        Add-Result 'INFRA' 'TLS certificate served' $false 'TLS handshake failed'
    }
    if ($tlsName) {
        # Full validation (chain to a trusted root + hostname), NO -k: connect to 127.0.0.1 as $tlsName.
        $v = Invoke-StormHttp "https://$($tlsName):$httpsPort/health/live" -Resolve "$($tlsName):$($httpsPort):127.0.0.1" -RevokeBestEffort
        Add-Result 'INFRA' "HTTPS verified as $tlsName (chain + hostname)" ($v.StatusCode -eq 200) $(if ($v.StatusCode -eq 200) { 'trusted certificate, hostname OK, HTTP 200' } else { "HTTP $($v.StatusCode) - certificate not trusted for $tlsName or request failed" })
    }

    # 6. Database (reported separately - never folded into infrastructure health)
    $dbAvailable = $false
    if ($healthObj) {
        $dbAvailable = ($healthObj.database.status -eq 'ok')
        Add-Result 'DATABASE' 'API -> SQL Server (STORM_ENERGY_RTU)' $dbAvailable "database=$($healthObj.database.status) ($($healthObj.database.details)); overall=$($healthObj.status)"
    } else {
        Add-Result 'DATABASE' 'API -> SQL Server (STORM_ENERGY_RTU)' $false 'API /health unavailable'
    }
    # No double quotes: Windows PowerShell 5.1 mangles embedded quotes in native arguments.
    $lt = Invoke-StormHttp "https://127.0.0.1:$httpsPort/api/devices/latest" -Insecure -TimeoutSec 20
    $ltOk = $false; $ltDetail = "HTTP $($lt.StatusCode)"
    if ($lt.StatusCode -eq 200) { try { $j = $lt.Body | ConvertFrom-Json; $ltOk = ($null -ne $j.server_time); $ltDetail = "HTTP 200, $(@($j.devices).Count) device(s)" } catch { $ltDetail = 'HTTP 200 but not JSON' } }
    Add-Result 'DATABASE' 'GET /api/devices/latest via proxy' $ltOk $ltDetail
    # Protocol Test Log (read-only diagnostics API) + retention permission scope
    $dg = Invoke-StormHttp "https://127.0.0.1:$httpsPort/api/diagnostics/tcp?page=1&page_size=50" -Insecure -TimeoutSec 20
    $dgOk = $false; $dgDetail = "HTTP $($dg.StatusCode)"
    if ($dg.StatusCode -eq 200) { try { $j = $dg.Body | ConvertFrom-Json; $dgOk = ($null -ne $j.server_time_display -and $j.page_size -eq 50); $dgDetail = "HTTP 200, $($j.total) TCP record(s), server time $($j.server_time_display)" } catch { $dgDetail = 'HTTP 200 but not JSON' } }
    Add-Result 'DATABASE' 'GET /api/diagnostics/tcp via proxy' $dgOk $dgDetail
    $dm = Invoke-StormHttp "https://127.0.0.1:$httpsPort/api/diagnostics/mqtt?page=1&page_size=50" -Insecure -TimeoutSec 20
    $dmOk = $false; $dmDetail = "HTTP $($dm.StatusCode)"
    if ($dm.StatusCode -eq 200) { try { $j = $dm.Body | ConvertFrom-Json; $dmOk = ($null -ne $j.server_time_display -and $j.page_size -eq 50); $dmDetail = "HTTP 200, $($j.total) MQTT record(s)" } catch { $dmDetail = 'HTTP 200 but not JSON' } }
    Add-Result 'DATABASE' 'GET /api/diagnostics/mqtt via proxy' $dmOk $dmDetail
    try {
        $appLogin = Get-StormAppLoginName $DotEnv
        $obj = "OBJECT_ID(N'STORM_ENERGY_RTU.dbo.ProtocolDiagnosticLogs')"
        $perm = "FROM STORM_ENERGY_RTU.sys.database_permissions p JOIN STORM_ENERGY_RTU.sys.database_principals u ON u.principal_id = p.grantee_principal_id " +
                "WHERE u.name = N'$appLogin' AND p.permission_name = N'DELETE' AND p.state IN ('G','W')"
        $row = Invoke-StormSqlScalarRow ("SELECT (SELECT COUNT(*) $perm AND p.class = 1 AND p.major_id = $obj), " +
                                         "(SELECT COUNT(*) $perm AND NOT (p.class = 1 AND p.major_id = $obj));")
        Add-Result 'DATABASE' 'retention DELETE granted on ProtocolDiagnosticLogs only' ($row[0] -eq '1' -and $row[1] -eq '0') ("diagnostics table grant=$($row[0]), DELETE elsewhere=$($row[1])")
    } catch { Add-Result 'DATABASE' 'retention DELETE granted on ProtocolDiagnosticLogs only' $false $_.Exception.Message }
    $py = 'import socket,os;s=socket.socket();s.settimeout(3);r=s.connect_ex((os.environ.get(''SQL_SERVER'',''host.docker.internal''),int(os.environ.get(''SQL_PORT'',''1433''))));print(''tcp_connect_ex=''+str(r))'
    $probe = Invoke-StormCompose -ArgumentList @('exec', '-T', 'storm-api', 'python', '-c', $py) -Quiet
    $tcpOk = ($probe.Output -match 'tcp_connect_ex=0')
    Add-Result 'DATABASE' 'container -> host.docker.internal:1433 (TCP)' $tcpOk $(if ($tcpOk) { 'reachable' } else { "not reachable ($($probe.Output.Trim()))" })

    $infraOk = -not ($results | Where-Object { $_.Group -eq 'INFRA' -and -not $_.Ok })
    $exit = if (-not $infraOk) { 1 } elseif (-not $dbAvailable) { 2 } else { 0 }
    Write-StormLog '' 'INFO'
    Write-StormLog ("INFRASTRUCTURE : {0}" -f $(if ($infraOk) { 'HEALTHY' } else { 'UNHEALTHY' })) $(if ($infraOk) { 'OK' } else { 'FAIL' })
    Write-StormLog ("DATABASE       : {0}" -f $(if ($dbAvailable) { 'AVAILABLE' } else { 'UNAVAILABLE' })) $(if ($dbAvailable) { 'OK' } else { 'WARN' })
    return [pscustomobject]@{ InfraHealthy = [bool]$infraOk; DatabaseAvailable = $dbAvailable; Results = $results; ExitCode = $exit }
}

Export-ModuleMember -Function *-Storm*, Get-StormRepoRoot
