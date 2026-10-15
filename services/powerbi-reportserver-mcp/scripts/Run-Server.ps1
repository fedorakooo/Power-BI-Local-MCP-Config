$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root
$log = Join-Path $root 'runtime\server.log'
& (Join-Path $root '.venv\Scripts\python.exe') -m pbirs_mcp.server --config (Join-Path $root 'config.local.json') --transport http --port 8010 *>> $log
exit $LASTEXITCODE
