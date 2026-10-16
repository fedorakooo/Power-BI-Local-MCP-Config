# PowerShell 7.4+ supplies .NET 8+ for the pinned Analysis Services clients.
function Test-HeadlessPowerShell([string]$Executable) {
    if (!(Test-Path -LiteralPath $Executable -PathType Leaf)) { throw "PowerShell executable not found: $Executable" }
    $probe = & $Executable -NoLogo -NoProfile -NonInteractive -Command '[pscustomobject]@{major=$PSVersionTable.PSVersion.Major;minor=$PSVersionTable.PSVersion.Minor;prerelease=[string]$PSVersionTable.PSVersion.PreReleaseLabel;bits=([IntPtr]::Size*8)} | ConvertTo-Json -Compress' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'PowerShell runtime probe failed.' }
    $info = ($probe -join "`n") | ConvertFrom-Json
    if ($info.major -ne 7 -or $info.minor -lt 4 -or $info.bits -ne 64 -or $info.prerelease) {
        throw 'Use stable PowerShell 7.4+ x64 for the .NET 8 SSAS clients.'
    }
    return (Resolve-Path -LiteralPath $Executable).Path
}

function Install-HeadlessPowerShell([string]$Root) {
    $version = '7.6.7'
    $expected = 'd2f952ebdbf24386cb8923553aa58e41a846db35a6155ea04c58142a4b16dbb7'
    $parent = Join-Path $Root 'tools\headless'
    $destination = Join-Path $parent ('powershell-' + $version)
    $executable = Join-Path $destination 'pwsh.exe'
    if (Test-Path -LiteralPath $destination) {
        $signature = Get-AuthenticodeSignature -LiteralPath $executable
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'Private PowerShell signature validation failed. Inspect tools/headless before retrying.' }
        return Test-HeadlessPowerShell $executable
    }
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $archive = Join-Path $parent ('PowerShell-' + $version + '-win-x64.zip')
    if (!(Test-Path -LiteralPath $archive)) {
        $pending = $archive + '.partial'
        Write-Host "Downloading private PowerShell $version x64 from Microsoft GitHub releases..."
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri "https://github.com/PowerShell/PowerShell/releases/download/v$version/PowerShell-$version-win-x64.zip" -OutFile $pending -UseBasicParsing
            if ((Get-FileHash -LiteralPath $pending -Algorithm SHA256).Hash -ne $expected) { throw 'PowerShell archive SHA256 mismatch.' }
            Move-Item -LiteralPath $pending -Destination $archive
        } finally { if (Test-Path -LiteralPath $pending) { Remove-Item -LiteralPath $pending } }
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) { throw 'Cached PowerShell archive SHA256 mismatch; remove the archive and retry.' }
    $staging = Join-Path $parent ('powershell-extract-' + [guid]::NewGuid().ToString('N'))
    Write-Progress -Id 73 -ParentId 71 -Activity 'Prepare private PowerShell' -Status 'Extract verified archive' -PercentComplete -1
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($archive, $staging)
        $stagedExe = Join-Path $staging 'pwsh.exe'
        $signature = Get-AuthenticodeSignature -LiteralPath $stagedExe
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'Extracted PowerShell must have a valid Microsoft Authenticode signature.' }
        [void](Test-HeadlessPowerShell $stagedExe)
        # Both move targets are fixed descendants of this deployment's tools folder.
        $prefix = [IO.Path]::GetFullPath($parent).TrimEnd('\') + '\'
        foreach ($target in @($staging,$destination)) {
            if (![IO.Path]::GetFullPath($target).StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'PowerShell installation path escapes the tools folder.' }
        }
        Move-Item -LiteralPath $staging -Destination $destination
    } finally { Write-Progress -Id 73 -Activity 'Prepare private PowerShell' -Completed }
    return Test-HeadlessPowerShell $executable
}

function Select-HeadlessPowerShell([string]$Root, [string]$Requested, [switch]$AllowDownload) {
    if ($Requested) { return Test-HeadlessPowerShell $Requested }
    $candidates = @()
    $command = Get-Command pwsh.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    if ($env:ProgramFiles) { $candidates += Join-Path $env:ProgramFiles 'PowerShell\7\pwsh.exe' }
    $candidates += Join-Path $Root 'tools\headless\powershell-7.6.7\pwsh.exe'
    foreach ($candidate in @($candidates | Select-Object -Unique)) {
        try {
            if ($candidate -eq (Join-Path $Root 'tools\headless\powershell-7.6.7\pwsh.exe')) {
                $signature = Get-AuthenticodeSignature -LiteralPath $candidate -ErrorAction Stop
                if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'Private PowerShell signature validation failed.' }
            }
            return Test-HeadlessPowerShell $candidate
        }
        catch { Write-Verbose "Skipping '$candidate': $($_.Exception.Message)" }
    }
    if (!$AllowDownload) { throw 'PowerShell 7.4+ x64 not found. Run -Setup to provision a private copy, or pass -PowerShell7 C:\path\pwsh.exe.' }
    return Install-HeadlessPowerShell $Root
}
