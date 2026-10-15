param([Parameter(Mandatory=$true)][string]$Root, [string]$TaskName)
$ErrorActionPreference = 'Continue'
$service = Join-Path $Root 'services\powerbi-reportserver-mcp'
Write-Host '=== Local gateway startup diagnostics (read-only) ==='
if (!$TaskName) {
    $marker = Join-Path $Root 'runtime\installation.json'
    if (Test-Path -LiteralPath $marker) { $TaskName = (Get-Content $marker -Raw | ConvertFrom-Json).task }
}
if ($TaskName) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        [pscustomobject]@{Task=$TaskName; State=$task.State.ToString(); LastResult=('0x{0:X8}' -f $info.LastTaskResult); LastRun=$info.LastRunTime; RunAs=$task.Principal.UserId} | Format-List | Out-Host
    } else { Write-Host "Task not found: $TaskName" }
}
$settingsPath = Join-Path $Root 'deployment.local.json'
if (Test-Path -LiteralPath (Join-Path $Root 'runtime\installation.json')) {
    $settingsPath = (Get-Content (Join-Path $Root 'runtime\installation.json') -Raw | ConvertFrom-Json).config
}
if (Test-Path -LiteralPath $settingsPath) {
    $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
    $ports = @(0..4 | ForEach-Object { [int]$settings.frontend_port + $_ })
    foreach ($port in $ports) {
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
        if (!$listeners.Count) { Write-Host "Port ${port}: NOT LISTENING" }
        foreach ($listener in $listeners) { Write-Host "Port ${port}: listening on $($listener.LocalAddress), PID=$($listener.OwningProcess)" }
    }
}
$required = @('.venv\Scripts\python.exe','gateway\node_modules\supergateway\dist\index.js','runtime\bin\caddy.exe','gateway\Caddyfile','gateway\servers.local.json')
foreach ($relative in $required) {
    $path = Join-Path $service $relative
    Write-Host "File present=$(Test-Path -LiteralPath $path): $relative"
}
$pathsFile = Join-Path $service 'runtime\gateway-paths.json'
if (Test-Path -LiteralPath $pathsFile) {
    $nodePath = (Get-Content $pathsFile -Raw | ConvertFrom-Json).node
    Write-Host "Node executable present=$(Test-Path -LiteralPath $nodePath): $nodePath"
}
$files = @('supervisor.log','caddy.log','fedaraka-powerbi-modeling.log','fedaraka-powerbi-reportserver.log','fedaraka-powerbi-authoring.log','fedaraka-powerbi-desktop.log')
foreach ($name in $files) {
    $path = Join-Path $service ('runtime\' + $name)
    if (Test-Path -LiteralPath $path) {
        Write-Host "--- Last 25 lines: $name ---"
        Get-Content -LiteralPath $path -Tail 25 | ForEach-Object {
            $line = $_ -replace '(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+=*','$1[REDACTED]'
            $line = $line -replace '(?i)((?:password|passwd|access_token|refresh_token|api[_-]?key|client_secret)\s*[=:]\s*)[^\s,;]+','$1[REDACTED]'
            Write-Host $line
        }
    } else { Write-Host "Log not created: $name" }
}
