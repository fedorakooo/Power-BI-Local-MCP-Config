[CmdletBinding()]
param(
    [switch]$Setup, [switch]$ValidateOnly, [switch]$Status, [switch]$Stop, [switch]$Diagnose,
    [switch]$AcceptMicrosoftEula, [switch]$NoDesktop, [switch]$ResetCredential,
    [string]$Python, [string]$CredentialPath,
    [string]$Config
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($root)) {
    $root = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if ([string]::IsNullOrWhiteSpace($Config)) {
    $Config = Join-Path $root 'deployment.local.json'
}
$service = Join-Path $root 'services\powerbi-reportserver-mcp'
$venvPython = Join-Path $service '.venv\Scripts\python.exe'
$runtime = Join-Path $root 'runtime'
$digest = [Security.Cryptography.SHA256]::Create()
try { $suffix = ([BitConverter]::ToString($digest.ComputeHash([Text.Encoding]::UTF8.GetBytes($root.ToLowerInvariant())))).Replace('-','').Substring(0,8) }
finally { $digest.Dispose() }
$taskName = 'Fedaraka-PowerBI-MCP-' + $suffix
if ($Diagnose) {
    & (Join-Path $root 'scripts\Diagnose-Startup.ps1') -Root $root -TaskName $taskName
    return
}

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments | ForEach-Object {
        $line = [string]$_
        if ($line.StartsWith('PBIMCP_PROGRESS ')) {
            $event = $line.Substring(16) | ConvertFrom-Json
            $id = if ($event.kind -eq 'download') { 12 } else { 11 }
            $parent = if ($id -eq 12) { 11 } else { 10 }
            if ($id -eq 11) { Write-Progress -Id 12 -Activity 'Download' -Completed }
            $activity = if ($event.activity) { [string]$event.activity } else { 'MCP readiness' }
            $percent = if ($event.total -gt 0) { [int][Math]::Min(100, [Math]::Floor(100 * $event.completed / $event.total)) } else { -1 }
            Write-Progress -Id $id -ParentId $parent -Activity $activity -Status $event.status -PercentComplete $percent
            Write-Host "  [$activity] $($event.status)"
        } else { Write-Output $_ }
    }
    if ($LASTEXITCODE -ne 0) { throw ('Command failed: ' + $Executable + ', exit=' + $LASTEXITCODE) }
}
function Stop-OwnedProcesses {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $taskName }
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -in @('python.exe','node.exe','caddy.exe') -and $_.CommandLine -and
        $_.CommandLine.IndexOf($service,[StringComparison]::OrdinalIgnoreCase) -ge 0
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
if ($Stop) { Stop-OwnedProcesses; Write-Host "Stopped this deployment: $taskName. Desktop remains open."; return }
if ($Status) {
    Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Select-Object TaskName,State
    if (Test-Path (Join-Path $runtime 'last-startup.json')) { Get-Content (Join-Path $runtime 'last-startup.json') }
    return
}
$script:progressStep = 0
$script:progressTotal = if ($ValidateOnly) { 2 } elseif ($Setup) { 16 } else { 4 }
$script:progressStage = ''
$script:progressActivity = if ($ValidateOnly) { 'Power BI MCP configuration check' } elseif ($Setup) { 'Power BI MCP setup' } else { 'Power BI MCP startup' }
function Start-DeploymentStage([string]$Name) {
    Write-Progress -Id 12 -Activity 'Download' -Completed
    Write-Progress -Id 11 -Activity 'Details' -Completed
    $script:progressStep++
    $script:progressStage = $Name
    $percent = [int][Math]::Floor(100 * ($script:progressStep - 1) / $script:progressTotal)
    Write-Host "[$script:progressStep/$script:progressTotal] $Name"
    Write-Progress -Id 10 -Activity $script:progressActivity -Status $Name -PercentComplete $percent
}
function Set-DeploymentDetail([int]$Completed, [int]$Total, [string]$Name) {
    $percent = if ($Total -gt 0) { [int][Math]::Floor(100 * $Completed / $Total) } else { -1 }
    Write-Progress -Id 12 -Activity 'Download' -Completed
    Write-Progress -Id 11 -ParentId 10 -Activity $script:progressStage -Status $Name -PercentComplete $percent
    Write-Host "  [$Completed/$Total] $Name"
}
function Invoke-Readiness([string]$Executable, [string[]]$Arguments) {
    try {
        Invoke-Checked $Executable $Arguments
    } finally { Write-Progress -Id 11 -Activity 'MCP readiness' -Completed }
}
try {
Start-DeploymentStage 'Read configuration and select Python'
Set-DeploymentDetail 0 3 'Load deployment settings'
if (!(Test-Path -LiteralPath $Config)) {
    if ($ValidateOnly) { $Config = Join-Path $root 'deployment.example.json' }
    elseif ($Setup) { Copy-Item -LiteralPath (Join-Path $root 'deployment.example.json') -Destination $Config }
    else { throw 'First run: .\Start-PowerBI.ps1 -Setup -AcceptMicrosoftEula' }
}
$Config = (Resolve-Path -LiteralPath $Config).Path
$settings = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
. (Join-Path $root 'scripts\Select-Python.ps1')
Set-DeploymentDetail 1 3 'Discover and probe installed Python runtimes'
$pythonInfo = Select-PowerBIPython -Requested $Python -ExistingVenv $venvPython
$Python = $pythonInfo.executable
Write-Host "Selected Python $($pythonInfo.version) x64: $Python"
if (Test-Path -LiteralPath $venvPython) {
    Set-DeploymentDetail 2 3 'Check the existing virtual environment'
    $environmentInfo = Get-PowerBIPython $venvPython
    if ($environmentInfo.base_executable -ne $pythonInfo.base_executable) {
        throw 'This deployment already uses a different Python installation. Omit -Python to reuse it, or use a new deployment folder to select another runtime.'
    }
}
Set-DeploymentDetail 3 3 'Python runtime selected'
$configure = Join-Path $root 'scripts\configure_deployment.py'
if ($ValidateOnly) {
    Start-DeploymentStage 'Validate deployment configuration and PBIX'
    Invoke-Checked $Python @($configure,'--root',$root,'--config',$Config,'--validate-only','--progress')
    Write-Progress -Id 10 -Activity $script:progressActivity -Status 'Configuration verified' -PercentComplete 100
    Write-Host 'Configuration check completed successfully.'
    return
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
if ($Setup) {
    Start-DeploymentStage 'Check prerequisites, configuration and source PBIX'
    Set-DeploymentDetail 0 3 'Check Windows administrator and Microsoft license acceptance'
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run initial -Setup in elevated PowerShell under the SAME Windows user who will operate Desktop.' }
    if (!$AcceptMicrosoftEula) { throw 'Review the Microsoft Desktop/Modeling MCP licenses; use -AcceptMicrosoftEula only after acceptance.' }
    Set-DeploymentDetail 1 3 'Validate settings, dependency locks and PBIX content'
    Invoke-Checked $Python @($configure,'--root',$root,'--config',$Config,'--validate-only','--progress')
    Set-DeploymentDetail 2 3 'Check Node.js and install or verify pnpm'
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if (!$nodeCommand) { throw 'Install Node.js LTS with npm, reopen PowerShell, then repeat Setup.' }
    if (!(Get-Command pnpm.cmd -ErrorAction SilentlyContinue)) {
        $npm = Get-Command npm.cmd -ErrorAction Stop
        Invoke-Checked $npm.Source @('install','--global','pnpm@11.25.0')
    }
    $pnpm = (Get-Command pnpm.cmd -ErrorAction Stop).Source
    if ((& $pnpm --version).Trim() -ne '11.25.0') { throw 'Install the pinned pnpm: npm install --global pnpm@11.25.0' }
    Set-DeploymentDetail 3 3 'Prerequisites verified'
    Start-DeploymentStage 'Protect runtime folders and stop this deployment'
    New-Item -ItemType Directory -Path $runtime,(Join-Path $service 'runtime') -Force | Out-Null
    $folderNumber = 0
    foreach ($folder in @($runtime,(Join-Path $service 'runtime'))) {
        Set-DeploymentDetail $folderNumber 3 'Apply private runtime folder permissions'
        Invoke-Checked 'icacls.exe' @($folder,'/inheritance:r','/grant:r',"${identity}:(OI)(CI)F",'SYSTEM:(OI)(CI)F')
        $folderNumber++
    }
    Set-DeploymentDetail 2 3 'Stop owned gateway processes'
    Stop-OwnedProcesses
    Set-DeploymentDetail 3 3 'Private runtime folders ready'
    Start-DeploymentStage 'Create or reuse Python virtual environment'
    Set-DeploymentDetail 0 1 'Create virtual environment, or reuse the installed environment'
    if (!(Test-Path -LiteralPath $venvPython)) { Invoke-Checked $Python @('-m','venv',(Join-Path $service '.venv')) }
    Set-DeploymentDetail 1 1 'Virtual environment ready'
    Start-DeploymentStage 'Install and verify Python dependencies'
    Set-DeploymentDetail 0 3 'Install pinned packages; pip shows individual download progress'
    Invoke-Checked $venvPython @('-m','pip','install','--progress-bar','on','-r',(Join-Path $service 'requirements-lock.txt'))
    Set-DeploymentDetail 1 3 'Check installed dependency constraints'
    Invoke-Checked $venvPython @('-m','pip','check')
    Set-DeploymentDetail 2 3 'Import Windows and MCP modules'
    Invoke-Checked $venvPython @((Join-Path $root 'scripts\probe_python.py'),'--check-dependencies','--progress')
    Set-DeploymentDetail 3 3 'Python dependencies verified'
    foreach ($dependency in @('modeling','gateway','bridge')) {
        Start-DeploymentStage "Install $dependency dependencies"
        Set-DeploymentDetail 0 1 'Resolve locked packages, download and link; pnpm reports package counts'
        Invoke-Checked $pnpm @('--dir',(Join-Path $service $dependency),'install','--frozen-lockfile','--reporter=default')
        Set-DeploymentDetail 1 1 "$dependency packages ready"
    }
    Start-DeploymentStage 'Install or verify ReportingServicesTools'
    Set-DeploymentDetail 0 1 'Check installed PowerShell module and install if missing'
    if (!(Get-Module -ListAvailable ReportingServicesTools | Where-Object { $_.Version -eq [version]'0.0.9.3' })) {
        Invoke-Checked 'powershell.exe' @('-NoProfile','-File',(Join-Path $service 'scripts\Install-ReportingServicesTools.ps1'))
    }
    Set-DeploymentDetail 1 1 'ReportingServicesTools ready'
    Start-DeploymentStage 'Install or verify Power BI Desktop RS (may take several minutes)'
    Invoke-Checked 'powershell.exe' @('-NoProfile','-File',(Join-Path $service 'scripts\Install-ReportServerDesktop.ps1'),'-AcceptEula')
    Start-DeploymentStage 'Download and verify Caddy'
    Invoke-Checked $venvPython @((Join-Path $service 'scripts\install_caddy.py'),'--progress')
    Start-DeploymentStage 'Generate host configuration and MCP client settings'
    Invoke-Checked $venvPython @($configure,'--root',$root,'--config',$Config,'--node',$nodeCommand.Source,'--progress')
    $serviceConfig = Join-Path $service 'config.local.json'
    Invoke-Checked 'icacls.exe' @($serviceConfig,'/inheritance:r','/grant:r',"${identity}:F",'SYSTEM:F')
    $credential = Join-Path $service 'runtime\pbirs-credential.xml'
    Start-DeploymentStage 'Configure Report Server credentials (complete the Windows dialog if shown)'
    Set-DeploymentDetail 0 1 'Reuse protected credentials, import them, or wait for the Windows credential dialog'
    if ($CredentialPath) {
        # Explicit same-user DPAPI import for local migration; never included in distributable ZIP.
        $savedCredential = Import-Clixml -LiteralPath (Resolve-Path -LiteralPath $CredentialPath).Path
        if ($savedCredential -isnot [Management.Automation.PSCredential]) { throw 'Not a Windows-protected PSCredential file' }
        $savedCredential | Export-Clixml -LiteralPath $credential
    } elseif ($ResetCredential -or !(Test-Path -LiteralPath $credential)) {
        Invoke-Checked 'powershell.exe' @('-NoProfile','-File',(Join-Path $service 'scripts\Set-PbirsCredential.ps1'),'-ConfigPath',$serviceConfig)
    }
    Set-DeploymentDetail 1 1 'Protected credential file ready'
    Start-DeploymentStage 'Register startup task and firewall rules'
    Set-DeploymentDetail 0 4 'Register the interactive startup task'
    $pythonScript = Join-Path $service 'scripts\run_supergateway.py'
    $action = New-ScheduledTaskAction -Execute $venvPython -Argument ('"' + $pythonScript + '"') -WorkingDirectory $service
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
    $taskPrincipal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $taskSettings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $taskPrincipal -Settings $taskSettings -Force -ErrorAction Stop | Out-Null
    Set-DeploymentDetail 1 4 'Replace firewall rules for this deployment'
    foreach ($rule in @($taskName,($taskName+'-Backends'))) {
        if (Get-NetFirewallRule -Name $rule -ErrorAction SilentlyContinue) { Remove-NetFirewallRule -Name $rule }
    }
    # Loopback does not need an inbound firewall exception; Windows rejects ::1 here.
    $remoteAddresses = @($settings.allowed_addresses | Where-Object { $_ -notmatch '^127\.' -and $_ -notmatch '^::1(?:/128)?$' })
    if ($remoteAddresses.Count) {
        New-NetFirewallRule -Name $taskName -DisplayName $taskName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $settings.frontend_port -RemoteAddress $remoteAddresses -Profile Any -ErrorAction Stop | Out-Null
    }
    $backendPorts = @(1..4 | ForEach-Object { [int]$settings.frontend_port + $_ })
    Set-DeploymentDetail 2 4 'Block remote access to all four backend ports'
    New-NetFirewallRule -Name ($taskName+'-Backends') -DisplayName ($taskName+' private backends') -Direction Inbound -Action Block -Protocol TCP -LocalPort $backendPorts -RemoteAddress Any -Profile Any -ErrorAction Stop | Out-Null
    Set-DeploymentDetail 3 4 'Record installation owner and configuration hash'
    @{identity=$identity; task=$taskName; config=$Config; settings_sha256=(Get-FileHash -LiteralPath $Config -Algorithm SHA256).Hash} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'installation.json') -Encoding UTF8
    Set-DeploymentDetail 4 4 'Task and firewall configuration complete'
}
if (!$Setup) { Start-DeploymentStage 'Verify existing installation and configuration' }
Set-DeploymentDetail 0 4 'Load the completed installation marker'
if (!(Test-Path -LiteralPath (Join-Path $runtime 'installation.json'))) { throw 'Initial Setup has not completed.' }
$installation = Get-Content (Join-Path $runtime 'installation.json') -Raw | ConvertFrom-Json
Set-DeploymentDetail 1 4 'Verify the Windows installation owner'
if ($installation.identity -ne $identity) { throw 'Use the Windows user who performed Setup; DPAPI and Desktop are user-scoped.' }
Set-DeploymentDetail 2 4 'Verify the configuration path'
if ($installation.config -ne $Config) { throw 'Configuration path changed. Rerun Setup with this config before starting.' }
Set-DeploymentDetail 3 4 'Verify the configuration hash'
if ($installation.settings_sha256 -ne (Get-FileHash -LiteralPath $Config -Algorithm SHA256).Hash) { throw 'Deployment settings changed. Rerun Setup to regenerate paths, ports and firewall rules.' }
Set-DeploymentDetail 4 4 'Installation identity and settings verified'
Start-DeploymentStage 'Start HTTP gateways'
Set-DeploymentDetail 0 1 'Check the frontend port and start or reuse the scheduled gateway task'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
if ($task.State -ne 'Running') {
    if (Get-NetTCPConnection -State Listen -LocalPort ([int]$settings.frontend_port) -ErrorAction SilentlyContinue) { throw 'Frontend port is occupied by another installation. Choose another frontend_port and rerun Setup.' }
    Start-ScheduledTask -TaskName $taskName
}
Set-DeploymentDetail 1 1 'Gateway start requested; verify service readiness next'
Start-DeploymentStage 'Check MCP services, Report Server and Desktop readiness'
$arguments = @((Join-Path $root 'scripts\check_runtime.py'),'--root',$root,'--config',$Config,'--progress')
if ($NoDesktop) { $arguments += '--no-desktop' }
Invoke-Readiness $venvPython $arguments
Write-Progress -Id 10 -Activity $script:progressActivity -Status 'All stages completed' -PercentComplete 100
Write-Host "Ready. Task: $taskName. Client configuration: $root\generated\codex-mcp.toml"
} catch {
    Write-Host "FAILED at stage [$script:progressStep/$script:progressTotal]: $script:progressStage" -ForegroundColor Red
    if ($script:progressStage -eq 'Check MCP services, Report Server and Desktop readiness') {
        & (Join-Path $root 'scripts\Diagnose-Startup.ps1') -Root $root -TaskName $taskName
    }
    throw
} finally {
    Write-Progress -Id 12 -Activity 'Download' -Completed
    Write-Progress -Id 11 -Activity 'Details' -Completed
    Write-Progress -Id 10 -Activity $script:progressActivity -Completed
}
