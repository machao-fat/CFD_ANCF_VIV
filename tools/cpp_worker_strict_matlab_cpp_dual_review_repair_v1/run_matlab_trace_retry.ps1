$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtime = Join-Path $root 'runtime\cpp_worker_strict_matlab_cpp_dual_review_repair_v1_retry_001'
$out = Join-Path $runtime 'matlab_step560_trace.json'
$stdout = Join-Path $runtime 'matlab_stdout.log'
$stderr = Join-Path $runtime 'matlab_stderr.log'
$temp = Join-Path $runtime 'temp'
$tmp = Join-Path $runtime 'tmp'
$tmpdir = Join-Path $runtime 'tmpdir'
$prefdir = Join-Path $runtime 'prefdir'
New-Item -ItemType Directory -Force -Path $runtime,$temp,$tmp,$tmpdir,$prefdir | Out-Null
$env:TEMP = $temp
$env:TMP = $tmp
$env:TMPDIR = $tmpdir
$env:MATLAB_PREFDIR = $prefdir
$matlab = 'D:\Program Files\MATLAB\R2021b\bin\matlab.exe'
$tool = Join-Path $root 'tools\cpp_worker_strict_matlab_cpp_dual_review_repair_v1'
$expr = "addpath('$tool'); export_step560_matlab_intermediate_trace('$out');"
& $matlab -batch $expr 1> $stdout 2> $stderr
$code = $LASTEXITCODE
[ordered]@{
  run_id = 'cpp_worker_strict_matlab_cpp_dual_review_retry_001'
  runtime = $runtime
  output = $out
  stdout = $stdout
  stderr = $stderr
  exit_code = $code
  trace_exists = (Test-Path -LiteralPath $out)
} | ConvertTo-Json -Depth 3
exit $code
