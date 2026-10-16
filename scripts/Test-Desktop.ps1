param([string]$ServiceRoot)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$service = if ($ServiceRoot) { (Resolve-Path -LiteralPath $ServiceRoot).Path } else { Join-Path $root 'services\powerbi-reportserver-mcp' }
Write-Host '=== Desktop processes and visible main-window titles (read-only) ==='
$processes = @(Get-Process PBIDesktop -ErrorAction SilentlyContinue)
if ($processes.Count) { $processes | Select-Object Id,SessionId,MainWindowTitle,Path | Format-List | Out-Host }
else { Write-Host 'No Power BI Desktop process found.' }
$config = Get-Content (Join-Path $service 'config.local.json') -Raw | ConvertFrom-Json
Write-Host '=== Enrolled report paths ==='
$config.desktop_reports | Format-List | Out-Host
$node = (Get-Content (Join-Path $service 'runtime\gateway-paths.json') -Raw | ConvertFrom-Json).node
$cli = Join-Path $service 'bridge\node_modules\@microsoft\powerbi-desktop-bridge-cli\dist\cli.js'
Write-Host '=== Official Desktop Bridge status ==='
& $node $cli status
if ($LASTEXITCODE -ne 0) { throw "Desktop Bridge status failed, exit=$LASTEXITCODE" }
