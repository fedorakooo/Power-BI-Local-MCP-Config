[CmdletBinding()]
param([string]$Root = (Split-Path -Parent $PSScriptRoot), [switch]$Recover)
$ErrorActionPreference = 'Stop'
$runtime = Join-Path $Root 'runtime'
$cfg = Get-Content (Join-Path $runtime 'unattended.json') -Raw | ConvertFrom-Json
$stateFile = Join-Path $runtime 'background-health.json'
$previous = $null
if (Test-Path -LiteralPath $stateFile) { $previous = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json }
$errors = @()
$warnings = @()
$backupStatus=Join-Path $runtime 'last-model-backup.json'
if (!(Test-Path -LiteralPath $backupStatus) -or (Get-Item -LiteralPath $backupStatus).LastWriteTimeUtc -lt [DateTime]::UtcNow.AddHours(-36)) { $warnings += 'No model backup in the last 36 hours' }
$drive=Get-PSDrive -Name ([IO.Path]::GetPathRoot($Root).Substring(0,1))
if ($drive.Free -lt 1GB) { $warnings += 'Less than 1 GB free on deployment drive' }
foreach ($name in @('MSOLAP$PBIMCPTEST','PowerBIReportServer')) {
    $svc=Get-Service -Name $name
    if ($svc.Status -ne 'Running') {
        if ($Recover) { Start-Service -Name $name }
        $errors += "Service was not running: $name"
    }
}
foreach ($port in @($cfg.ssas_port)) {
    if (!(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)) { $errors += "Missing SSAS listener: $port" }
}
# Protocol checks include a catalog read. They never save, refresh or publish.
$python = Join-Path $Root 'services\powerbi-reportserver-mcp\.venv\Scripts\python.exe'
$savedPreference=$ErrorActionPreference
try {
    # Windows PowerShell 5 turns native stderr into ErrorRecords. Startup failures
    # must be recorded and retried by the bounded health loop, not abort it.
    $ErrorActionPreference='Continue'
    $probe = & $python (Join-Path $Root 'scripts\probe_background.py') --root $Root 2>&1
    $probeExit=$LASTEXITCODE
} finally { $ErrorActionPreference=$savedPreference }
if ($probeExit -ne 0) { $errors += 'Background MCP/catalog readiness check failed' }
$failures = if ($errors.Count) { 1 + [int]$previous.consecutive_failures } else { 0 }
$lastRecovery = if ($previous.last_recovery) { [double]$previous.last_recovery } else { 0 }
$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$recovered = $false
if ($Recover -and $failures -ge 2 -and ($now-$lastRecovery) -ge 600) {
    # Only the enrolled background task; never retry a business operation.
    Stop-ScheduledTask -TaskName $cfg.task
    Start-Sleep -Seconds 20
    Start-ScheduledTask -TaskName $cfg.task
    $lastRecovery=$now; $recovered=$true
}
$result = [ordered]@{time_utc=[DateTime]::UtcNow.ToString('o');healthy=($errors.Count -eq 0);errors=$errors;warnings=$warnings;
    consecutive_failures=$failures;last_recovery=$lastRecovery;recovery_requested=$recovered;desktop_required=$false}
$pending=$stateFile+'.tmp'
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $pending -Encoding UTF8
Move-Item -LiteralPath $pending -Destination $stateFile -Force
$result | ConvertTo-Json -Depth 5
if ($errors.Count) { exit 1 }
