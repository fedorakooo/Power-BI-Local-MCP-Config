[CmdletBinding()]
param(
    [switch]$Setup, [switch]$ValidateOnly, [switch]$Status, [switch]$Stop,
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

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
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
    $script:progressStep++
    $script:progressStage = $Name
    $percent = [int][Math]::Floor(100 * ($script:progressStep - 1) / $script:progressTotal)
    Write-Host "[$script:progressStep/$script:progressTotal] $Name"
    Write-Progress -Id 10 -Activity $script:progressActivity -Status $Name -PercentComplete $percent
}
function Invoke-Readiness([string]$Executable, [string[]]$Arguments) {
    try {
        & $Executable @Arguments | ForEach-Object {
            $line = [string]$_
            if ($line.StartsWith('PBIMCP_PROGRESS ')) {
                $event = $line.Substring(16) | ConvertFrom-Json
                Write-Progress -Id 11 -ParentId 10 -Activity 'MCP readiness' -Status $event.status -PercentComplete ([int][Math]::Floor(100 * $event.completed / $event.total))
                Write-Host "  [MCP $($event.completed)/$($event.total)] $($event.status)"
            } else { Write-Output $_ }
        }
        if ($LASTEXITCODE -ne 0) { throw "Readiness check failed, exit=$LASTEXITCODE" }
    } finally { Write-Progress -Id 11 -Activity 'MCP readiness' -Completed }
}
try {
Start-DeploymentStage 'Read configuration and select Python'
if (!(Test-Path -LiteralPath $Config)) {
    if ($ValidateOnly) { $Config = Join-Path $root 'deployment.example.json' }
    elseif ($Setup) { Copy-Item -LiteralPath (Join-Path $root 'deployment.example.json') -Destination $Config }
    else { throw 'First run: .\Start-PowerBI.ps1 -Setup -AcceptMicrosoftEula' }
}
$Config = (Resolve-Path -LiteralPath $Config).Path
$settings = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
. (Join-Path $root 'scripts\Select-Python.ps1')
$pythonInfo = Select-PowerBIPython -Requested $Python -ExistingVenv $venvPython
$Python = $pythonInfo.executable
Write-Host "Selected Python $($pythonInfo.version) x64: $Python"
if (Test-Path -LiteralPath $venvPython) {
    $environmentInfo = Get-PowerBIPython $venvPython
    if ($environmentInfo.base_executable -ne $pythonInfo.base_executable) {
        throw 'This deployment already uses a different Python installation. Omit -Python to reuse it, or use a new deployment folder to select another runtime.'
    }
}
$configure = Join-Path $root 'scripts\configure_deployment.py'
if ($ValidateOnly) {
    Start-DeploymentStage 'Validate deployment configuration and PBIX'
    Invoke-Checked $Python @($configure,'--root',$root,'--config',$Config,'--validate-only')
    Write-Progress -Id 10 -Activity $script:progressActivity -Status 'Configuration verified' -PercentComplete 100
    Write-Host 'Configuration check completed successfully.'
    return
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
if ($Setup) {
    Start-DeploymentStage 'Check administrator, licenses, Node.js and pnpm'
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run initial -Setup in elevated PowerShell under the SAME Windows user who will operate Desktop.' }
    if (!$AcceptMicrosoftEula) { throw 'Review the Microsoft Desktop/Modeling MCP licenses; use -AcceptMicrosoftEula only after acceptance.' }
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if (!$nodeCommand) { throw 'Install Node.js LTS with npm, reopen PowerShell, then repeat Setup.' }
    if (!(Get-Command pnpm.cmd -ErrorAction SilentlyContinue)) {
        $npm = Get-Command npm.cmd -ErrorAction Stop
        Invoke-Checked $npm.Source @('install','--global','pnpm@11.25.0')
    }
    $pnpm = (Get-Command pnpm.cmd -ErrorAction Stop).Source
    if ((& $pnpm --version).Trim() -ne '11.25.0') { throw 'Install the pinned pnpm: npm install --global pnpm@11.25.0' }
    Start-DeploymentStage 'Protect runtime folders and stop this deployment'
    New-Item -ItemType Directory -Path $runtime,(Join-Path $service 'runtime') -Force | Out-Null
    foreach ($folder in @($runtime,(Join-Path $service 'runtime'))) {
        Invoke-Checked 'icacls.exe' @($folder,'/inheritance:r','/grant:r',"${identity}:(OI)(CI)F",'SYSTEM:(OI)(CI)F')
    }
    Stop-OwnedProcesses
    Start-DeploymentStage 'Create or reuse Python virtual environment'
    if (!(Test-Path -LiteralPath $venvPython)) { Invoke-Checked $Python @('-m','venv',(Join-Path $service '.venv')) }
    Start-DeploymentStage 'Install and verify Python dependencies'
    Invoke-Checked $venvPython @('-m','pip','install','-r',(Join-Path $service 'requirements-lock.txt'))
    Invoke-Checked $venvPython @('-m','pip','check')
    Invoke-Checked $venvPython @((Join-Path $root 'scripts\probe_python.py'),'--check-dependencies')
    foreach ($dependency in @('modeling','gateway','bridge')) {
        Start-DeploymentStage "Install $dependency dependencies"
        Invoke-Checked $pnpm @('--dir',(Join-Path $service $dependency),'install','--frozen-lockfile')
    }
    Start-DeploymentStage 'Install or verify ReportingServicesTools'
    if (!(Get-Module -ListAvailable ReportingServicesTools | Where-Object { $_.Version -eq [version]'0.0.9.3' })) {
        Invoke-Checked 'powershell.exe' @('-NoProfile','-File',(Join-Path $service 'scripts\Install-ReportingServicesTools.ps1'))
    }
    Start-DeploymentStage 'Install or verify Power BI Desktop RS (may take several minutes)'
    Invoke-Checked 'powershell.exe' @('-NoProfile','-File',(Join-Path $service 'scripts\Install-ReportServerDesktop.ps1'),'-AcceptEula')
    Start-DeploymentStage 'Download and verify Caddy'
    Invoke-Checked $venvPython @((Join-Path $service 'scripts\install_caddy.py'))
    Start-DeploymentStage 'Generate host configuration and MCP client settings'
    Invoke-Checked $venvPython @($configure,'--root',$root,'--config',$Config,'--node',$nodeCommand.Source)
    $serviceConfig = Join-Path $service 'config.local.json'
    Invoke-Checked 'icacls.exe' @($serviceConfig,'/inheritance:r','/grant:r',"${identity}:F",'SYSTEM:F')
    $credential = Join-Path $service 'runtime\pbirs-credential.xml'
    Start-DeploymentStage 'Configure Report Server credentials (complete the Windows dialog if shown)'
    if ($CredentialPath) {
        # Explicit same-user DPAPI import for local migration; never included in distributable ZIP.
        $savedCredential = Import-Clixml -LiteralPath (Resolve-Path -LiteralPath $CredentialPath).Path
        if ($savedCredential -isnot [Management.Automation.PSCredential]) { throw 'Not a Windows-protected PSCredential file' }
        $savedCredential | Export-Clixml -LiteralPath $credential
    } elseif ($ResetCredential -or !(Test-Path -LiteralPath $credential)) {
        Invoke-Checked 'powershell.exe' @('-NoProfile','-File',(Join-Path $service 'scripts\Set-PbirsCredential.ps1'),'-ConfigPath',$serviceConfig)
    }
    Start-DeploymentStage 'Register startup task and firewall rules'
    $pythonScript = Join-Path $service 'scripts\run_supergateway.py'
    $action = New-ScheduledTaskAction -Execute $venvPython -Argument ('"' + $pythonScript + '"') -WorkingDirectory $service
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
    $taskPrincipal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $taskSettings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $taskPrincipal -Settings $taskSettings -Force -ErrorAction Stop | Out-Null
    foreach ($rule in @($taskName,($taskName+'-Backends'))) {
        if (Get-NetFirewallRule -Name $rule -ErrorAction SilentlyContinue) { Remove-NetFirewallRule -Name $rule }
    }
    # Loopback does not need an inbound firewall exception; Windows rejects ::1 here.
    $remoteAddresses = @($settings.allowed_addresses | Where-Object { $_ -notmatch '^127\.' -and $_ -notmatch '^::1(?:/128)?$' })
    if ($remoteAddresses.Count) {
        New-NetFirewallRule -Name $taskName -DisplayName $taskName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $settings.frontend_port -RemoteAddress $remoteAddresses -Profile Any -ErrorAction Stop | Out-Null
    }
    $backendPorts = @(1..4 | ForEach-Object { [int]$settings.frontend_port + $_ })
    New-NetFirewallRule -Name ($taskName+'-Backends') -DisplayName ($taskName+' private backends') -Direction Inbound -Action Block -Protocol TCP -LocalPort $backendPorts -RemoteAddress Any -Profile Any -ErrorAction Stop | Out-Null
    @{identity=$identity; task=$taskName; config=$Config; settings_sha256=(Get-FileHash -LiteralPath $Config -Algorithm SHA256).Hash} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'installation.json') -Encoding UTF8
}
if (!$Setup) { Start-DeploymentStage 'Verify existing installation and configuration' }
if (!(Test-Path -LiteralPath (Join-Path $runtime 'installation.json'))) { throw 'Initial Setup has not completed.' }
$installation = Get-Content (Join-Path $runtime 'installation.json') -Raw | ConvertFrom-Json
if ($installation.identity -ne $identity) { throw 'Use the Windows user who performed Setup; DPAPI and Desktop are user-scoped.' }
if ($installation.config -ne $Config) { throw 'Configuration path changed. Rerun Setup with this config before starting.' }
if ($installation.settings_sha256 -ne (Get-FileHash -LiteralPath $Config -Algorithm SHA256).Hash) { throw 'Deployment settings changed. Rerun Setup to regenerate paths, ports and firewall rules.' }
Start-DeploymentStage 'Start HTTP gateways'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
if ($task.State -ne 'Running') {
    if (Get-NetTCPConnection -State Listen -LocalPort ([int]$settings.frontend_port) -ErrorAction SilentlyContinue) { throw 'Frontend port is occupied by another installation. Choose another frontend_port and rerun Setup.' }
    Start-ScheduledTask -TaskName $taskName
}
Start-DeploymentStage 'Check MCP services, Report Server and Desktop readiness'
$arguments = @((Join-Path $root 'scripts\check_runtime.py'),'--root',$root,'--config',$Config,'--progress')
if ($NoDesktop) { $arguments += '--no-desktop' }
Invoke-Readiness $venvPython $arguments
Write-Progress -Id 10 -Activity $script:progressActivity -Status 'All stages completed' -PercentComplete 100
Write-Host "Ready. Task: $taskName. Client configuration: $root\generated\codex-mcp.toml"
} catch {
    Write-Host "FAILED at stage [$script:progressStep/$script:progressTotal]: $script:progressStage" -ForegroundColor Red
    throw
} finally {
    Write-Progress -Id 10 -Activity $script:progressActivity -Completed
}
