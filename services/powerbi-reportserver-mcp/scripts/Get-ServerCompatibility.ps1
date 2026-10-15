param([Parameter(Mandatory=$true)][string]$Config)
$ErrorActionPreference = 'Stop'
$configuration = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
$credential = Import-Clixml -LiteralPath $configuration.credential_path
$portal = $configuration.portal.TrimEnd('/')
$common = @{ Credential=$credential; TimeoutSec=60; MaximumRedirection=0 }
$result = @{}
foreach ($endpoint in @('/api/v1.0/ReportServerInfo/Model.ServerProductInfo', '/api/v2.0/System/Properties?properties=MaxFileSizeMb')) {
    try {
        $response = Invoke-RestMethod -Uri ($portal + $endpoint) @common
        $result[$endpoint] = $response
    } catch {
        $result[$endpoint] = @{ http_status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { $null } }
    }
}
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $configuration.data_root 'server-compatibility.json') -Encoding UTF8
$result | ConvertTo-Json -Depth 6
