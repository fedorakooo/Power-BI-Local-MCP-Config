$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$binary = @(Get-ChildItem (Join-Path $root 'modeling\node_modules\.pnpm') -Recurse -Filter 'powerbi-modeling-mcp.exe')
if ($binary.Count -ne 1) { throw 'Install the pinned modeling package first' }
$config = @{
    mcpServers = @{
        'powerbi-reportserver' = @{
            type = 'stdio'; command = (Join-Path $root '.venv\Scripts\python.exe')
            args = @((Join-Path $root 'server.py'), '--config', (Join-Path $root 'config.local.json'))
            env = @{ PBIRS_STDIO_ACTOR = 'local-operator' }
        }
        'powerbi-modeling' = @{
            type = 'stdio'; command = $binary[0].FullName
            args = @('--start', '--readwrite', '--accepteula')
        }
    }
}
$config | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $root 'mcpServers.local.json') -Encoding UTF8
Write-Host 'Wrote mcpServers.local.json with absolute local paths; no credentials included.'
