param([Parameter(Mandatory=$true)][string]$Python)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Select-Python.ps1')
$selected = Select-PowerBIPython -Requested $Python -ExistingVenv 'C:\nonexistent-venv\python.exe'
if ($selected.major -ne 3 -or $selected.bits -ne 64) { throw 'Explicit selection failed' }
$existing = Select-PowerBIPython -ExistingVenv $Python
if ($existing.executable -ne $selected.executable) { throw 'Existing environment was not reused' }
$failed = $false
try { Select-PowerBIPython -Requested 'C:\nonexistent-runtime\python.exe' -ExistingVenv $Python | Out-Null }
catch { $failed = $_.Exception.Message -like '*Requested -Python*' }
if (!$failed) { throw 'An invalid explicit runtime must fail instead of falling back' }
$automatic = Select-PowerBIPython -ExistingVenv 'C:\nonexistent-venv\python.exe'
if (!$automatic.executable) { throw 'Automatic installed-runtime detection failed' }
Write-Host 'PASS: explicit selection, existing environment reuse, invalid explicit runtime rejection, automatic discovery'
