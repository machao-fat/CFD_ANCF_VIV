$ErrorActionPreference = 'Stop'
$project=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path; $runtime=Join-Path $project 'runtime\performance_optimization_v2'; $status=Join-Path $runtime 'status\runner_status.json'
if (!(Test-Path $status)) { Write-Output 'stage95_runner_not_found'; exit 0 }
$s=Get-Content $status -Raw | ConvertFrom-Json; $runnerPid=[int]$s.pid
New-Item -ItemType File -Force (Join-Path $runtime 'status\stop.request') | Out-Null
Wait-Process -Id $runnerPid -Timeout 30 -ErrorAction SilentlyContinue
if (Get-Process -Id $runnerPid -ErrorAction SilentlyContinue) { throw "Runner did not exit; no broad termination attempted" }
Write-Output "stage95_runner_stopped pid=$runnerPid residual=0"
