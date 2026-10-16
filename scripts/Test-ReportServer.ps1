param([string]$ConfigPath)
$ErrorActionPreference = 'Stop'
if (!$ConfigPath) {
    $ConfigPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'services\powerbi-reportserver-mcp\config.local.json'
}
$settings = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$portal = [uri]$settings.portal
Write-Host "Report Server portal: $($portal.AbsoluteUri)"
Write-Host "Catalog endpoint: $($portal.AbsoluteUri.TrimEnd('/'))/api/v2.0/PowerBIReports"
if ($portal.Host -like '*.example.com') {
    throw 'The example portal is still configured. Set your real portal in deployment.local.json and rerun Setup to regenerate the service configuration.'
}
$connection = New-Object Net.Sockets.TcpClient
try {
    $connect = $connection.ConnectAsync($portal.DnsSafeHost, $portal.Port)
    if (!$connect.Wait(5000)) { throw 'TCP connection timed out after 5 seconds' }
    Write-Host "TCP $($portal.DnsSafeHost):$($portal.Port): reachable"
} catch {
    Write-Host "TCP $($portal.DnsSafeHost):$($portal.Port): FAILED"
    throw
} finally { $connection.Dispose() }
$request = @{operation='list'; portal=$settings.portal; credential_path=$settings.credential_path} | ConvertTo-Json -Compress
$bridge = Join-Path (Split-Path -Parent $PSScriptRoot) 'services\powerbi-reportserver-mcp\pbirs_mcp\bridge.ps1'
$response = $request | & powershell.exe -NoProfile -NonInteractive -File $bridge
$bridgeExit = $LASTEXITCODE
$result = ($response -join "`n") | ConvertFrom-Json
if ($bridgeExit -ne 0 -or $result.error) {
    $result | Select-Object error,exception_type,http_status,network_status,upstream_code | Format-List | Out-Host
    exit 1
}
Write-Host "Catalog authentication passed; reports returned=$(@($result.reports).Count)"
