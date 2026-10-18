[CmdletBinding()]
param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference='Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'Use the enrolled PowerShell 7 runtime.' }
$cfg=Get-Content (Join-Path $Root 'runtime\unattended.json') -Raw | ConvertFrom-Json
$client=Join-Path $Root 'tools\headless\as-client'
foreach($assembly in @('Microsoft.Identity.Client','Microsoft.Identity.Client.Broker','Microsoft.AnalysisServices.Runtime.Core','Microsoft.AnalysisServices.Runtime.Windows','Microsoft.AnalysisServices.Core','Microsoft.AnalysisServices.Tabular.Json','Microsoft.AnalysisServices.Tabular')) {
    [void][Reflection.Assembly]::LoadFrom((Join-Path $client ($assembly+'.dll')))
}
$password=Import-Clixml -LiteralPath (Join-Path $Root 'runtime\model-backup-credential.xml')
$server=New-Object Microsoft.AnalysisServices.Tabular.Server
try {
    $server.Connect('Data Source=localhost:'+$cfg.ssas_port+';Integrated Security=SSPI;')
    $database=$server.Databases.FindByName('PowerBIMcpHeadlessLab')
    if (!$database -or $database.Model.Annotations.Find('McpHeadlessLab').Value -ne 'synthetic-test-data-only') { throw 'Enrolled synthetic model identity mismatch.' }
    $stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
    $file=Join-Path $cfg.model_backup_directory ('PowerBIMcpHeadlessLab-'+$stamp+'.abf')
    $info=New-Object Microsoft.AnalysisServices.BackupInfo
    $info.File=$file; $info.AllowOverwrite=$false; $info.ApplyCompression=$true
    $info.Password=$password.GetNetworkCredential().Password
    $database.Backup($info)
    $info.Password=$null
    if (!(Test-Path -LiteralPath $file) -or (Get-Item -LiteralPath $file).Length -eq 0) { throw 'Model backup file not confirmed.' }
    # Source snapshots contain no Windows credential XML, local configs or tokens.
    $sourceFile=Join-Path $cfg.source_backup_directory ('headless-sources-'+$stamp+'.zip')
    $sources=@('headless\projects','headless\created-reports') | ForEach-Object { Join-Path $Root $_ } | Where-Object { Test-Path -LiteralPath $_ }
    Compress-Archive -LiteralPath $sources -DestinationPath $sourceFile
    $result=@{time_utc=[DateTime]::UtcNow.ToString('o');status='backup_created';database='PowerBIMcpHeadlessLab';model_file=$file;model_sha256=(Get-FileHash -LiteralPath $file).Hash;source_file=$sourceFile;source_sha256=(Get-FileHash -LiteralPath $sourceFile).Hash;encrypted=$true;off_machine=$false;restore_tested=$false}
    $result | ConvertTo-Json | Set-Content (Join-Path $Root 'runtime\last-model-backup.json') -Encoding UTF8
    # Delete only old files with these owned prefixes inside the enrolled directories.
    foreach($entry in @(@($cfg.model_backup_directory,'PowerBIMcpHeadlessLab-*.abf'),@($cfg.source_backup_directory,'headless-sources-*.zip'))) {
        $base=[IO.Path]::GetFullPath($entry[0]).TrimEnd('\')+'\'
        Get-ChildItem -LiteralPath $entry[0] -Filter $entry[1] -File | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } | ForEach-Object {
            if (![IO.Path]::GetFullPath($_.FullName).StartsWith($base,[StringComparison]::OrdinalIgnoreCase)) { throw 'Backup retention path escaped enrollment.' }
            Remove-Item -LiteralPath $_.FullName
        }
    }
    $result | ConvertTo-Json
} finally { if ($server.Connected) { $server.Disconnect() }; $server.Dispose() }
