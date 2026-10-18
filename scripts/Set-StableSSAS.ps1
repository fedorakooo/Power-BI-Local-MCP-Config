[CmdletBinding()]
param([int]$Port = 0)
$ErrorActionPreference = 'Stop'
# Only the explicitly installed synthetic lab instance is managed here.
$name = 'MSOLAP$PBIMCPTEST'
$svc = Get-CimInstance Win32_Service -Filter ("Name='" + $name + "'")
if (!$svc) { throw 'The enrolled PBIMCPTEST service is missing.' }
if ($svc.PathName -notmatch '-s\s+"([^"]+)"') { throw 'Cannot resolve enrolled SSAS configuration directory.' }
$file = Join-Path $Matches[1] 'msmdsrv.ini'
[xml]$xml = Get-Content -LiteralPath $file -Raw
$node = $xml.SelectSingleNode('/ConfigurationSettings/Port')
if (!$node) { throw 'SSAS Port setting is absent; no configuration was changed.' }
if (!$Port) {
    if ([int]$node.InnerText -gt 0) { $Port = [int]$node.InnerText }
    else {
        $ports = @(Get-NetTCPConnection -State Listen -OwningProcess $svc.ProcessId | Select-Object -ExpandProperty LocalPort -Unique)
        if ($ports.Count -ne 1) { throw 'Expected exactly one enrolled SSAS listener.' }
        $Port = $ports[0]
    }
}
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Invalid fixed SSAS port.' }
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -ne $svc.ProcessId }) { throw 'Selected port belongs to another process.' }
Set-Service -Name $name -StartupType Automatic
if ([int]$node.InnerText -ne $Port) {
    $backup = $file + '.mcp-' + (Get-Date -Format 'yyyyMMddHHmmss') + '.bak'
    Copy-Item -LiteralPath $file -Destination $backup
    $node.InnerText = [string]$Port
    $pending = $file + '.mcp-pending'
    $xml.Save($pending)
    Stop-Service -Name $name
    try { Move-Item -LiteralPath $pending -Destination $file -Force; Start-Service -Name $name }
    catch { Copy-Item -LiteralPath $backup -Destination $file -Force; Start-Service -Name $name; throw }
} else { Start-Service -Name $name }
$ready = $false
for ($i=0; $i -lt 60; $i++) {
    $current = Get-CimInstance Win32_Service -Filter ("Name='" + $name + "'")
    if (Get-NetTCPConnection -State Listen -LocalPort $Port -OwningProcess $current.ProcessId -ErrorAction SilentlyContinue) { $ready=$true; break }
    Start-Sleep -Seconds 1
}
if (!$ready) { throw 'Fixed SSAS listener did not become ready.' }
[pscustomobject]@{status='stable_ssas_verified';service=$name;port=$Port;startup='Automatic';configuration=$file} | ConvertTo-Json
