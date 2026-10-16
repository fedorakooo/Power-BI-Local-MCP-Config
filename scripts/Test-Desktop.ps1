param([string]$ServiceRoot, [switch]$Launch, [string]$Project = 'rs-automation')
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
Write-Host '=== Desktop executable and report file ==='
$executable = [string]$config.desktop_executable
$reportProperty = $config.desktop_reports.PSObject.Properties[$Project]
if (!$reportProperty) { throw "Project is not enrolled: $Project" }
$report = [string]$reportProperty.Value
if (!(Test-Path -LiteralPath $executable -PathType Leaf)) { throw "Desktop executable missing: $executable" }
if (!(Test-Path -LiteralPath $report -PathType Leaf)) { throw "Report missing: $report" }
Get-Item -LiteralPath $executable | Select-Object FullName,@{Name='Version';Expression={$_.VersionInfo.FileVersion}} | Format-List | Out-Host
Get-Item -LiteralPath $report | Select-Object FullName,Length | Format-List | Out-Host
Get-FileHash -LiteralPath $report -Algorithm SHA256 | Format-List | Out-Host
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($report)
try {
    Write-Host "PBIX DataModel present=$([bool]$archive.GetEntry('DataModel')); Report/Layout present=$([bool]$archive.GetEntry('Report/Layout'))"
} finally { $archive.Dispose() }
Write-Host '=== WebView2 runtime registrations ==='
$registrations = @()
foreach ($key in @('HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients','HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients','HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients')) {
    $registrations += @(Get-ChildItem $key -ErrorAction SilentlyContinue | Get-ItemProperty -ErrorAction SilentlyContinue | Where-Object { $_.name -like '*WebView2*' } | Select-Object name,pv)
}
if ($registrations.Count) { $registrations | Format-Table -AutoSize | Out-Host }
else { Write-Host 'No Evergreen WebView2 registration found; this alone does not prove the runtime is unavailable.' }
if ($Launch) {
    if (@(Get-Process PBIDesktop -ErrorAction SilentlyContinue).Count) {
        throw 'Desktop is already running. Use this diagnostic without -Launch; no duplicate launch attempted.'
    }
    Write-Host '=== Launch enrolled report once; monitor for up to 20 seconds ==='
    $started = Start-Process -FilePath $executable -ArgumentList ('"' + $report + '"') -WorkingDirectory (Split-Path -Parent $executable) -PassThru
    Write-Host "Launch requested: PID=$($started.Id)"
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while (!$started.WaitForExit(1000) -and $timer.Elapsed.TotalSeconds -lt 20) {
        Write-Progress -Id 20 -Activity 'Power BI Desktop diagnostic launch' -Status ("Waiting; elapsed {0}s" -f [int]$timer.Elapsed.TotalSeconds) -PercentComplete -1
    }
    Write-Progress -Id 20 -Activity 'Power BI Desktop diagnostic launch' -Completed
    if ($started.HasExited) { Write-Host ('Original Desktop process exited: decimal={0}, hex=0x{1:X8}' -f $started.ExitCode, $started.ExitCode) }
    else { Write-Host 'Desktop process is still running; inspect any visible startup message.' }
    Get-Process PBIDesktop -ErrorAction SilentlyContinue | Select-Object Id,SessionId,MainWindowTitle | Format-List | Out-Host
}
Write-Host '=== Windows, memory and .NET Framework ==='
Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,OSArchitecture,@{Name='RAM_GB';Expression={[Math]::Round($_.TotalVisibleMemorySize/1MB,1)}},@{Name='FreeRAM_GB';Expression={[Math]::Round($_.FreePhysicalMemory/1MB,1)}} | Format-List | Out-Host
Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -ErrorAction SilentlyContinue | Select-Object Version,Release | Format-List | Out-Host
Write-Host '=== Recent Windows application and .NET faults mentioning Power BI or Mashup ==='
$faults = @(Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000,1001,1026; StartTime=(Get-Date).AddHours(-4)} -MaxEvents 200 -ErrorAction SilentlyContinue | Where-Object { $_.Message -match 'PBIDesktop|msmdsrv|Power BI|msedgewebview2|Microsoft\.Mashup' } | Select-Object -First 6)
if ($faults.Count) {
    foreach ($fault in $faults) {
        $message = $fault.Message.Substring(0,[Math]::Min(8000,$fault.Message.Length))
        $message = $message -replace '(?i)((?:password|passwd|access_token|refresh_token|client_secret)\s*[=:]\s*)[^\s,;]+','$1[REDACTED]'
        [pscustomobject]@{Time=$fault.TimeCreated; Provider=$fault.ProviderName; Id=$fault.Id; Message=$message} | Format-List | Out-Host
    }
} else { Write-Host 'No matching application fault found in the last four hours.' }
$node = (Get-Content (Join-Path $service 'runtime\gateway-paths.json') -Raw | ConvertFrom-Json).node
$cli = Join-Path $service 'bridge\node_modules\@microsoft\powerbi-desktop-bridge-cli\dist\cli.js'
Write-Host '=== Official Desktop Bridge status ==='
& $node $cli status
if ($LASTEXITCODE -ne 0) { throw "Desktop Bridge status failed, exit=$LASTEXITCODE" }
