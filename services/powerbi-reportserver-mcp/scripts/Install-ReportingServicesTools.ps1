$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
if (!(Get-PackageProvider -Name NuGet -ListAvailable -ErrorAction SilentlyContinue)) {
    Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Scope CurrentUser -Force | Out-Null
}
Install-Module -Name ReportingServicesTools -RequiredVersion 0.0.9.3 -Repository PSGallery -Scope CurrentUser -Force -Confirm:$false
Import-Module ReportingServicesTools -RequiredVersion 0.0.9.3
Get-Command Out-RsRestCatalogItem,Write-RsRestCatalogItem | Select-Object Name,Version
