param(
    [Parameter(Mandatory=$true)][string]$MediaRoot,
    [ValidatePattern('^[A-Za-z][A-Za-z0-9_]{0,15}$')][string]$InstanceName = 'PBIMCPTEST',
    [string]$AdminAccount,
    [switch]$AcceptSqlServerLicense,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
if (!$AdminAccount) { $AdminAccount = [Security.Principal.WindowsIdentity]::GetCurrent().Name }
if ($AdminAccount -match '["\r\n]' -or $AdminAccount -notmatch '\\') { throw 'Use a Windows DOMAIN\user account, without quotes or newlines.' }
$media = (Resolve-Path -LiteralPath $MediaRoot).Path
$setup = Join-Path $media 'setup.exe'
if (!(Test-Path -LiteralPath $setup -PathType Leaf)) { throw 'MediaRoot must contain the full SQL Server Developer installation media and setup.exe.' }
$signature = Get-AuthenticodeSignature -LiteralPath $setup
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw 'SQL setup must have a valid Microsoft Authenticode signature.'
}
$serviceName = 'MSOLAP$' + $InstanceName
if (Get-Service -Name $serviceName -ErrorAction SilentlyContinue) { throw 'This instance already exists; refusing to reinstall or change it.' }
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$plan = [ordered]@{status='preflight';computer=$env:COMPUTERNAME;instance=$InstanceName;features='AS';mode='TABULAR';admin=$AdminAccount;service_account=('NT Service\' + $serviceName);startup='Manual';media=$media;license_accepted=[bool]$AcceptSqlServerLicense;purpose='non-production test only'}
$plan | ConvertTo-Json | Write-Output
if ($ValidateOnly) { return }
if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run installation from an elevated PowerShell.' }
if (!$AcceptSqlServerLicense) { throw 'Explicit SQL Server license acceptance is required: review the Microsoft terms, then use -AcceptSqlServerLicense.' }
$arguments = @('/Q','/ACTION=Install','/FEATURES=AS','/ASSERVERMODE=TABULAR',
    ('/INSTANCENAME=' + $InstanceName),('/INSTANCEID=' + $InstanceName),
    ('/ASSVCACCOUNT="NT Service\' + $serviceName + '"'),'/ASSVCSTARTUPTYPE=Manual',
    ('/ASSYSADMINACCOUNTS="' + $AdminAccount + '"'),'/IACCEPTSQLSERVERLICENSETERMS','/INDICATEPROGRESS')
Write-Host 'Installing the separate Analysis Services test instance; SQL setup logs contain detailed progress.'
$process = Start-Process -FilePath $setup -ArgumentList $arguments -WorkingDirectory $media -WindowStyle Hidden -PassThru
$watch = [Diagnostics.Stopwatch]::StartNew()
while (!$process.WaitForExit(1000)) {
    Write-Progress -Activity 'Install SSAS Tabular test instance' -Status ("Instance {0}; elapsed {1}s" -f $InstanceName,[int]$watch.Elapsed.TotalSeconds) -PercentComplete -1
}
Write-Progress -Activity 'Install SSAS Tabular test instance' -Completed
if ($process.ExitCode -notin @(0,3010)) { throw ('SQL setup failed, exit=' + $process.ExitCode + '. Inspect Microsoft SQL Server Setup Bootstrap logs.') }
$service = Get-Service -Name $serviceName -ErrorAction Stop
[pscustomobject]@{status='installed';instance=$InstanceName;service=$serviceName;service_status=[string]$service.Status;restart_required=($process.ExitCode -eq 3010);model_deployed=$false;reportserver_verified=$false} | ConvertTo-Json
