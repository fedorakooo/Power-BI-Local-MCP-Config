[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$root='C:\PowerBI-MCP';$service=Join-Path $root 'services\powerbi-reportserver-mcp';$runtime=Join-Path $root 'runtime'
$installation=Get-Content (Join-Path $runtime 'installation.json') -Raw|ConvertFrom-Json
if([Security.Principal.WindowsIdentity]::GetCurrent().Name -ne $installation.identity){throw 'Run under the enrolled deployment owner.'}
$caddy=Join-Path $service 'gateway\Caddyfile';$text=Get-Content -LiteralPath $caddy -Raw
$expected=@('modeling','reportserver','authoring','desktop','headless')
foreach($route in $expected){if($text -notmatch ('handle_path /stair-powerbi-'+$route+'/\*')){throw ('Missing canonical STAIR route '+$route)}}
$backup=Join-Path $runtime ('branding-finalize-'+(Get-Date -Format 'yyyyMMddHHmmss'))
New-Item -ItemType Directory -Path $backup|Out-Null
& icacls.exe $backup /inheritance:r /grant:r "$($installation.identity):(OI)(CI)F" 'SYSTEM:(OI)(CI)F'|Out-Null
if($LASTEXITCODE -ne 0){throw 'Could not protect the final Caddy backup.'}
Copy-Item -LiteralPath $caddy -Destination (Join-Path $backup 'Caddyfile')
$pattern='(?ms)^        handle_path /fedaraka-powerbi-(?:modeling|reportserver|authoring|desktop|headless)/\* \{\r?\n.*?^        \}\r?\n'
$count=[regex]::Matches($text,$pattern).Count
if($count -ne 5){throw ('Expected five temporary legacy aliases, found '+$count)}
$text=[regex]::Replace($text,$pattern,'')
if($text -match 'fedaraka-powerbi-'){throw 'Legacy Fedaraka MCP route remains in Caddy configuration.'}
[IO.File]::WriteAllText($caddy,$text,(New-Object Text.UTF8Encoding($false)))
$previousErrorAction=$ErrorActionPreference;$ErrorActionPreference='Continue'
& (Join-Path $service 'runtime\bin\caddy.exe') validate --config $caddy --adapter caddyfile 2>$null
$exit=$LASTEXITCODE;$ErrorActionPreference=$previousErrorAction
if($exit -ne 0){Copy-Item (Join-Path $backup 'Caddyfile') $caddy -Force;throw 'Caddy validation failed; previous config restored.'}
& (Join-Path $root 'Start-Reliable.ps1') -Restart
if($LASTEXITCODE -ne 0){throw 'STAIR gateway restart or readiness check failed.'}
$health=Get-Content (Join-Path $runtime 'background-health.json') -Raw|ConvertFrom-Json
if(!$health.healthy){throw 'STAIR health check reports unhealthy.'}
$legacy='Fedaraka-PowerBI-MCP-D2AD4272'
foreach($suffix in @('','-Desktop','-Health','-Backup')){if(Get-ScheduledTask -TaskName ($legacy+$suffix) -ErrorAction SilentlyContinue){Unregister-ScheduledTask -TaskName ($legacy+$suffix) -Confirm:$false}}
@{status='stair_branding_finalized';legacy_routes_removed=$count;health=$health.healthy;backup=$backup;task=$installation.task}|ConvertTo-Json -Compress
