$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$name = 'STAIR-PowerBI-ReportServer-MCP'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoLogo -NoProfile -NonInteractive -File "' + (Join-Path $root 'scripts\Run-Server.ps1') + '"') `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
& (Join-Path $PSScriptRoot 'Stop-Local.ps1')
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Local authenticated Power BI Report Server MCP; starts at user logon.' -Force | Out-Null
Start-ScheduledTask -TaskName $name
Get-ScheduledTask -TaskName $name | Select-Object TaskName,State
