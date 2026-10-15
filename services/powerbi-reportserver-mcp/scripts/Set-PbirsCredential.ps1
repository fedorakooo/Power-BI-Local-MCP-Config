param([string]$ConfigPath = (Join-Path $PSScriptRoot '..\config.local.json'))
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$credential = Get-Credential -Message 'Dedicated Report Server account. Password is protected with Windows DPAPI for this Windows user.'
if (!$credential) { throw 'Credential entry cancelled' }
$path = Join-Path $config.data_root 'pbirs-credential.xml'
$credential | Export-Clixml -LiteralPath $path
$config | Add-Member -NotePropertyName credential_path -NotePropertyValue $path -Force
$config | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ConfigPath -Encoding UTF8
Write-Host 'Windows-protected credential saved. Restart MCP, then run the discover command.'
