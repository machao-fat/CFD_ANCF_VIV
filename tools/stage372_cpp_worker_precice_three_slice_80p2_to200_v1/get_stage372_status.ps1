$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$logs = Join-Path $root 'runtime\stage372_cpp_worker_precice_three_slice_80p2_to200_v1_retry3\logs'
$progress = Join-Path $logs 'progress.json'
if (Test-Path $progress) { Get-Content -Raw $progress } else { Write-Output 'progress=NOT_YET_AVAILABLE' }
if (Test-Path (Join-Path $logs 'returns.txt')) { Get-Content (Join-Path $logs 'returns.txt') }
if (Test-Path (Join-Path $logs 'structure.stderr')) {
    $e = Get-Content -Raw (Join-Path $logs 'structure.stderr')
    if ($null -eq $e) { $e = '' }
    $e = $e.Trim()
    if ($e) { Write-Output ("structure_stderr=" + $e) } else { Write-Output 'structure_stderr=none' }
}
0..2 | ForEach-Object {
    $p = Join-Path $logs ("fluid_{0:D4}.stderr" -f $_)
    if (Test-Path $p) {
        $e = Get-Content -Raw $p
        if ($null -eq $e) { $e = '' }
        $e = $e.Trim()
        if ($e) { Write-Output (("fluid_{0:D4}_stderr=" -f $_) + $e) } else { Write-Output ("fluid_{0:D4}_stderr=none" -f $_) }
    }
}
