$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script = Join-Path $PSScriptRoot 'run_stage372.py'
$runtime = Join-Path $root 'runtime\stage372_cpp_worker_precice_three_slice_80p2_to200_v1_retry3'
$logs = Join-Path $runtime 'logs'
New-Item -ItemType Directory -Force -Path $runtime, $logs | Out-Null
$preflight = Join-Path $runtime 'logs\preflight.json'
$hasRunOutput = @('structure_participant.json','progress.json','returns.txt') | Where-Object { Test-Path (Join-Path $logs $_) }
if ((-not (Test-Path $preflight)) -and ((Get-ChildItem -Force $runtime | Where-Object { $_.Name -notin @('logs','process','storage','precice-sockets') }).Count -gt 0)) { throw "Stage 372 runtime is not empty; refusing reuse" }
if ($hasRunOutput.Count -gt 0) { throw "Stage 372 runtime already has run output; refusing reuse" }
$python = (Get-Command python -ErrorAction Stop).Source
$proc = Start-Process -FilePath $python -ArgumentList @('-u', $script) -WorkingDirectory $root -RedirectStandardOutput (Join-Path $logs 'launcher_host.stdout') -RedirectStandardError (Join-Path $logs 'launcher_host.stderr') -PassThru -WindowStyle Hidden
Set-Content -Path (Join-Path $logs 'host_pid.txt') -Value $proc.Id -Encoding ascii
Write-Output ("stage372_started pid={0} runtime={1} source=80.2s target=200.0s" -f $proc.Id, $runtime)
