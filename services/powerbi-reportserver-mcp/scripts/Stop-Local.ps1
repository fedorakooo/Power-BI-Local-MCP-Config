$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$config = Join-Path $root 'config.local.json'
if (Get-ScheduledTask -TaskName 'STAIR-PowerBI-ReportServer-MCP' -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName 'STAIR-PowerBI-ReportServer-MCP'
}
# Windows venv launchers can leave an interpreter child after Task Scheduler stops the parent.
# Stop only this installation's server processes, identified by its exact absolute config path.
$owned = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains('pbirs_mcp.server') -and $_.CommandLine.Contains($config)
})
foreach ($process in $owned) { Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue }
