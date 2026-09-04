$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$runtime = Join-Path $root 'runtime\stage381_cpp_worker_precice_three_slice_continue220_to270_v1'
$progressPath = Join-Path $runtime 'logs\progress.json'
$structurePath = Join-Path $runtime 'logs\structure_participant.json'
$pidsPath = Join-Path $runtime 'logs\pids.txt'
if (-not (Test-Path -LiteralPath $progressPath)) {
    Write-Output 'state=STARTING'
    Write-Output "runtime=$runtime"
    exit 0
}
$progress = Get-Content -LiteralPath $progressPath -Raw | ConvertFrom-Json
Write-Output ("run_id={0}" -f $progress.run_id)
Write-Output ("case_id={0}" -f $progress.case_id)
Write-Output ("source_global_step={0}" -f $progress.source_global_step)
Write-Output ("target_global_step={0}" -f $progress.target_global_step)
Write-Output ("current_global_step={0}" -f $progress.current_global_step)
Write-Output ("current_time_s={0}" -f $progress.current_time_s)
Write-Output ("committed_steps={0}" -f $progress.committed_steps)
Write-Output ("slice_counts={0}" -f (($progress.slice_counts | ConvertTo-Json -Compress)))
Write-Output ("checkpoint_count={0}" -f $progress.checkpoint_count)
Write-Output ("mapping_diagnostics_count={0}" -f $progress.mapping_diagnostics_count)
if (Test-Path -LiteralPath $structurePath) {
    $structure = Get-Content -LiteralPath $structurePath -Raw | ConvertFrom-Json
    Write-Output ("finalized={0}" -f $structure.finalized)
    Write-Output ("error={0}" -f $structure.error)
}
if (Test-Path -LiteralPath $pidsPath) {
    Get-Content -LiteralPath $pidsPath | ForEach-Object {
        if ($_ -match '^(?<name>[^=]+)=(?<value>\d+)$') {
            Write-Output ("{0}={1} namespace=WSL" -f $Matches.name, [int]$Matches.value)
        }
    }
}
$launcher = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like '*stage381_cpp_worker_precice_three_slice_continue220_to270_v1*run_stage381.py*'
} | Select-Object -First 1
if ($launcher) {
    Write-Output ("launcher_pid={0} alive=True" -f $launcher.ProcessId)
} else {
    Write-Output 'launcher_pid=none alive=False'
}
Write-Output "runtime=$runtime"
