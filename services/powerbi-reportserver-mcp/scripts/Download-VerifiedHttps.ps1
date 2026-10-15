param(
    [Parameter(Mandatory=$true)][uri]$Url,
    [Parameter(Mandatory=$true)][string]$Destination
)
$ErrorActionPreference = 'Stop'
if ($Url.Scheme -ne 'https') { throw 'Only HTTPS downloads are allowed' }
# .NET validates the server certificate and hostname using Windows trust.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing -TimeoutSec 120
