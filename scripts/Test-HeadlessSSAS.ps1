param(
    [Parameter(Mandatory=$true)][ValidatePattern('^localhost(:[0-9]{1,5}|\\PBIMCPTEST)$')][string]$Server,
    [Parameter(Mandatory=$true)][string]$ClientDirectory,
    [switch]$CreateSyntheticModel,
    [switch]$DeployTestMeasure,
    [string]$EvidencePath
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'Use PowerShell 7 for the .NET 8 Analysis Services client libraries.' }
$client = (Resolve-Path -LiteralPath $ClientDirectory).Path
foreach ($assembly in @('Microsoft.Identity.Client','Microsoft.Identity.Client.Broker',
    'Microsoft.AnalysisServices.Runtime.Core','Microsoft.AnalysisServices.Runtime.Windows',
    'Microsoft.AnalysisServices.Core','Microsoft.AnalysisServices.Tabular.Json',
    'Microsoft.AnalysisServices.Tabular','Microsoft.AnalysisServices.AdomdClient')) {
    [void][Reflection.Assembly]::LoadFrom((Join-Path $client ($assembly + '.dll')))
}
$databaseName = 'PowerBIMcpHeadlessLab'
$tom = New-Object Microsoft.AnalysisServices.Tabular.Server
try {
    $tom.Connect('Data Source=' + $Server + ';Integrated Security=SSPI;')
    $database = $tom.Databases.FindByName($databaseName)
    if ($CreateSyntheticModel) {
        if ($database) { throw 'Lab database already exists; refusing to replace it.' }
        $database = New-Object Microsoft.AnalysisServices.Tabular.Database
        $database.ID = $databaseName; $database.Name = $databaseName; $database.CompatibilityLevel = 1500
        $database.Model = New-Object Microsoft.AnalysisServices.Tabular.Model
        $database.Model.Culture = 'en-US'
        $annotation = New-Object Microsoft.AnalysisServices.Tabular.Annotation
        $annotation.Name = 'McpHeadlessLab'; $annotation.Value = 'synthetic-test-data-only'
        $database.Model.Annotations.Add($annotation)
        $table = New-Object Microsoft.AnalysisServices.Tabular.Table
        $table.Name = 'Sales'
        foreach ($definition in @(@('Manager','String'),@('Won','Int64'),@('Total','Int64'))) {
            $column = New-Object Microsoft.AnalysisServices.Tabular.CalculatedTableColumn
            $column.Name = $definition[0]; $column.SourceColumn = '[' + $definition[0] + ']'
            $column.DataType = [Enum]::Parse([Microsoft.AnalysisServices.Tabular.DataType],$definition[1])
            $table.Columns.Add($column)
        }
        $partition = New-Object Microsoft.AnalysisServices.Tabular.Partition
        $partition.Name = 'SyntheticRows'
        $partition.Source = New-Object Microsoft.AnalysisServices.Tabular.CalculatedPartitionSource
        $partition.Source.Expression = 'DATATABLE("Manager", STRING, "Won", INTEGER, "Total", INTEGER, {{"Cara Losch", 4979, 10000}, {"Other", 4653, 10000}})'
        $table.Partitions.Add($partition)
        $measure = New-Object Microsoft.AnalysisServices.Tabular.Measure
        $measure.Name = 'Win Rate %'; $measure.Expression = "DIVIDE(SUM('Sales'[Won]), SUM('Sales'[Total]))"; $measure.FormatString = '0.00%'
        $table.Measures.Add($measure)
        $database.Model.Tables.Add($table)
        [void]$tom.Databases.Add($database)
        [void]$database.Update([Microsoft.AnalysisServices.UpdateOptions]::ExpandFull)
        $database.Model.RequestRefresh([Microsoft.AnalysisServices.Tabular.RefreshType]::Full)
        [void]$database.Model.SaveChanges()
    }
    if (!$database) { throw 'Synthetic lab database not found.' }
    if ($database.Model.Annotations.Find('McpHeadlessLab').Value -ne 'synthetic-test-data-only') { throw 'Database is not the enrolled synthetic lab.' }
    if ($DeployTestMeasure) {
        $table = $database.Model.Tables.Find('Sales')
        if ($table.Measures.Find('Win Rate % v2')) { throw 'Test measure already exists; refusing to overwrite it.' }
        $measure = New-Object Microsoft.AnalysisServices.Tabular.Measure
        $measure.Name = 'Win Rate % v2'; $measure.Expression = '[Win Rate %] + 0.01'; $measure.FormatString = '0.00%'
        $table.Measures.Add($measure)
        [void]$database.Model.SaveChanges()
    }
    $connection = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection('Data Source=' + $Server + ';Initial Catalog=' + $databaseName + ';Integrated Security=SSPI;')
    try {
        $connection.Open()
        $command = $connection.CreateCommand()
        $query = 'EVALUATE ROW("base", [Win Rate %], "Cara", CALCULATE([Win Rate %], Sales[Manager] = "Cara Losch")'
        $hasV2 = [bool]$database.Model.Tables.Find('Sales').Measures.Find('Win Rate % v2')
        if ($hasV2) { $query += ', "updated", [Win Rate % v2]' }
        $command.CommandText = $query + ')'
        $reader = $command.ExecuteReader()
        try {
            if (!$reader.Read()) { throw 'DAX verification returned no row.' }
            $base = [double]$reader.GetValue(0); $cara = [double]$reader.GetValue(1)
            if ([math]::Abs($base - 0.4816) -gt 0.0000001 -or [math]::Abs($cara - 0.4979) -gt 0.0000001) { throw 'Synthetic DAX results do not match expected data.' }
            $result = [ordered]@{status='ssas_headless_verified';server=$Server;database=$databaseName;data='synthetic-test-only';base=$base;Cara=$cara;gui_save_used=$false;test_measure_present=$hasV2;reportserver_render_verified=$false}
            if ($hasV2) {
                $updated = [double]$reader.GetValue(2)
                if ([math]::Abs($updated - 0.4916) -gt 0.0000001) { throw 'Deployed measure DAX verification failed.' }
                $result.updated = $updated
            }
            $json = $result | ConvertTo-Json
            if ($EvidencePath) { $json | Set-Content -LiteralPath $EvidencePath -Encoding UTF8 }
            $json
        } finally { $reader.Close(); $command.Dispose() }
    } finally { $connection.Dispose() }
} finally { if ($tom.Connected) { $tom.Disconnect() }; $tom.Dispose() }
