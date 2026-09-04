$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$runtime = Join-Path $root 'runtime\stage382_cpp_worker_precice_three_slice_continue270_to370_v1'
$progressPath = Join-Path $runtime 'logs\progress.json'
if (-not (Test-Path -LiteralPath $progressPath)) {
    Write-Output 'state=STARTING'
    Write-Output "runtime=$runtime"
    exit 0
}
$progress = Get-Content -LiteralPath $progressPath -Raw | ConvertFrom-Json
foreach ($name in @('run_id','case_id','source_global_step','target_global_step','current_global_step','current_time_s','committed_steps','checkpoint_count','mapping_diagnostics_count')) {
    Write-Output ("{0}={1}" -f $name, $progress.$name)
}
Write-Output ("slice_counts={0}" -f ($progress.slice_counts | ConvertTo-Json -Compress))
$launcher = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*stage382_cpp_worker_precice_three_slice_continue270_to370_v1*run_stage382.py*' } | Select-Object -First 1
Write-Output ("launcher_pid={0} alive={1}" -f ($(if($launcher){$launcher.ProcessId}else{'none'}), [bool]$launcher))
foreach ($name in @('structure.stderr','fluid_0000.stderr','fluid_0001.stderr','fluid_0002.stderr')) {
    $path = Join-Path $runtime "logs\$name"
    if (Test-Path -LiteralPath $path) { Write-Output ("{0}_bytes={1}" -f $name.Replace('.','_'), (Get-Item -LiteralPath $path).Length) }
}
Write-Output "runtime=$runtime"
