param(
    [string]$Root,
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_-]+\.pbix$')][string]$FileName,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSha256,
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_-]+$')][string]$Destination,
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$Actor = 'fedaraka'
)
# Operator-only approval gate. Do not expose this script as an MCP tool.
$ErrorActionPreference='Stop'
if (!$Root) { $Root = Split-Path -Parent $PSScriptRoot }
$service = Join-Path $Root 'services\powerbi-reportserver-mcp'
$config = Join-Path $service 'config.local.json'
$settings = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
$source = Join-Path $settings.release_root $FileName
Push-Location $service
try {
    & (Join-Path $service '.venv\Scripts\python.exe') -m pbirs_mcp.admin --config $config `
        approve-create --actor $Actor --report $Destination --file $source --expected-sha256 $ExpectedSha256
    if ($LASTEXITCODE -ne 0) { throw 'Create approval was not issued.' }
} finally { Pop-Location }
