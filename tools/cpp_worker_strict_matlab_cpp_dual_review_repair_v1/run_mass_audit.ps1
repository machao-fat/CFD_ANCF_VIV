$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtime=Join-Path $root 'runtime\cpp_worker_strict_matlab_cpp_dual_review_repair_v1_retry_001\mass_audit_001'
$out=Join-Path $runtime 'matlab_mass_audit.json'; New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$seed=Join-Path $root 'runtime\cpp_worker_persistent_ipc_v1\matlab_dual_011\accepted_step559_seed.mat'
$tool=$PSScriptRoot; $stdout=Join-Path $runtime 'stdout.log'; $stderr=Join-Path $runtime 'stderr.log'
$matlab='D:\Program Files\MATLAB\R2021b\bin\matlab.exe'
$expr="addpath('$tool'); export_mass_audit('$seed','$out');"
& $matlab -batch $expr 1> $stdout 2> $stderr
$code=$LASTEXITCODE
[ordered]@{runtime=$runtime;output=$out;exit_code=$code;trace_exists=(Test-Path -LiteralPath $out);stdout=$stdout;stderr=$stderr} | ConvertTo-Json -Depth 3
exit $code
