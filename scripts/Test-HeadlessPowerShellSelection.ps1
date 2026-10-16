# Isolated discovery regression checks; does not install software or change PATH.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Select-HeadlessPowerShell.ps1')
$legacy = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$rejected = $false
try { [void](Test-HeadlessPowerShell $legacy) } catch { $rejected = $true }
if (!$rejected) { throw 'Legacy PowerShell was accepted for .NET 8 clients.' }

# Simulate an empty runtime inventory, as on a new Windows Server installation.
function Test-HeadlessPowerShell([string]$Executable) { throw 'Simulated missing runtime' }
function Get-Command { param($Name,$ErrorAction) return $null }
function Install-HeadlessPowerShell([string]$Root) { return 'private-runtime-provisioned' }
$result = Select-HeadlessPowerShell -Root $env:TEMP -AllowDownload
if ($result -ne 'private-runtime-provisioned') { throw 'Setup did not provision the missing runtime.' }
$rejected = $false
try { [void](Select-HeadlessPowerShell -Root $env:TEMP) } catch { $rejected = $true }
if (!$rejected) { throw 'Non-Setup run unexpectedly installed a runtime.' }
$rejected = $false
try { [void](Select-HeadlessPowerShell -Root $env:TEMP -Requested 'missing-explicit.exe' -AllowDownload) } catch { $rejected = $true }
if (!$rejected) { throw 'Explicit invalid runtime silently fell back to a different executable.' }
Write-Host 'PowerShell discovery checks passed: legacy rejected, missing runtime provisioned only during Setup, explicit path respected.'
