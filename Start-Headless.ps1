[CmdletBinding()]
param(
    [switch]$Setup, [switch]$Restart, [switch]$Stop, [switch]$Status,
    [switch]$InstallTestSSAS, [switch]$AcceptSqlServerLicense, [switch]$TestBuild,
    [switch]$WithPowerBIStack, [switch]$AcceptMicrosoftEula,
    [string]$Python, [string]$PowerShell7, [string]$Config, [string]$PowerBIConfig
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (!$Config) { $Config = Join-Path $root 'headless.deployment.local.json' }
$serviceRoot = Join-Path $root 'services\powerbi-reportserver-mcp'
$runtime = Join-Path $root 'runtime\headless'
$tools = Join-Path $root 'tools\headless'
$venv = Join-Path $runtime '.venv\Scripts\python.exe'
$pidFile = Join-Path $runtime 'process.json'
$serviceConfig = Join-Path $root 'headless\config.local.json'
function Step([int]$Number, [string]$Text) {
    Write-Host "[$Number/7] $Text"
    Write-Progress -Id 71 -Activity 'Configure and start Power BI headless MCP' -Status $Text -PercentComplete (($Number-1)*100/7)
}
function Run([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Executable (exit $LASTEXITCODE)" }
}
function Fetch([string]$Url, [string]$Destination, [string]$Hash='', [string]$Algorithm='SHA256') {
    if (Test-Path -LiteralPath $Destination) {
        if (!$Hash -or (Get-FileHash -LiteralPath $Destination -Algorithm $Algorithm).Hash -eq $Hash) { return }
        throw "Cached download hash mismatch: $Destination. Remove this file and retry."
    }
    Write-Host "Download: $Url"
    $pending = $Destination + '.partial'
    try {
        Invoke-WebRequest -Uri $Url -OutFile $pending -UseBasicParsing
        if ($Hash -and (Get-FileHash -LiteralPath $pending -Algorithm $Algorithm).Hash -ne $Hash) { throw "Download hash mismatch: $Url" }
        Move-Item -LiteralPath $pending -Destination $Destination
    } finally { if (Test-Path -LiteralPath $pending) { Remove-Item -LiteralPath $pending } }
}
function OwnedProcess {
    if (!(Test-Path -LiteralPath $pidFile)) { return $null }
    $saved = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$saved.pid) -ErrorAction SilentlyContinue
    if ($process -and $process.ExecutablePath -eq $venv -and
        $process.CommandLine.Contains($serviceConfig) -and
        $process.CommandLine.Contains('pbirs_mcp.headless_build') -and
        $process.CreationDate.ToUniversalTime().Ticks.ToString() -eq [string]$saved.creation_ticks) { return $process }
    return $null
}
function StopOwned {
    $owned = OwnedProcess
    if ($owned) { Stop-Process -Id $owned.ProcessId -ErrorAction Stop; Write-Host 'Stopped this installation headless MCP.' }
    if (Test-Path -LiteralPath $pidFile) { Remove-Item -LiteralPath $pidFile }
}
if ($Stop) {
    if ($WithPowerBIStack) { & (Join-Path $root 'Start-PowerBI.ps1') -Stop; return }
    StopOwned; return
}
if ($Status) {
    $managedSettings = Join-Path $serviceRoot 'runtime\headless-supervisor.json'
    if (Test-Path -LiteralPath $managedSettings) {
        $managedPort = [int](Get-Content -LiteralPath $managedSettings -Raw | ConvertFrom-Json).port
        [pscustomobject]@{mode='gateway-supervised';port=$managedPort;
            listening=[bool](Get-NetTCPConnection -State Listen -LocalPort $managedPort -ErrorAction SilentlyContinue);
            logs=(Join-Path $serviceRoot 'runtime\stair-powerbi-headless.log')} | ConvertTo-Json
        return
    }
    $owned = OwnedProcess
    [pscustomobject]@{running=[bool]$owned;pid=$(if ($owned) {$owned.ProcessId} else {$null});config=$serviceConfig;logs=$runtime} | ConvertTo-Json
    return
}
try {
    Step 1 'Read deployment settings and check prerequisites'
    if (!(Test-Path -LiteralPath $Config)) {
        if (!$Setup) { throw 'Run with -Setup first.' }
        Copy-Item -LiteralPath (Join-Path $root 'headless.deployment.example.json') -Destination $Config
    }
    $settings = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
    if ($settings.mode -notin @('lab','existing')) { throw 'mode must be lab or existing.' }
    if ([int]$settings.http_port -lt 1024 -or [int]$settings.http_port -gt 65535) { throw 'http_port must be 1024..65535.' }
    if ($settings.project -notmatch '^[A-Za-z0-9_-]{1,60}$') { throw 'Invalid project alias.' }
    if ($settings.mode -eq 'lab') {
        if (!(Get-Service -Name 'MSOLAP$PBIMCPTEST' -ErrorAction SilentlyContinue)) {
            if (!$InstallTestSSAS -or !$AcceptSqlServerLicense) { throw 'Test SSAS is missing. Review Microsoft SQL Server Developer license, then use -Setup -InstallTestSSAS -AcceptSqlServerLicense in elevated PowerShell. Developer is non-production only.' }
            $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
            if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Open elevated PowerShell to install the test SSAS instance.' }
        }
    }
    if ($WithPowerBIStack) {
        if (!$PowerBIConfig) { $PowerBIConfig = Join-Path $root 'deployment.local.json' }
        if (!(Test-Path -LiteralPath $PowerBIConfig)) { throw 'Create deployment.local.json from deployment.example.json for the existing Power BI stack first.' }
        $stack = Get-Content -LiteralPath $PowerBIConfig -Raw | ConvertFrom-Json
        if (($stack | ConvertTo-Json -Depth 20) -match 'report-server.example.com') { throw 'Set the real Report Server portal before -WithPowerBIStack.' }
        if ([int]$settings.http_port -in ([int]$stack.frontend_port..([int]$stack.frontend_port+4))) { throw 'Headless HTTP port overlaps Power BI gateway ports.' }
    }
    if ($settings.mode -eq 'lab') {
        . (Join-Path $root 'scripts\Select-HeadlessPowerShell.ps1')
        $PowerShell7 = Select-HeadlessPowerShell -Root $root -Requested $PowerShell7 -AllowDownload:$Setup
        Write-Host "Selected PowerShell: $PowerShell7"
    }
    . (Join-Path $root 'scripts\Select-Python.ps1')
    $selected = Select-PowerBIPython -Requested $Python -ExistingVenv $venv
    New-Item -ItemType Directory -Path $runtime,$tools -Force | Out-Null
    if ($Setup) {
        Step 2 'Create Python environment and install locked dependencies'
        if (!(Test-Path -LiteralPath $venv)) { Run $selected.executable @('-m','venv',(Join-Path $runtime '.venv')) }
        Run $venv @('-m','pip','install','--disable-pip-version-check','--progress-bar','on','-r',(Join-Path $serviceRoot 'requirements-lock.txt'))
        Run $venv @('-m','pip','check')
        Step 3 'Download pinned compiler, .NET runtime and SSAS clients'
        $packages = Join-Path $tools 'packages'
        New-Item -ItemType Directory -Path $packages -Force | Out-Null
        $compilerZip = Join-Path $packages 'pbi-tools-1.2.0.zip'
        Fetch 'https://github.com/pbi-tools/pbi-tools/releases/download/1.2.0/pbi-tools.core.1.2.0_win-x64.zip' $compilerZip '41a7d14421d9797ecb522bc7d226cd2eaca37c59be0c7e1f4d25254fec467425'
        Write-Progress -Id 72 -ParentId 71 -Activity 'Headless dependencies' -Status 'Extract compiler (AGPL-3.0)' -PercentComplete 15
        Expand-Archive -LiteralPath $compilerZip -DestinationPath (Join-Path $tools 'compiler') -Force
        $dotnetZip = Join-Path $packages 'dotnet-8.0.32.zip'
        Fetch 'https://builds.dotnet.microsoft.com/dotnet/Runtime/8.0.32/dotnet-runtime-8.0.32-win-x64.zip' $dotnetZip 'f0349e793d8081c682c01d736db695c9c1ec268c6173648913543db219e44cbf2e952c7ef94fc37946b0f2bb95ca1898d972a43591b8e44d5a1659f4911904c0' 'SHA512'
        Expand-Archive -LiteralPath $dotnetZip -DestinationPath (Join-Path $tools 'dotnet') -Force
        $client = Join-Path $tools 'as-client'
        New-Item -ItemType Directory -Path $client -Force | Out-Null
        $index = 0
        foreach ($package in @(@('microsoft.analysisservices','19.118.3'),@('microsoft.analysisservices.adomdclient','19.118.3'),@('microsoft.identity.client','4.83.3'),@('microsoft.identity.client.broker','4.83.3'))) {
            $index++
            Write-Progress -Id 72 -ParentId 71 -Activity 'Headless dependencies' -Status ("SSAS client package $index/4: " + $package[0]) -PercentComplete (30+$index*17)
            $name = $package[0]; $version = $package[1]
            $archive = Join-Path $packages ($name + '-' + $version + '.zip')
            Fetch "https://api.nuget.org/v3-flatcontainer/$name/$version/$name.$version.nupkg" $archive
            $unpack = Join-Path $packages ($name + '-' + $version)
            Expand-Archive -LiteralPath $archive -DestinationPath $unpack -Force
            $framework = @('net8.0','net6.0','netstandard2.0') | Where-Object { Test-Path -LiteralPath (Join-Path $unpack ('lib\' + $_)) } | Select-Object -First 1
            if (!$framework) { throw "No compatible library in $name" }
            Get-ChildItem -LiteralPath (Join-Path $unpack ('lib\' + $framework)) -Filter '*.dll' | Copy-Item -Destination $client -Force
        }
        Write-Progress -Id 72 -Completed -Activity 'Headless dependencies'
    } else {
        if (!(Test-Path -LiteralPath $venv) -or !(Test-Path -LiteralPath $serviceConfig)) { throw 'Run -Setup first.' }
        Step 2 'Reuse installed Python environment'
        Step 3 'Reuse pinned headless dependencies'
    }
    Step 4 'Prepare or verify the SSAS endpoint'
    $server = [string]$settings.ssas_server
    if ($settings.mode -eq 'lab') {
        $serviceName = 'MSOLAP$PBIMCPTEST'
        if (!(Get-Service -Name $serviceName -ErrorAction SilentlyContinue)) {
            if (!$InstallTestSSAS -or !$AcceptSqlServerLicense) { throw 'Test SSAS is missing. Review Microsoft SQL Server Developer license, then use -Setup -InstallTestSSAS -AcceptSqlServerLicense in elevated PowerShell. Developer is non-production only.' }
            $bootstrap = Join-Path $tools 'SQL2025-EnterpriseDeveloper.exe'
            Fetch 'https://aka.ms/sql2025EnterpriseDev' $bootstrap
            $signature = Get-AuthenticodeSignature -LiteralPath $bootstrap
            if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'SQL bootstrap signature validation failed.' }
            $media = Join-Path $tools 'sql-media'
            New-Item -ItemType Directory -Path $media -Force | Out-Null
            $download = Start-Process -FilePath $bootstrap -ArgumentList @('/ACTION=Download','/MEDIATYPE=ISO',('/MEDIAPATH="'+$media+'"'),'/QUIET') -WindowStyle Hidden -PassThru
            while (!$download.WaitForExit(1000)) { Write-Progress -Id 72 -ParentId 71 -Activity 'Download SQL Server Developer media' -Status 'Downloading official installation media' -PercentComplete -1 }
            Write-Progress -Id 72 -Activity 'Download SQL Server Developer media' -Completed
            if ($download.ExitCode -ne 0) { throw "SQL media download failed: $($download.ExitCode)" }
            $iso = Get-ChildItem -LiteralPath $media -Filter '*.iso' | Select-Object -First 1
            if (!$iso) { throw 'SQL media ISO was not downloaded.' }
            $disk = Mount-DiskImage -ImagePath $iso.FullName -PassThru
            try {
                $volume = $disk | Get-Volume
                & (Join-Path $root 'scripts\Install-TestSSAS.ps1') -MediaRoot ($volume.DriveLetter + ':\') -AcceptSqlServerLicense
            } finally { Dismount-DiskImage -ImagePath $iso.FullName | Out-Null }
        }
        Start-Service -Name $serviceName
        for ($attempt=1; $attempt -le 30; $attempt++) {
            $svc = Get-CimInstance Win32_Service -Filter ("Name='" + $serviceName + "'")
            $listeners = @()
            if ($svc.ProcessId -gt 0) { $listeners = @(Get-NetTCPConnection -State Listen -OwningProcess $svc.ProcessId -ErrorAction SilentlyContinue | Select-Object -ExpandProperty LocalPort -Unique) }
            if ($listeners.Count -eq 1) { break }
            Write-Progress -Id 72 -ParentId 71 -Activity 'Wait for test SSAS listener' -Status "Attempt $attempt/30" -PercentComplete ($attempt*100/30)
            Start-Sleep -Seconds 1
        }
        Write-Progress -Id 72 -Activity 'Wait for test SSAS listener' -Completed
        if ($listeners.Count -ne 1) { throw 'Cannot identify the single SSAS TCP listener; wait for service startup and retry.' }
        $server = 'localhost:' + $listeners[0]
        Run $PowerShell7 @('-NoProfile','-File',(Join-Path $root 'scripts\Test-HeadlessSSAS.ps1'),'-Server',$server,'-ClientDirectory',(Join-Path $tools 'as-client'),'-EnsureSyntheticModel','-EvidencePath',(Join-Path $runtime 'ssas-evidence.json'))
    } elseif (!$settings.source_root -or !$settings.connection_string) { throw 'existing mode requires source_root and connection_string. It never installs or changes SSAS.' }
    Step 5 'Enroll report sources and generate MCP configuration'
    if (OwnedProcess) { StopOwned }
    Run $venv @((Join-Path $root 'scripts\configure_headless.py'),'--root',$root,'--settings',$Config,'--server',$server)
    Step 6 'Start local HTTP MCP and optional Power BI gateway stack'
    $port = [int]$settings.http_port
    if (!$WithPowerBIStack) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw "Port $port is occupied by another process. Select a free http_port. No unrelated process was stopped." }
    $childId = & $venv (Join-Path $root 'scripts\start_headless_process.py') --root $root --port $port
    if ($LASTEXITCODE -ne 0) { throw 'Failed to detach headless MCP; inspect its logs.' }
    $childId = [int]$childId
    $started = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $childId)
    if (!$started) { throw 'Headless MCP exited; inspect runtime/headless/stderr.log.' }
    @{pid=$childId;creation_ticks=$started.CreationDate.ToUniversalTime().Ticks.ToString()} | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
    $url = "http://127.0.0.1:$port/mcp"
    $ready = $false
    for ($attempt=1; $attempt -le 30; $attempt++) {
        if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { $ready=$true; break }
        if (!(Get-Process -Id $childId -ErrorAction SilentlyContinue)) { break }
        Write-Progress -Id 72 -ParentId 71 -Activity 'Wait for HTTP listener' -Status "Attempt $attempt/30" -PercentComplete ($attempt*100/30)
        Start-Sleep -Seconds 1
    }
    Write-Progress -Id 72 -Activity 'Wait for HTTP listener' -Completed
    if (!$ready) { throw 'MCP startup timed out; inspect runtime/headless/stderr.log.' }
    }
    if ($WithPowerBIStack) {
        # A detached child still belongs to the Windows OpenSSH job and dies on
        # disconnect. Let the independent scheduled task own this process instead.
        $supervisorSettings = Join-Path $serviceRoot 'runtime\headless-supervisor.json'
        New-Item -ItemType Directory -Path (Split-Path -Parent $supervisorSettings) -Force | Out-Null
        @{port=$port} | ConvertTo-Json | Set-Content -LiteralPath $supervisorSettings -Encoding UTF8
        $stackArgs = @{Config=$PowerBIConfig;NoDesktop=$true;HeadlessPort=$port;Restart=$true}
        if ($Setup) { $stackArgs.Setup=$true }
        if ($Restart) { $stackArgs.Restart=$true }
        if ($AcceptMicrosoftEula) { $stackArgs.AcceptMicrosoftEula=$true }
        if ($Python) { $stackArgs.Python=$Python }
        & (Join-Path $root 'Start-PowerBI.ps1') @stackArgs
        $url = 'http://127.0.0.1:' + [int]$stack.frontend_port + '/stair-powerbi-headless/mcp'
    }
    Step 7 'Verify MCP protocol, tools and optional thin PBIX build'
    $probeArgs = @((Join-Path $root 'scripts\check_headless.py'),'--url',$url,'--project',$settings.project,'--evidence',(Join-Path $runtime 'mcp-evidence.json'))
    if ($TestBuild) { $probeArgs += '--build' }
    Run $venv $probeArgs
    @{mcpServers=@{'stair-powerbi-headless'=@{url=$url}}} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runtime 'mcp-client.json') -Encoding UTF8
    @('[mcp_servers.stair-powerbi-headless]',('url = "' + $url + '"')) | Set-Content -LiteralPath (Join-Path $runtime 'codex.mcp.toml') -Encoding UTF8
    Write-Host "Headless MCP: $url"
    Write-Host "Client settings: $runtime\mcp-client.json"
    Write-Host "Codex TOML fragment: $runtime\codex.mcp.toml"
    if ($WithPowerBIStack) {
        Write-Host 'The headless route uses the existing Caddy frontend and its IP allowlist. STAIR connectivity and Report Server publication still require integration checks.'
    } else {
        Write-Host 'This endpoint is local only. Use -WithPowerBIStack to configure its route through the existing IP-restricted Caddy frontend.'
    }
    if (Test-Path (Join-Path $root 'runtime\unattended.json')) {
        Write-Host 'SSAS lab uses the pinned port and background startup. Developer licensing remains test-only; no automatic Windows reboot.'
    } else {
        Write-Host 'SSAS lab uses a dynamic port; rerun this script after SSAS restarts. No automatic Windows reboot or production publication.'
    }
} finally { Write-Progress -Id 71 -Activity 'Configure and start Power BI headless MCP' -Completed }
