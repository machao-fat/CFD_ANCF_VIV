[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath(('D:\' + (-join [char[]](0x7814,0x4E8C,0x6587,0x4EF6)) + '\' + (-join [char[]](0x5F00,0x9898,0x51C6,0x5907)) + '\CFD_ANCF_VIV'))
$rootPrefix = $projectRoot.TrimEnd('\') + '\'
$cleanupRoot = Join-Path $projectRoot 'results\cleanup'
$manifestPath = Join-Path $cleanupRoot 'delete_manifest_v8.csv'
$executionLog = Join-Path $cleanupRoot 'delete_execution_v8.json'

function Get-SafePath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full.TrimEnd('\') -eq $projectRoot.TrimEnd('\')) { throw "root itself is not a valid target: $full" }
    if (-not $full.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "target escapes project root: $full" }
    if (-not (Test-Path -LiteralPath $full)) { throw "manifest target is missing: $full" }
    $item = Get-Item -LiteralPath $full -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "target is a reparse point: $full" }
    return $full
}

function Test-RelatedComputeProcess {
    $patterns = 'pimpleFoam|simpleFoam|icoFoam|interFoam|foamRun|decomposePar|reconstructPar|free_viv_driver|MATLAB|matlab'
    $related = Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -match '^(pimpleFoam|simpleFoam|icoFoam|interFoam|foamRun|decomposePar|reconstructPar|matlab|MATLAB)(\.exe)?$') -or
        ($_.Name -match '^python(\.exe)?$' -and $_.CommandLine -match $patterns) -or
        ($_.Name -match '^wsl(\.exe)?$' -and $_.CommandLine -match 'CFD_ANCF_VIV|pimpleFoam|OpenFOAM|free_viv_driver')
    }
    if ($related) {
        $related | Select-Object Name,ProcessId,ParentProcessId,CommandLine | Format-List | Out-String | Write-Output
        throw 'related project compute process is running; deletion stopped before any target'
    }
}

if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "manifest missing: $manifestPath" }
Test-RelatedComputeProcess
$rows = @(Import-Csv -LiteralPath $manifestPath -Encoding UTF8)
if ($rows.Count -eq 0) { throw 'manifest is empty' }
$bad = @($rows | Where-Object { $_.entry_type -notin @('file','directory') -or $_.reparse_checked -ne 'True' -or [string]::IsNullOrWhiteSpace($_.absolute_path) -or ([IO.Path]::GetFullPath($_.absolute_path).TrimEnd('\') -eq $projectRoot.TrimEnd('\')) -or -not ([IO.Path]::GetFullPath($_.absolute_path).StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) -or ([IO.Path]::GetFileName($_.absolute_path) -eq '0') })
if ($bad.Count -gt 0) { throw "manifest safety validation failed for $($bad.Count) rows" }

$deleted = [Collections.Generic.List[object]]::new()
$started = (Get-Date).ToUniversalTime().ToString('o')
$index = 0
foreach ($row in $rows) {
    $index++
    $full = Get-SafePath $row.absolute_path
    $item = Get-Item -LiteralPath $full -Force
    $actualType = if ($item.PSIsContainer) {'directory'} else {'file'}
    if ($actualType -ne $row.entry_type) { throw "target type changed: $full" }
    if ([int64]$row.bytes -le 0) { throw "zero-byte deletion target: $full" }
    if ($row.entry_type -eq 'directory') {
        Remove-Item -LiteralPath $full -Force -Recurse
    } else {
        Remove-Item -LiteralPath $full -Force
    }
    if (Test-Path -LiteralPath $full) { throw "target still exists after deletion: $full" }
    $deleted.Add([pscustomobject]@{absolute_path=$full; relative_path=$row.relative_path; entry_type=$row.entry_type; bytes=[int64]$row.bytes; category=$row.category; reason=$row.reason})
    if (($index % 1000) -eq 0) { Write-Output "deleted $index / $($rows.Count)" }
}
$ended = (Get-Date).ToUniversalTime().ToString('o')
$log = [ordered]@{schema_version='delete_execution_v8'; project_root=$projectRoot; started_utc=$started; ended_utc=$ended; target_count=$rows.Count; deleted_count=$deleted.Count; failed_count=0; deleted_bytes=[int64](($deleted | Measure-Object -Property bytes -Sum).Sum); deleted=@($deleted)}
$log | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $executionLog -Encoding UTF8
Write-Output ($log | ConvertTo-Json -Depth 4)
