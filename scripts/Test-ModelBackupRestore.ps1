[CmdletBinding()]
param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference='Stop'
$cfg=Get-Content (Join-Path $Root 'runtime\unattended.json') -Raw | ConvertFrom-Json
$backup=Get-Content (Join-Path $Root 'runtime\last-model-backup.json') -Raw | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $backup.model_file).Hash -ne $backup.model_sha256) { throw 'Backup hash mismatch.' }
$client=Join-Path $Root 'tools\headless\as-client'
foreach($assembly in @('Microsoft.Identity.Client','Microsoft.Identity.Client.Broker','Microsoft.AnalysisServices.Runtime.Core','Microsoft.AnalysisServices.Runtime.Windows','Microsoft.AnalysisServices.Core','Microsoft.AnalysisServices.Tabular.Json','Microsoft.AnalysisServices.Tabular','Microsoft.AnalysisServices.AdomdClient')) {
    [void][Reflection.Assembly]::LoadFrom((Join-Path $client ($assembly+'.dll')))
}
$server=New-Object Microsoft.AnalysisServices.Tabular.Server
$name='McpRestoreValidation_'+[guid]::NewGuid().ToString('N')
$created=$false
try {
    $server.Connect('Data Source=localhost:'+$cfg.ssas_port+';Integrated Security=SSPI;')
    if ($server.Databases.FindByName($name)) { throw 'Restore test target already exists.' }
    $password=Import-Clixml (Join-Path $Root 'runtime\model-backup-credential.xml')
    $info=New-Object Microsoft.AnalysisServices.RestoreInfo
    $info.File=$backup.model_file; $info.DatabaseName=$name; $info.AllowOverwrite=$false
    $info.Security=[Microsoft.AnalysisServices.RestoreSecurity]::IgnoreSecurity
    $info.Password=$password.GetNetworkCredential().Password
    $server.Restore($info)
    $info.Password=$null; $created=$true
    $connection=New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection('Data Source=localhost:'+$cfg.ssas_port+';Initial Catalog='+$name+';Integrated Security=SSPI;')
    try {
        $connection.Open(); $command=$connection.CreateCommand()
        $command.CommandText='EVALUATE ROW("base",[Win Rate %],"updated",[Win Rate % v2])'
        $reader=$command.ExecuteReader()
        try {
            if (!$reader.Read() -or [math]::Abs([double]$reader.GetValue(0)-0.4816) -gt 0.0000001 -or [math]::Abs([double]$reader.GetValue(1)-0.4916) -gt 0.0000001) { throw 'Restored synthetic model values differ.' }
        } finally { $reader.Close(); $command.Dispose() }
    } finally { $connection.Dispose() }
    $result=@{status='encrypted_backup_restore_verified';backup_sha256=$backup.model_sha256;source_database_unchanged=$true;restore_target=$name;values_verified=$true;off_machine=$false}
    $result | ConvertTo-Json | Set-Content (Join-Path $Root 'runtime\model-restore-evidence.json') -Encoding UTF8
    $backup.restore_tested=$true
    $backup | ConvertTo-Json | Set-Content (Join-Path $Root 'runtime\last-model-backup.json') -Encoding UTF8
    $result | ConvertTo-Json
} finally {
    if ($created) {
        $server.Databases.Refresh()
        $temporary=$server.Databases.FindByName($name)
        if ($temporary -and $temporary.Name -eq $name -and $name -match '^McpRestoreValidation_[0-9a-f]{32}$') { $temporary.Drop() }
    }
    if ($server.Connected) { $server.Disconnect() }; $server.Dispose()
}
