$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$arguments = '-m pbirs_mcp.server --config "' + (Join-Path $root 'config.local.json') + '" --transport http --port 8010'
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $root 'runtime\server.stdout.log') `
    -RedirectStandardError (Join-Path $root 'runtime\server.stderr.log')
$process.Id | Set-Content -LiteralPath (Join-Path $root 'runtime\server.pid')
Write-Host ('MCP process started: ' + $process.Id + '. Endpoint: http://127.0.0.1:8010/mcp')
