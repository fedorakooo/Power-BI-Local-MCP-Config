param([switch]$AcceptEula)
$ErrorActionPreference = 'Stop'
function Write-InstallerProgress([int]$Completed, [int]$Total, [string]$Status) {
    'PBIMCP_PROGRESS ' + (@{activity='Power BI Desktop RS'; completed=$Completed; total=$Total; status=$Status} | ConvertTo-Json -Compress)
}
Write-InstallerProgress 0 6 'Check installed Desktop version and running installers'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$expectedVersion = '2.158.1177.0'
$executable = Join-Path $env:ProgramFiles 'Microsoft Power BI Desktop RS\bin\PBIDesktop.exe'
if (Get-Process PBIDesktopSetupRS_x64 -ErrorAction SilentlyContinue) { throw 'A Desktop installer is still running; wait for MSI completion before verifying or retrying.' }
if ((Test-Path -LiteralPath $executable) -and (Get-Item -LiteralPath $executable).VersionInfo.FileVersion -eq $expectedVersion) {
    Write-InstallerProgress 6 6 'Matching Desktop RS is already installed'
    @{ status='already_installed'; executable=$executable; version=$expectedVersion } | ConvertTo-Json
    exit 0
}
if (!$AcceptEula) { throw 'Accept the Microsoft Desktop for Report Server EULA explicitly before using -AcceptEula.' }
if (Get-Process PBIDesktop -ErrorAction SilentlyContinue) { throw 'Close Power BI Desktop after saving reviewed work, then run the installer.' }
$directory = Join-Path $root 'runtime\installers'
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$installer = Join-Path $directory 'PBIDesktopSetupRS_x64.exe'
Write-InstallerProgress 1 6 'Download or reuse the Desktop installer'
if (!(Test-Path -LiteralPath $installer)) {
    Invoke-WebRequest 'https://download.microsoft.com/download/2/d/a/2da81ea3-040a-4d08-a593-6bebc3bf97e8/PBIDesktopSetupRS_x64.exe' -OutFile $installer -UseBasicParsing
}
Write-InstallerProgress 2 6 'Verify installer SHA256'
if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne 'E3BBA54D63C88642AA495FBC0E19AB96E88D1CF2EB019388A9A76B2A3B3F93F9') { throw 'Installer does not match the reviewed September 2026 build.' }
Write-InstallerProgress 3 6 'Verify Microsoft Authenticode signature'
$signature = Get-AuthenticodeSignature -LiteralPath $installer
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '^CN=Microsoft Corporation,') { throw 'Installer signature verification failed.' }
$logPath = Join-Path $directory ('desktop-rs-' + [Guid]::NewGuid().ToString('N') + '.log')
Write-InstallerProgress 4 6 'Start the Microsoft Desktop installer'
$process = Start-Process -FilePath $installer -ArgumentList '-quiet','-norestart','ACCEPT_EULA=1','LANGUAGE=en-US','ENABLECXP=0','INSTALLDESKTOPSHORTCUT=0','-log',('"' + $logPath + '"') -WindowStyle Hidden -PassThru
$elapsed = [Diagnostics.Stopwatch]::StartNew()
$lastNotice = -5
while (!$process.WaitForExit(1000)) {
    if ($elapsed.Elapsed.TotalSeconds - $lastNotice -ge 5) {
        $lastNotice = [int]$elapsed.Elapsed.TotalSeconds
        Write-InstallerProgress 0 0 "Microsoft installer is running; elapsed ${lastNotice}s (completion percentage unavailable)"
    }
}
Write-InstallerProgress 5 6 'Verify installed executable version and MSI completion log'
# This bootstrapper can return 0 even when the MSI failed. Verify log and installed binary.
if (!(Test-Path -LiteralPath $executable) -or (Get-Item -LiteralPath $executable).VersionInfo.FileVersion -ne $expectedVersion -or !(Select-String -LiteralPath $logPath -Pattern 'Apply complete, result: 0x0,' -Quiet)) {
    throw ('Desktop installation not verified. Inspect private log: ' + $logPath)
}
Write-InstallerProgress 6 6 'Desktop RS installation verified'
@{ status='installed_verified'; executable=$executable; version=$expectedVersion; bootstrapper_exit_code=$process.ExitCode; log=$logPath } | ConvertTo-Json
