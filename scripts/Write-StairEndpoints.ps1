param([Parameter(Mandatory=$true)][string]$Root, [Parameter(Mandatory=$true)][string]$ConfigPath, [string]$PublicHost)
$ErrorActionPreference = 'Stop'
$settings = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$generated = Join-Path $Root 'generated'
New-Item -ItemType Directory -Path $generated -Force | Out-Null
$destination = Join-Path $generated 'stair-endpoints.json'
if (!$PublicHost -and (Test-Path -LiteralPath $destination)) {
    $PublicHost = (Get-Content -LiteralPath $destination -Raw | ConvertFrom-Json).public_host
}
if (!$PublicHost) { $PublicHost = [Environment]::MachineName }
$PublicHost = $PublicHost.Trim().Trim('[',']')
if ([uri]::CheckHostName($PublicHost) -eq [UriHostNameType]::Unknown) {
    throw 'PublicHost must be a Windows machine IP or DNS name, without http://, port or path.'
}
$urlHost = if ($PublicHost.Contains(':')) { '[' + $PublicHost + ']' } else { $PublicHost }
$port = [int]$settings.frontend_port
$tools = @(
    @{name='Fedaraka Power BI Modeling'; route='modeling'; backend_port=$port+1},
    @{name='Fedaraka Power BI Report Server'; route='reportserver'; backend_port=$port+2},
    @{name='Fedaraka Power BI Authoring'; route='authoring'; backend_port=$port+3},
    @{name='Fedaraka Power BI Desktop'; route='desktop'; backend_port=$port+4}
)
$toolsets = @($tools | ForEach-Object {
    [ordered]@{name=$_.name; transport='streamable-http'; url="http://${urlHost}:$port/fedaraka-powerbi-$($_.route)/mcp"; authentication='none'; internal_backend_port=$_.backend_port}
})
$payload = [ordered]@{public_host=$PublicHost; proxy_port=$port; allowed_addresses=@($settings.allowed_addresses); access_from_stair='not_verified'; toolsets=$toolsets}
$payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $destination -Encoding UTF8
Write-Host ''
Write-Host '=== STAIR MCP URLs: Streamable HTTP through Supergateway + Caddy ===' -ForegroundColor Cyan
foreach ($toolset in $toolsets) {
    Write-Host $toolset.name
    Write-Host $toolset.url
}
Write-Host "Proxy port: $port; internal backend ports: $($tools.backend_port -join ',')"
Write-Host "IP allowlist: $($settings.allowed_addresses -join ',')"
Write-Host "Saved: $destination"
Write-Host 'STAIR network reachability has not been verified from this Windows startup check.'
if (!@($settings.allowed_addresses | Where-Object { $_ -notmatch '^127\.' -and $_ -notmatch '^::1(?:/128)?$' }).Count) {
    Write-Host 'Only loopback is allowed. Run Setup with -StairAddresses <STAIR-egress-IP-or-CIDR> to enable the intended source.' -ForegroundColor Yellow
}
