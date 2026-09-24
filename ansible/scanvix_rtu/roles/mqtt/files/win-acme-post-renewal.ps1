<#
.SYNOPSIS
    Storm Energy RTU -- win-acme post-renewal script (Phase 6 DESIGN ONLY).

.DESCRIPTION
    NOT WIRED INTO ANY SCHEDULED TASK OR PLAYBOOK. This file exists as
    source-of-truth for a future, explicitly-authorized phase to install
    and configure win-acme with. It is not executed by anything today.

    win-acme's built-in "Script" installation plugin
    (https://www.win-acme.com/reference/plugins/installation/script) runs
    an external script automatically after every successful certificate
    issuance/renewal, including renewals fired by win-acme's own scheduled
    task. This script is designed to be that hook, invoked as:

        --installation script --script <path-to-this-file> `
          --scriptparameters "-CommonName '{0}'"

    (win-acme substitutes {0} with the certificate's common name at
    execution time -- see https://www.win-acme.com/reference/plugins/installation/script)

    PREREQUISITE (Phase 6 finding, verified against
    https://www.win-acme.com/reference/plugins/store/pemfiles): win-acme
    must be configured with the PemFiles store plugin, e.g.:

        --store pemfiles --pemfilespath "E:\StormEnergyRTU\certs\live\mqtt.stormenergy.in" --pemfilesname cert

    which produces, in that directory:
        cert-crt.pem         (leaf certificate only -- not used here)
        cert-key.pem         (private key)
        cert-chain.pem       (certificate + chain -- i.e. the "fullchain")
        cert-chain-only.pem  (chain without the leaf certificate)

    win-acme does NOT natively produce files named fullchain.pem/
    privkey.pem/chain.pem (the Certbot/Let's Encrypt-standard names this
    project's Mosquitto template already expects -- see group_vars/all.yml
    scanvix_mqtt_tls_certfile/keyfile, Phase 2/3). This script's first job
    is to bridge that gap: rename/copy win-acme's actual PemFiles output
    into the exact filenames Mosquitto is configured to read.

    Renewal flow implemented here (see Phase 6 report item I):
        1. Locate win-acme's PemFiles output (cert-{crt,key,chain,chain-only}.pem)
        2. Verify all required source files exist and are non-empty
        3. Stage the rename into a temp location first (atomic-ish swap)
        4. Only after staging succeeds, replace the live fullchain.pem/
           privkey.pem/chain.pem -- the PREVIOUS files are moved aside
           (never deleted outright) so a failure partway through never
           leaves Mosquitto with a missing or half-written certificate
        5. Controlled StormMosquitto restart (via the Windows service
           manager -- NSSM-wrapped, see roles/mqtt/tasks/gate2.yml)
        6. Verify the service reaches Running
        7. Verify TCP 8883 is actually listening
        8. On ANY failure at steps 3-7: restore the previous certificate
           files from the aside-location and leave StormMosquitto exactly
           as it was found -- a failed renewal must never leave the
           broker running with no valid certificate, or leave it stopped.

    This script deliberately does NOT verify MQTT TLS connection, auth,
    or ACL enforcement end-to-end (steps further down the Phase 6 renewal
    diagram) -- those require a real MQTT client round-trip and are left
    to a separate, future monitoring check, not this synchronous renewal
    hook (win-acme's scheduled task has a bounded execution window; a full
    protocol-level self-test does not belong inside it).

    SAFETY: this script is NEVER executed by this phase. It is reviewed
    source only. Running it requires win-acme to be installed and
    configured (not done this phase) and requires explicit future
    authorization to wire into a scheduled task.

.NOTES
    Author: Storm Energy RTU platform (Phase 6 design)
    Status: SOURCE ONLY -- NOT DEPLOYED, NOT SCHEDULED, NOT EXECUTED
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$CommonName,

    [string]$PemFilesDir   = 'E:\StormEnergyRTU\certs\live\mqtt.stormenergy.in',
    [string]$PemFilesName  = 'cert',
    [string]$ServiceName   = 'StormMosquitto',
    [int]   $TlsPort       = 8883,
    [int]   $ServiceWaitSeconds = 30
)

$ErrorActionPreference = 'Stop'

function Write-Log($msg) {
    Write-Output "[$(Get-Date -Format o)] $msg"
}

Write-Log "win-acme post-renewal hook starting for CommonName='$CommonName'"

# ---------------------------------------------------------------------
# 1-2. Locate and verify win-acme's PemFiles output
# ---------------------------------------------------------------------
$srcCrt       = Join-Path $PemFilesDir "$PemFilesName-crt.pem"
$srcKey       = Join-Path $PemFilesDir "$PemFilesName-key.pem"
$srcChain     = Join-Path $PemFilesDir "$PemFilesName-chain.pem"        # cert + chain == "fullchain"
$srcChainOnly = Join-Path $PemFilesDir "$PemFilesName-chain-only.pem"   # chain only

$required = @($srcKey, $srcChain, $srcChainOnly)
foreach ($f in $required) {
    if (-not (Test-Path $f)) {
        Write-Error "RENEWAL_ABORTED: expected win-acme output file missing: $f"
        exit 1
    }
    if ((Get-Item $f).Length -eq 0) {
        Write-Error "RENEWAL_ABORTED: win-acme output file is empty: $f"
        exit 1
    }
}
Write-Log "Verified win-acme PemFiles output present and non-empty."

# ---------------------------------------------------------------------
# 3-4. Fail-safe rename: stage new files, move the old ones aside
#      (never delete), only then promote the new files into place.
# ---------------------------------------------------------------------
$destFullchain = Join-Path $PemFilesDir 'fullchain.pem'
$destPrivkey   = Join-Path $PemFilesDir 'privkey.pem'
$destChain     = Join-Path $PemFilesDir 'chain.pem'

$stagingDir = Join-Path $PemFilesDir '.staging'
New-Item -ItemType Directory -Path $stagingDir -Force | Out-Null

Copy-Item -Path $srcChain     -Destination (Join-Path $stagingDir 'fullchain.pem') -Force
Copy-Item -Path $srcKey       -Destination (Join-Path $stagingDir 'privkey.pem')   -Force
Copy-Item -Path $srcChainOnly -Destination (Join-Path $stagingDir 'chain.pem')     -Force
Write-Log "Staged renamed certificate files in $stagingDir"

$backupDir = Join-Path $PemFilesDir (".previous-{0}" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
foreach ($existing in @($destFullchain, $destPrivkey, $destChain)) {
    if (Test-Path $existing) {
        Move-Item -Path $existing -Destination $backupDir -Force
    }
}
Write-Log "Previous certificate files (if any) moved aside to $backupDir (never deleted)."

function Restore-PreviousCertificate {
    Write-Log "ROLLBACK: restoring previous certificate files from $backupDir"
    foreach ($name in @('fullchain.pem', 'privkey.pem', 'chain.pem')) {
        $backupFile = Join-Path $backupDir $name
        if (Test-Path $backupFile) {
            Move-Item -Path $backupFile -Destination (Join-Path $PemFilesDir $name) -Force
        }
    }
    Write-Log "ROLLBACK complete: previous certificate restored, StormMosquitto left untouched by this script beyond that."
}

try {
    Move-Item -Path (Join-Path $stagingDir 'fullchain.pem') -Destination $destFullchain -Force
    Move-Item -Path (Join-Path $stagingDir 'privkey.pem')   -Destination $destPrivkey   -Force
    Move-Item -Path (Join-Path $stagingDir 'chain.pem')     -Destination $destChain     -Force
    Write-Log "Promoted new certificate files into place: $destFullchain, $destPrivkey, $destChain"
}
catch {
    Write-Error "RENEWAL_FAILED during file promotion: $_"
    Restore-PreviousCertificate
    exit 1
}

# ---------------------------------------------------------------------
# 5-6. Controlled StormMosquitto restart + verify Running
# ---------------------------------------------------------------------
try {
    $svc = Get-Service -Name $ServiceName -ErrorAction Stop
    $wasRunning = ($svc.Status -eq 'Running')

    Write-Log "Restarting $ServiceName (current status: $($svc.Status))..."
    Restart-Service -Name $ServiceName -Force -ErrorAction Stop

    $waited = 0
    while ($waited -lt $ServiceWaitSeconds) {
        Start-Sleep -Seconds 1
        $waited++
        $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -eq 'Running') {
            Write-Log "$ServiceName reached Running after ${waited}s."
            break
        }
        if ($svc -and $svc.Status -eq 'Paused') {
            throw "$ServiceName entered SERVICE_PAUSED after restart -- likely a bad certificate/config."
        }
    }
    if (-not ($svc -and $svc.Status -eq 'Running')) {
        throw "$ServiceName did not reach Running within ${ServiceWaitSeconds}s (status: $($svc.Status))"
    }
}
catch {
    Write-Error "RENEWAL_FAILED: StormMosquitto restart/verification failed: $_"
    Restore-PreviousCertificate
    try {
        Write-Log "Attempting to restart StormMosquitto again with the RESTORED (previous) certificate..."
        Restart-Service -Name $ServiceName -Force -ErrorAction Stop
    }
    catch {
        Write-Error "CRITICAL: StormMosquitto did not restart even after certificate rollback. Manual intervention required. $_"
    }
    exit 1
}

# ---------------------------------------------------------------------
# 7. Verify TCP 8883 is actually listening
# ---------------------------------------------------------------------
$listening = Get-NetTCPConnection -LocalPort $TlsPort -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
    Write-Error "RENEWAL_FAILED: $ServiceName is Running but port $TlsPort is not listening after restart."
    Restore-PreviousCertificate
    try { Restart-Service -Name $ServiceName -Force -ErrorAction Stop } catch {}
    exit 1
}
Write-Log "Verified TCP $TlsPort is listening."

# ---------------------------------------------------------------------
# Success. Old certificate/state kept in $backupDir for manual inspection
# (NOT auto-deleted by this script -- routine cleanup of old .previous-*
# directories is a separate, future housekeeping concern, not part of
# the renewal hot path).
# ---------------------------------------------------------------------
Write-Log "RENEWAL_SUCCESS: certificate for '$CommonName' installed, $ServiceName running, port $TlsPort listening."
Write-Log "Previous certificate retained (not deleted) at: $backupDir"
exit 0
