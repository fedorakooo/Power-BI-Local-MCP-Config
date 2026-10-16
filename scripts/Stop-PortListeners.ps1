[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidateRange(1024,65535)][int[]]$Ports)
$ErrorActionPreference = 'Stop'
$portsToFree = @($Ports | Sort-Object -Unique)
$protectedIds = @(0,4,$PID)
$ancestor = Get-CimInstance Win32_Process -Filter "ProcessId=$PID"
while ($ancestor -and $ancestor.ParentProcessId -and $ancestor.ParentProcessId -notin $protectedIds) {
    $protectedIds += [int]$ancestor.ParentProcessId
    $ancestor = Get-CimInstance Win32_Process -Filter "ProcessId=$($ancestor.ParentProcessId)"
}
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $portsToFree -ErrorAction SilentlyContinue)
$owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
# Validate the entire set before terminating anything.
$targets = @()
foreach ($ownerId in $owners) {
    $process = Get-Process -Id $ownerId -ErrorAction SilentlyContinue
    if (!$process) { continue }
    if ($ownerId -in $protectedIds -or $process.ProcessName -in @('System','Registry','smss','csrss','wininit','services','lsass','winlogon','svchost','explorer','PBIDesktop','msmdsrv')) {
        throw "Port cleanup refused for protected process $($process.ProcessName) PID=$ownerId. Assign another frontend_port."
    }
    $targets += [pscustomobject]@{Process=$process; StartTime=$process.StartTime; Ports=@($listeners | Where-Object OwningProcess -eq $ownerId | Select-Object -ExpandProperty LocalPort -Unique)}
}
try {
    $completed = 0
    foreach ($target in $targets) {
        Write-Progress -Id 13 -Activity 'Free required MCP ports' -Status "Stopping $($target.Process.ProcessName) PID=$($target.Process.Id)" -PercentComplete ([int](100*$completed/[Math]::Max(1,$targets.Count)))
        $current = Get-Process -Id $target.Process.Id -ErrorAction SilentlyContinue
        if ($current -and $current.StartTime -eq $target.StartTime) {
            Write-Host "Stopping $($current.ProcessName) PID=$($current.Id), listening ports=$($target.Ports -join ',')"
            Stop-Process -InputObject $current -Force -ErrorAction Stop
        }
        $completed++
    }
    $deadline = (Get-Date).AddSeconds(5)
    do {
        $remaining = @(Get-NetTCPConnection -State Listen -LocalPort $portsToFree -ErrorAction SilentlyContinue)
        if (!$remaining.Count) { break }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    if ($remaining.Count) { throw "Ports remain occupied: $((@($remaining.LocalPort) | Sort-Object -Unique) -join ','). Another supervisor may be restarting its listeners." }
    Write-Host "Required ports are free: $($portsToFree -join ',')"
} finally { Write-Progress -Id 13 -Activity 'Free required MCP ports' -Completed }
