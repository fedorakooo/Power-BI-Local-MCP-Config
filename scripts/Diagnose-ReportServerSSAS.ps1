param(
    [string]$Root,
    [string]$Report = 'staging',
    [ValidatePattern('^[0-9a-fA-F-]{36}$')][string]$RequestId,
    [string]$PowerShell7
)
# Run locally under Windows PowerShell 5.1: the stored credential uses its owner's DPAPI.
$ErrorActionPreference = 'Stop'
if (!$Root) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path -LiteralPath $Root).Path
$serviceRoot = Join-Path $Root 'services\powerbi-reportserver-mcp'
$config = Get-Content -LiteralPath (Join-Path $serviceRoot 'config.local.json') -Raw | ConvertFrom-Json
$reportId = [string]$config.reports.PSObject.Properties[$Report].Value
$guid = [guid]::Empty
if (![guid]::TryParse($reportId, [ref]$guid)) { throw 'Report alias is not enrolled with a GUID.' }
Write-Host '=== Read-only Report Server / SSAS diagnostics; no restart, permission change or publish ==='
$services = @(Get-CimInstance Win32_Service | Where-Object {
    $_.Name -eq 'MSOLAP$PBIMCPTEST' -or $_.Name -eq 'PowerBIReportServer'
})
$services | Select-Object Name,State,StartName,ProcessId | Format-Table -AutoSize | Out-Host
$ssas = $services | Where-Object Name -eq 'MSOLAP$PBIMCPTEST'
$ports = @()
if ($ssas -and $ssas.ProcessId -gt 0) {
    $ports = @(Get-NetTCPConnection -State Listen -OwningProcess $ssas.ProcessId -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty LocalPort -Unique)
}
Write-Host ('Current test SSAS listener ports: ' + ($ports -join ','))
Write-Host '=== Published report data sources (secrets excluded) ==='
$common = @{TimeoutSec=30;MaximumRedirection=0}
if ($config.credential_path) { $common.Credential = Import-Clixml -LiteralPath $config.credential_path }
else { $common.UseDefaultCredentials = $true }
try {
    $uri = $config.portal.TrimEnd('/') + '/api/v2.0/PowerBIReports(' + $guid + ')/DataSources'
    $data = Invoke-RestMethod -Uri $uri @common
    foreach ($source in $data.value) {
        $builder = New-Object System.Data.Common.DbConnectionStringBuilder
        $builder.ConnectionString = $source.ConnectionString
        [pscustomobject]@{
            Server=$builder['Data Source'];Database=$builder['Initial Catalog'];
            AuthType=$source.DataModelDataSource.AuthType;
            CredentialRetrieval=$source.CredentialRetrieval;
            ConnectionOverridden=$source.IsConnectionStringOverridden
        } | Format-List | Out-Host
        if ([string]$builder['Data Source'] -match '^localhost:(\d+)$') {
            $matchesCurrentPort = [int]$Matches[1] -in $ports
            Write-Host "Published port matches current test SSAS listener: $matchesCurrentPort"
        }
    }
} catch { Write-Host ('Catalog diagnostic failed: ' + $_.Exception.GetType().Name) }
Write-Host '=== SSAS DAX and database roles under this operator identity ==='
if ($ports.Count -eq 1) {
    . (Join-Path $PSScriptRoot 'Select-HeadlessPowerShell.ps1')
    $pwsh = Select-HeadlessPowerShell -Root $Root -Requested $PowerShell7
    & $pwsh -NoProfile -NonInteractive -File (Join-Path $PSScriptRoot 'Test-HeadlessSSAS.ps1') `
        -Server ('localhost:' + $ports[0]) -ClientDirectory (Join-Path $Root 'tools\headless\as-client') -InspectRoles
    Write-Host "SSAS operator check exit code: $LASTEXITCODE (does not test report viewer access)"
} else { Write-Host 'No single running test SSAS port found; skipping DAX check.' }
Write-Host '=== Bounded Report Server log matches ==='
$logRoot = Join-Path $env:ProgramFiles 'Microsoft Power BI Report Server\PBIRS\LogFiles'
if (!(Test-Path -LiteralPath $logRoot)) { Write-Host 'Default PBIRS LogFiles directory not found.'; return }
$pattern = 'AnalysisServices|Analysis Services|PowerBIMcpHeadlessLab|SSPI|Logon failure'
if ($RequestId) { $pattern = [regex]::Escape($RequestId) + '|' + $pattern }
$files = Get-ChildItem -LiteralPath $logRoot -File -Filter '*.log' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 5
foreach ($file in $files) {
    $lines = @(Get-Content -LiteralPath $file.FullName -Tail 500 |
        Select-String -Pattern $pattern | Select-Object -Last 12)
    if ($lines.Count) { Write-Host ('--- ' + $file.Name + ' ---') }
    foreach ($line in $lines) {
        $safe = $line.Line -replace '(?i)((?:password|pwd|secret|token|authorization)\s*[=:]\s*)[^;,\s]+', '$1[REDACTED]'
        Write-Host $safe.Substring(0, [Math]::Min($safe.Length,1500))
    }
}
