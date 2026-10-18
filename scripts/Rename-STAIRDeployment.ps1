[CmdletBinding()]
param([string]$Root=(Split-Path -Parent $PSScriptRoot),
    [Parameter(Mandatory=$true)][Management.Automation.PSCredential]$Credential)
$ErrorActionPreference='Stop'
$Root=(Resolve-Path -LiteralPath $Root).Path
$service=Join-Path $Root 'services\powerbi-reportserver-mcp'
$runtime=Join-Path $Root 'runtime'
$installationPath=Join-Path $runtime 'installation.json'
$installation=Get-Content $installationPath -Raw | ConvertFrom-Json
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
if ($identity -ne $installation.identity -or $Credential.UserName -ne $identity) { throw 'Use the existing deployment owner.' }
$oldTask=[string]$installation.task
if ($oldTask -notmatch '^Fedaraka-PowerBI-MCP-[A-F0-9]{8}$') { throw 'Expected the enrolled legacy task. A completed migration must not be repeated.' }
$newTask=$oldTask.Replace('Fedaraka','STAIR')
$snapshot=Join-Path $runtime ('branding-backup-'+(Get-Date -Format 'yyyyMMddHHmmss'))
New-Item -ItemType Directory -Path $snapshot | Out-Null
& icacls.exe $snapshot /inheritance:r /grant:r "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not protect branding backup.' }
function Rebrand([string]$Value) { $Value.Replace('fedaraka','stair').Replace('Fedaraka','STAIR').Replace('FEDARAKA','STAIR') }
function Write-Utf8([string]$Path,[string]$Value) { [IO.File]::WriteAllText($Path,$Value,(New-Object Text.UTF8Encoding($false))) }
$jsonFiles=@($installationPath,(Join-Path $Root 'deployment.local.json'),(Join-Path $runtime 'unattended.json'),(Join-Path $service 'config.local.json'),(Join-Path $service 'gateway\servers.local.json'),(Join-Path $Root 'headless\config.local.json'))
for($i=0;$i -lt $jsonFiles.Count;$i++) { Copy-Item -LiteralPath $jsonFiles[$i] -Destination (Join-Path $snapshot ("config-$i.json")) }
$tasks=@()
foreach($suffix in @('-Health','-Backup','-Desktop','')) {
    $task=Get-ScheduledTask -TaskName ($oldTask+$suffix) -ErrorAction SilentlyContinue
    if ($task) {
        $xml=Export-ScheduledTask -TaskName $task.TaskName
        $xml | Set-Content (Join-Path $snapshot ($task.TaskName+'.xml')) -Encoding UTF8
        $tasks+=@{name=$task.TaskName;xml=$xml;logon=[string]$task.Principal.LogonType}
        Stop-ScheduledTask -TaskName $task.TaskName
        Disable-ScheduledTask -TaskName $task.TaskName | Out-Null
    }
}
Start-Sleep -Seconds 20
# Metadata-only Report Server renames: preserve GUIDs and report content.
$config=Get-Content (Join-Path $service 'config.local.json') -Raw | ConvertFrom-Json
$pbiCredential=Import-Clixml -LiteralPath $config.clients.fedaraka.credential_path
$base=$config.portal.TrimEnd('/')+'/api/v2.0/'
$common=@{Credential=$pbiCredential;ErrorAction='Stop'}
$folders=(Invoke-RestMethod -Uri ($base+'Folders') @common).value
$folder=@($folders | Where-Object { $_.Path -eq '/Fedaraka MCP Validation' })
if ($folder.Count -ne 1 -or @($folders | Where-Object { $_.Path -eq '/STAIR MCP Validation' }).Count) { throw 'Expected one enrolled legacy folder and no conflicting STAIR folder.' }
$folder | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $snapshot 'catalog-folder.json') -Encoding UTF8
Invoke-RestMethod -Uri ($base+'Folders('+$folder[0].Id+')') -Method Patch -ContentType 'application/json' -Body '{"Name":"STAIR MCP Validation"}' @common | Out-Null
$enrollments=Join-Path $service 'runtime\catalog-enrollments'
foreach($file in Get-ChildItem -LiteralPath $enrollments -Filter '*.json') {
    $record=Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
    if ($record.path -notlike '/Fedaraka MCP Validation/*') { continue }
    Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $snapshot $file.Name)
    $item=Invoke-RestMethod -Uri ($base+'PowerBIReports('+$record.id+')') @common
    if ($item.Name -match 'Fedaraka') {
        $payload=@{Name=(Rebrand $item.Name)} | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri ($base+'PowerBIReports('+$record.id+')') -Method Patch -ContentType 'application/json' -Body $payload @common | Out-Null
    }
    $actual=Invoke-RestMethod -Uri ($base+'PowerBIReports('+$record.id+')') @common
    if ($actual.Path -ne (Rebrand $record.path)) { throw 'Catalog rename verification failed.' }
    $record.path=$actual.Path
    Write-Utf8 $file.FullName ($record | ConvertTo-Json -Depth 10)
}
# Rename only the enrolled Desktop working file, preserving edited bytes.
$oldFile=[string]$config.desktop_reports.'rs-automation'
$newFile=Rebrand $oldFile
if ($oldFile -ne $newFile) {
    $expectedDirectory=[IO.Path]::GetFullPath((Join-Path $service 'runtime\release')).TrimEnd('\')+'\'
    if (![IO.Path]::GetFullPath($oldFile).StartsWith($expectedDirectory,[StringComparison]::OrdinalIgnoreCase) -or ![IO.Path]::GetFullPath($newFile).StartsWith($expectedDirectory,[StringComparison]::OrdinalIgnoreCase)) { throw 'Report rename escaped deployment release directory.' }
    if (Get-Process PBIDesktop -ErrorAction SilentlyContinue) { throw 'Close Power BI Desktop after saving before renaming its enrolled file.' }
    if (Test-Path -LiteralPath $newFile) { throw 'New working report already exists; refusing overwrite.' }
    $before=(Get-FileHash -LiteralPath $oldFile).Hash
    Move-Item -LiteralPath $oldFile -Destination $newFile
    if ((Get-FileHash -LiteralPath $newFile).Hash -ne $before) { throw 'Working report content changed.' }
}
$created=Join-Path $Root 'headless\created-reports'
$oldProject=Join-Path $created 'fedaraka-dynamic-sales'
$newProject=Join-Path $created 'stair-dynamic-sales'
if (Test-Path -LiteralPath $oldProject) {
    if (Test-Path -LiteralPath $newProject) { throw 'New project already exists; refusing overwrite.' }
    if ((Get-Item -LiteralPath $created).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Managed project root is a reparse point.' }
    $parent=(Resolve-Path -LiteralPath $created).Path.TrimEnd('\')+'\'
    if (![IO.Path]::GetFullPath($newProject).StartsWith($parent,[StringComparison]::OrdinalIgnoreCase)) { throw 'New project path escaped managed root.' }
    $resolved=(Resolve-Path -LiteralPath $oldProject).Path
    if ([IO.Path]::GetFullPath($resolved) -ne [IO.Path]::GetFullPath($oldProject)) { throw 'Unexpected managed project path.' }
    Move-Item -LiteralPath $oldProject -Destination $newProject
    $meta=Join-Path $newProject '.mcp-created-report.json'
    Write-Utf8 $meta (Rebrand (Get-Content $meta -Raw))
}
foreach($file in $jsonFiles) { Write-Utf8 $file (Rebrand (Get-Content -LiteralPath $file -Raw)) }
$installation=Get-Content $installationPath -Raw | ConvertFrom-Json
$installation.settings_sha256=(Get-FileHash -LiteralPath (Join-Path $Root 'deployment.local.json')).Hash
Write-Utf8 $installationPath ($installation | ConvertTo-Json)
$caddy=Join-Path $service 'gateway\Caddyfile'
Copy-Item -LiteralPath $caddy -Destination (Join-Path $snapshot 'Caddyfile')
$text=Rebrand (Get-Content -LiteralPath $caddy -Raw)
# Transitional aliases keep clients connected while their toolsets are updated.
$text=[regex]::Replace($text,'(?ms)^        handle_path /(stair-powerbi-[^/]+)/\* \{\r?\n.*?^        \}\r?\n', {param($m) $m.Value+$m.Value.Replace('/stair-powerbi-','/fedaraka-powerbi-')})
Write-Utf8 $caddy $text
& (Join-Path $service 'runtime\bin\caddy.exe') validate --config $caddy --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw 'Caddy validation failed; restore saved configuration before starting.' }
foreach($task in $tasks) {
    $newName=Rebrand $task.name
    $xml=Rebrand $task.xml
    [xml]$definition=$xml
    $definition.Task.Settings.Enabled='true'
    $xml=$definition.OuterXml
    # The legacy tasks were disabled after export; the copied definitions stay enabled.
    if ($task.logon -eq 'Password') {
        Register-ScheduledTask -TaskName $newName -Xml $xml -User $identity -Password $Credential.GetNetworkCredential().Password -Force | Out-Null
    } else { Register-ScheduledTask -TaskName $newName -Xml $xml -Force | Out-Null }
}
foreach($rule in Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq $oldTask -or $_.Name -eq ($oldTask+'-Backends') }) {
    $port=$rule | Get-NetFirewallPortFilter
    $address=$rule | Get-NetFirewallAddressFilter
    New-NetFirewallRule -Name (Rebrand $rule.Name) -DisplayName (Rebrand $rule.DisplayName) -Direction $rule.Direction -Action $rule.Action -Enabled $rule.Enabled -Profile $rule.Profile -Protocol $port.Protocol -LocalPort $port.LocalPort -RemoteAddress $address.RemoteAddress | Out-Null
    Remove-NetFirewallRule -Name $rule.Name
}
foreach($task in $tasks) { Unregister-ScheduledTask -TaskName $task.name -Confirm:$false }
Start-ScheduledTask -TaskName $newTask
Start-ScheduledTask -TaskName ($newTask+'-Desktop')
@{status='stair_branding_migrated';task=$newTask;backup=$snapshot;legacy_routes_temporary=$true;working_report_sha256=$before} | ConvertTo-Json | Set-Content (Join-Path $runtime 'branding-migration.json') -Encoding UTF8
& (Join-Path $Root 'Start-Reliable.ps1')
