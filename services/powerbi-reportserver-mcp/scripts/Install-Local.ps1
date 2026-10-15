param([Parameter(Mandatory=$true)][string]$Python)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
& $Python -m venv .venv
if ($LASTEXITCODE) { throw 'Python virtual environment installation failed' }
& .\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
if ($LASTEXITCODE) { throw 'Dependency installation failed' }
& powershell.exe -NoProfile -NonInteractive -File .\scripts\Install-ReportingServicesTools.ps1
if ($LASTEXITCODE) { throw 'ReportingServicesTools installation failed' }
if (!(Test-Path -LiteralPath config.local.json)) {
    & .\.venv\Scripts\python.exe -m pbirs_mcp.admin init
    if ($LASTEXITCODE) { throw 'Configuration initialization failed' }
}
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls runtime /inheritance:r /grant:r "${identity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE) { throw 'Runtime ACL installation failed' }
& icacls config.local.json /inheritance:r /grant:r "${identity}:F" 'SYSTEM:F' | Out-Null
if ($LASTEXITCODE) { throw 'Configuration ACL installation failed' }
& .\scripts\Register-LocalTask.ps1
Write-Host 'Local Report Server MCP installed. Configure Report Server credentials and enroll a staging report before enabling writes.'
