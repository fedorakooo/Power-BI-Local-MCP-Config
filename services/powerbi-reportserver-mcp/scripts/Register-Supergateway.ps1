param([string[]]$AllowedAddresses)
$ErrorActionPreference = 'Stop'
if (!$AllowedAddresses) { throw 'Provide the STAIR gateway pod and node addresses' }
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$node = (Get-Command node -ErrorAction Stop).Source
@{ node = $node } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'runtime\gateway-paths.json') -Encoding UTF8
$name = 'STAIR-Fedaraka-PowerBI-Supergateway'
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $name }
$processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and ($_.CommandLine.IndexOf((Join-Path $root 'scripts\run_supergateway.py'),[StringComparison]::OrdinalIgnoreCase) -ge 0 -or
    $_.CommandLine.IndexOf((Join-Path $root 'gateway\servers.local.json'),[StringComparison]::OrdinalIgnoreCase) -ge 0)
})
foreach ($owned in $processes) { Stop-Process -Id $owned.ProcessId -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and ($_.Name -eq 'node.exe' -or $_.Name -eq 'caddy.exe') -and $_.CommandLine.IndexOf($root,[StringComparison]::OrdinalIgnoreCase) -ge 0
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$action = New-ScheduledTaskAction -Execute (Join-Path $root '.venv\Scripts\python.exe') `
    -Argument ('"' + (Join-Path $root 'scripts\run_supergateway.py') + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description "Fedaraka's IP-restricted Power BI Modeling and Report Server Supergateway HTTP endpoints; no API-key auth for pilot." -Force | Out-Null
$firewallName = 'STAIR-Fedaraka-PowerBI-Supergateway'
if (Get-NetFirewallRule -Name $firewallName -ErrorAction SilentlyContinue) { Remove-NetFirewallRule -Name $firewallName }
New-NetFirewallRule -Name $firewallName -DisplayName "Fedaraka Power BI MCP - STAIR dev gateway only" `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8012 -RemoteAddress $AllowedAddresses -Profile Any | Out-Null
$backendRule = 'STAIR-Fedaraka-PowerBI-Backend-Block'
if (Get-NetFirewallRule -Name $backendRule -ErrorAction SilentlyContinue) { Remove-NetFirewallRule -Name $backendRule }
New-NetFirewallRule -Name $backendRule -DisplayName 'Block external access to internal Supergateway backends' `
    -Direction Inbound -Action Block -Protocol TCP -LocalPort 8013,8014,8015,8016 -RemoteAddress Any -Profile Any | Out-Null
Start-ScheduledTask -TaskName $name
Get-ScheduledTask -TaskName $name | Select-Object TaskName,State
