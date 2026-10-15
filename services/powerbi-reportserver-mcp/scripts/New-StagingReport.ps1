# Operator-only: create an isolated Report Server staging copy, never overwrite a report.
param([Parameter(Mandatory=$true)][string]$Config)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$configuration = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
$credential = Import-Clixml -LiteralPath $configuration.credential_path
$portal = $configuration.portal.TrimEnd('/')
$common = @{ Credential=$credential; TimeoutSec=60; MaximumRedirection=0 }
$folder = '/Fedaraka MCP Validation'
Import-Module ReportingServicesTools -RequiredVersion 0.0.9.3
$folders = Invoke-RestMethod -Uri ($portal + '/api/v2.0/Folders') @common
if (!@($folders.value | Where-Object Path -eq $folder).Count) {
    New-RsRestFolder -ReportPortalUri $portal -RsFolder '/' -FolderName 'Fedaraka MCP Validation' -Credential $credential | Out-Null
}
$reports = Invoke-RestMethod -Uri ($portal + '/api/v2.0/PowerBIReports') @common
$target = $folder + '/Sales Teams Quarterly Performance'
if (@($reports.value | Where-Object Path -eq $target).Count) { throw 'Staging report already exists; review before enrolling it. No overwrite performed.' }
$baseline = Join-Path $configuration.release_root 'Sales Teams Quarterly Performance.pbix'
Write-RsRestCatalogItem -ReportPortalUri $portal -Path $baseline -RsFolder $folder -Credential $credential -Overwrite:$false | Out-Null
$reports = Invoke-RestMethod -Uri ($portal + '/api/v2.0/PowerBIReports') @common
$created = @($reports.value | Where-Object Path -eq $target)
if ($created.Count -ne 1) { throw 'Staging creation outcome uncertain; inspect the catalog before retrying.' }
$result = @{ report_id=$created[0].Id; path=$created[0].Path; name=$created[0].Name }
$result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $configuration.data_root 'staging-report.json') -Encoding UTF8
$result | ConvertTo-Json -Compress
