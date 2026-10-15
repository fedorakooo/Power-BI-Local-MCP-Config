# Probe installed interpreters without installing Python or changing the system default.
function Get-PowerBIPython([string]$Executable) {
    if (!(Test-Path -LiteralPath $Executable -PathType Leaf)) { throw 'Executable does not exist' }
    $output = & $Executable (Join-Path $PSScriptRoot 'probe_python.py') 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Interpreter probe failed' }
    $info = ($output -join "`n") | ConvertFrom-Json
    if ($info.major -ne 3 -or $info.minor -lt 10) { throw 'Python 3.10 or newer is required' }
    if ($info.bits -ne 64 -or $info.platform -ne 'win32' -or $info.implementation -ne 'CPython') { throw 'Windows CPython x64 is required' }
    if ($info.releaselevel -ne 'final') { throw 'Use a stable Python release' }
    return $info
}

function Select-PowerBIPython([string]$Requested, [string]$ExistingVenv) {
    if ($Requested) {
        try { return Get-PowerBIPython $Requested }
        catch { throw "Requested -Python '$Requested' is not usable: $($_.Exception.Message)" }
    }
    # Keep the installed environment stable. Do not silently migrate it to another runtime.
    if (Test-Path -LiteralPath $ExistingVenv) {
        try { return Get-PowerBIPython $ExistingVenv }
        catch { throw "Existing environment is not usable: $($_.Exception.Message). Use a new deployment folder to rebuild it." }
    }
    $candidates = @()
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $listing = @(& $launcher.Source -0p 2>$null)
            # Prefer the launcher's default (*) and then its other installed runtimes.
            foreach ($line in @($listing | Sort-Object { if ($_ -match '\*') { 0 } else { 1 } })) {
                if ($line -match '([A-Za-z]:\\.+?\.exe)\s*$') { $candidates += $Matches[1] }
            }
        } catch { Write-Verbose 'Python launcher inventory unavailable; checking PATH.' }
    }
    foreach ($name in @('python.exe', 'python3.exe')) {
        foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($command.Source -and $command.Source -notlike '*WindowsApps*') { $candidates += $command.Source }
        }
    }
    foreach ($candidate in @($candidates | Select-Object -Unique)) {
        try { return Get-PowerBIPython $candidate }
        catch { Write-Verbose "Skipping '$candidate': $($_.Exception.Message)" }
    }
    throw 'No suitable Python found. Install stable Windows CPython x64 (3.10+), or pass -Python "C:\path\python.exe". Run py -0p to list installed runtimes.'
}
