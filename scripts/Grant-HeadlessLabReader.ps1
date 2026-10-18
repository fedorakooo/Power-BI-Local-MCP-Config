param(
    [Parameter(Mandatory=$true)][ValidatePattern('^localhost(:[0-9]{1,5}|\\PBIMCPTEST)$')][string]$Server,
    [Parameter(Mandatory=$true)][string]$ClientDirectory,
    [Parameter(Mandatory=$true)][ValidatePattern('^[^\\\r\n;]+\\[^\\\r\n;]+$')][string]$Member,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'Use PowerShell 7.4+ x64.' }
$account = [Security.Principal.NTAccount]::new($Member)
$sid = $account.Translate([Security.Principal.SecurityIdentifier])
# Reject broad built-in identities; enroll a named Windows account explicitly.
if ($sid.Value -notmatch '^S-1-5-21-') { throw 'Use a named local/domain account, not a broad built-in identity.' }
$client = (Resolve-Path -LiteralPath $ClientDirectory).Path
foreach ($assembly in @('Microsoft.Identity.Client','Microsoft.Identity.Client.Broker',
    'Microsoft.AnalysisServices.Runtime.Core','Microsoft.AnalysisServices.Runtime.Windows',
    'Microsoft.AnalysisServices.Core','Microsoft.AnalysisServices.Tabular.Json','Microsoft.AnalysisServices.Tabular')) {
    [void][Reflection.Assembly]::LoadFrom((Join-Path $client ($assembly + '.dll')))
}
$tom = [Microsoft.AnalysisServices.Tabular.Server]::new()
try {
    $tom.Connect('Data Source=' + $Server + ';Integrated Security=SSPI;')
    $database = $tom.Databases.FindByName('PowerBIMcpHeadlessLab')
    if (!$database -or $database.Model.Annotations.Find('McpHeadlessLab').Value -ne 'synthetic-test-data-only') {
        throw 'Only the enrolled synthetic lab database may be changed.'
    }
    $roleName = 'McpHeadlessLabReaders'
    $role = $database.Model.Roles.Find($roleName)
    if ($role -and ([string]$role.ModelPermission -ne 'Read' -or $role.TablePermissions.Count -gt 0)) {
        throw 'Existing role differs from the expected unrestricted lab Read role; refusing to modify it.'
    }
    $present = $false
    if ($role) { $present = @($role.Members | Where-Object { $_.MemberID -eq $sid.Value -or $_.MemberName -ieq $Member }).Count -gt 0 }
    if (!$ValidateOnly -and !$present) {
        if (!$role) {
            $role = [Microsoft.AnalysisServices.Tabular.ModelRole]::new()
            $role.Name = $roleName
            $role.ModelPermission = [Microsoft.AnalysisServices.Tabular.ModelPermission]::Read
            $database.Model.Roles.Add($role)
        }
        $entry = [Microsoft.AnalysisServices.Tabular.WindowsModelRoleMember]::new()
        $entry.MemberName = $Member; $entry.MemberID = $sid.Value
        $role.Members.Add($entry)
        [void]$database.Model.SaveChanges()
    }
    [ordered]@{database=$database.Name;role=$roleName;permission='Read';member=$Member;
        already_present=$present;validate_only=[bool]$ValidateOnly;changed=(!$ValidateOnly -and !$present);
        reportserver_render_verified=$false} | ConvertTo-Json
} finally { if ($tom.Connected) { $tom.Disconnect() }; $tom.Dispose() }
