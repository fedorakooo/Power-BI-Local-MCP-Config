[CmdletBinding()]
param([Parameter(Mandatory=$true)][Management.Automation.PSCredential]$Credential)
$ErrorActionPreference='Stop'
$root='C:\PowerBI-MCP';$service=Join-Path $root 'services\powerbi-reportserver-mcp';$runtime=Join-Path $root 'runtime'
$installation=Get-Content (Join-Path $runtime 'installation.json') -Raw|ConvertFrom-Json
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
if($identity -ne $installation.identity -or $Credential.UserName -ne $identity){throw 'Run under the original deployment owner.'}
if($installation.task -notmatch '^STAIR-PowerBI-MCP-[A-F0-9]{8}$'){throw 'Installation marker is not branded STAIR.'}
$config=Get-Content (Join-Path $service 'config.local.json') -Raw|ConvertFrom-Json
$client=$config.clients.stair
if(!$client -or !$client.credential_path){throw 'STAIR Report Server credential configuration is missing.'}
$pbiCredential=Import-Clixml -LiteralPath $client.credential_path
$base=$config.portal.TrimEnd('/')+'/api/v2.0/'
$common=@{Credential=$pbiCredential;ErrorAction='Stop'}
$folders=(Invoke-RestMethod -Uri ($base+'Folders') @common).value
$oldFolder=@($folders|Where-Object Path -eq '/Fedaraka MCP Validation')
$newFolder=@($folders|Where-Object Path -eq '/STAIR MCP Validation')
if($newFolder.Count -eq 1 -and $oldFolder.Count -eq 0){$folderId=$newFolder[0].Id}
elseif($oldFolder.Count -eq 1 -and $newFolder.Count -eq 0){$folderId=$oldFolder[0].Id;Invoke-RestMethod -Uri ($base+'Folders('+$folderId+')') -Method Patch -ContentType 'application/json' -Body '{"Name":"STAIR MCP Validation"}' @common|Out-Null}
else{throw 'Report Server folder state is ambiguous; refusing to rename or overwrite.'}
foreach($file in Get-ChildItem -LiteralPath (Join-Path $service 'runtime\catalog-enrollments') -Filter '*.json'){
 $record=Get-Content -LiteralPath $file.FullName -Raw|ConvertFrom-Json
 if($record.path -notmatch '^/(Fedaraka|STAIR) MCP Validation/'){continue}
 $item=Invoke-RestMethod -Uri ($base+'PowerBIReports('+$record.id+')') @common
 if($item.Name -match '^Fedaraka '){$body=@{Name=($item.Name -replace '^Fedaraka ','STAIR ')}|ConvertTo-Json -Compress;Invoke-RestMethod -Uri ($base+'PowerBIReports('+$record.id+')') -Method Patch -ContentType 'application/json' -Body $body @common|Out-Null}
 $actual=Invoke-RestMethod -Uri ($base+'PowerBIReports('+$record.id+')') @common
 $expected=$record.path -replace '^/Fedaraka MCP Validation','/STAIR MCP Validation' -replace '/Fedaraka ','/STAIR '
 if($actual.Path -ne $expected){throw ('Report Server path mismatch for enrollment '+$file.BaseName)}
 $record.path=$actual.Path;[IO.File]::WriteAllText($file.FullName,($record|ConvertTo-Json -Depth 10),(New-Object Text.UTF8Encoding($false)))
}
# Ensure the enrolled working PBIX and managed project have their STAIR names.
$report=[string]$config.desktop_reports.'rs-automation';$stairReport=$report -replace 'Fedaraka','STAIR'
if($report -ne $stairReport -and (Test-Path -LiteralPath $report)){if(Test-Path -LiteralPath $stairReport){throw 'Both legacy and STAIR working PBIX files exist.'};Move-Item -LiteralPath $report -Destination $stairReport}
$oldProject=Join-Path $root 'headless\created-reports\fedaraka-dynamic-sales';$newProject=Join-Path $root 'headless\created-reports\stair-dynamic-sales'
if((Test-Path $oldProject) -and !(Test-Path $newProject)){Move-Item -LiteralPath $oldProject -Destination $newProject}
# Refresh generated Windows and STAIR endpoint files after the server-side config rename.
$clientFiles=@((Join-Path $root 'generated\stair-endpoints.json'),(Join-Path $root 'generated\codex-mcp.toml'),(Join-Path $runtime 'headless\mcp-client.json'),(Join-Path $runtime 'headless\codex.mcp.toml'))
foreach($file in $clientFiles){if(Test-Path -LiteralPath $file){$text=Get-Content -LiteralPath $file -Raw;$text=$text.Replace('fedaraka','stair').Replace('Fedaraka','STAIR').Replace('FEDARAKA','STAIR');[IO.File]::WriteAllText($file,$text,(New-Object Text.UTF8Encoding($false)))}}
# Validate current canonical routes; legacy aliases stay live while STAIR toolsets refresh.
$caddy=Join-Path $service 'gateway\Caddyfile';$caddyText=Get-Content $caddy -Raw
foreach($route in @('modeling','reportserver','authoring','desktop','headless')){if($caddyText -notmatch ('handle_path /stair-powerbi-'+$route+'/\*')){throw ('Missing canonical STAIR route: '+$route)}}
$previousErrorAction=$ErrorActionPreference;$ErrorActionPreference='Continue'
& (Join-Path $service 'runtime\bin\caddy.exe') validate --config $caddy --adapter caddyfile 2>$null
$caddyExit=$LASTEXITCODE;$ErrorActionPreference=$previousErrorAction
if($caddyExit -ne 0){throw 'Caddy configuration validation failed.'}
# Clone the existing restricted firewall policy under the STAIR task name.
$oldTask='Fedaraka-PowerBI-MCP-D2AD4272';$newTask=[string]$installation.task
foreach($oldName in @($oldTask,$oldTask+'-Backends')){
 $rule=Get-NetFirewallRule -Name $oldName -ErrorAction SilentlyContinue
 if($rule -and !(Get-NetFirewallRule -Name ($oldName -replace 'Fedaraka','STAIR') -ErrorAction SilentlyContinue)){
  $port=$rule|Get-NetFirewallPortFilter;$address=$rule|Get-NetFirewallAddressFilter
  New-NetFirewallRule -Name ($oldName -replace 'Fedaraka','STAIR') -DisplayName ($rule.DisplayName -replace 'Fedaraka','STAIR') -Direction $rule.Direction -Action $rule.Action -Enabled $rule.Enabled -Profile $rule.Profile -Protocol $port.Protocol -LocalPort $port.LocalPort -RemoteAddress $address.RemoteAddress|Out-Null
 }
}
# Rebuild and start the STAIR background, Desktop, health and backup tasks; readiness is checked by the script.
& (Join-Path $root 'Start-Reliable.ps1') -Setup -Credential $Credential
if($LASTEXITCODE -ne 0){throw 'Reliable startup did not complete.'}
# Remove only the stopped legacy tasks after STAIR readiness succeeded.
foreach($name in @($oldTask,$oldTask+'-Desktop',$oldTask+'-Health',$oldTask+'-Backup')){if(Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue){Unregister-ScheduledTask -TaskName $name -Confirm:$false}}
foreach($name in @($oldTask,$oldTask+'-Backends')){if(Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue){Remove-NetFirewallRule -Name $name}}
@{status='stair_recovery_complete';task=$newTask;folder='/STAIR MCP Validation';legacy_routes_temporary=$true} | ConvertTo-Json -Compress
