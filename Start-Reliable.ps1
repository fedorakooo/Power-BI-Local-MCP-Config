[CmdletBinding()]
param([switch]$Setup, [switch]$Restart, [switch]$Status,
    [Management.Automation.PSCredential]$Credential)
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$runtime=Join-Path $root 'runtime'
$service=Join-Path $root 'services\powerbi-reportserver-mcp'
$marker=Join-Path $runtime 'unattended.json'
if ($Status) {
    Get-Content -LiteralPath $marker
    Get-Content -LiteralPath (Join-Path $runtime 'background-health.json') -ErrorAction SilentlyContinue
    return
}
if ($Setup) {
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
    $installation=Get-Content (Join-Path $runtime 'installation.json') -Raw | ConvertFrom-Json
    if ($installation.identity -ne $identity) { throw 'Run under the original installation owner; credentials are protected with user-scoped DPAPI.' }
    if (!$Credential) { $Credential=Get-Credential -UserName $identity -Message 'Task Scheduler background startup: current installation owner' }
    if (!$Credential -or $Credential.UserName -ne $identity) { throw 'Credential must match the full installation owner identity.' }
    Write-Host '[1/4] Pin the existing lab SSAS port and enable automatic startup'
    $ssas=& (Join-Path $root 'scripts\Set-StableSSAS.ps1') | ConvertFrom-Json
    $task=$installation.task
    $desktopTask=$task+'-Desktop'
    $watchdogTask=$task+'-Health'
    $old=Get-ScheduledTask -TaskName $task
    if (!(Test-Path (Join-Path $runtime 'task-before-unattended.xml'))) {
        Export-ScheduledTask -TaskName $task | Set-Content (Join-Path $runtime 'task-before-unattended.xml') -Encoding UTF8
    }
    Write-Host '[2/4] Separate background server processes from interactive Desktop'
    Stop-ScheduledTask -TaskName $task
    Start-Sleep -Seconds 20
    $python=Join-Path $service '.venv\Scripts\pythonw.exe'
    $script=Join-Path $service 'scripts\run_supergateway.py'
    $action=New-ScheduledTaskAction -Execute $python -Argument ('"'+$script+'" --mode background') -WorkingDirectory $service
    $trigger=New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay='PT45S'
    $principal=New-ScheduledTaskPrincipal -UserId $identity -LogonType Password -RunLevel Limited
    $settings=New-ScheduledTaskSettingsSet -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $definition=New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Enrolled background Power BI MCP; no Desktop UI dependency'
    # The password goes directly to Task Scheduler's protected store, never a file/log.
    Register-ScheduledTask -TaskName $task -InputObject $definition -User $identity -Password $Credential.GetNetworkCredential().Password -Force | Out-Null
    $desktopAction=New-ScheduledTaskAction -Execute $python -Argument ('"'+$script+'" --mode desktop') -WorkingDirectory $service
    $desktopPrincipal=New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $desktopTask -Action $desktopAction -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $identity) -Principal $desktopPrincipal -Settings $settings -Force | Out-Null
    Write-Host '[3/4] Register bounded read-only checks and task recovery every five minutes'
    @{task=$task;desktop_task=$desktopTask;health_task=$watchdogTask;identity=$identity;ssas_port=$ssas.port;mode='background-plus-interactive-desktop'} | ConvertTo-Json | Set-Content $marker -Encoding UTF8
    $healthAction=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $root 'scripts\Test-BackgroundHealth.ps1')+'" -Root "'+$root+'" -Recover') -WorkingDirectory $root
    $healthTrigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $system=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $healthSettings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -MultipleInstances IgnoreNew -StartWhenAvailable
    Register-ScheduledTask -TaskName $watchdogTask -Action $healthAction -Trigger $healthTrigger -Principal $system -Settings $healthSettings -Force | Out-Null
    Start-ScheduledTask -TaskName $task
    Start-ScheduledTask -TaskName $desktopTask
} elseif ($Restart) {
    $cfg=Get-Content $marker -Raw | ConvertFrom-Json
    Stop-ScheduledTask -TaskName $cfg.task
    Start-Sleep -Seconds 20
    Start-ScheduledTask -TaskName $cfg.task
}
Write-Host '[4/4] Wait for background MCP and catalog readiness'
$ready=$false
for ($i=0;$i -lt 6;$i++) {
    & (Join-Path $root 'scripts\Test-BackgroundHealth.ps1') -Root $root
    if ($LASTEXITCODE -eq 0) { $ready=$true; break }
    Start-Sleep -Seconds 10
}
if (!$ready) { throw 'Background readiness failed. Inspect runtime/background-health.json and supervisor logs.' }
Write-Host 'Background MCP ready. Desktop UI still requires an unlocked owner session. SQL Developer remains test-only.'
