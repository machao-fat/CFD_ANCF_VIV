$ErrorActionPreference='Stop'
$project=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path; $runtime=Join-Path $project 'runtime\user_session_runner_v1'; $status=Join-Path $runtime 'status\runner_status.json'
if (!(Test-Path $status)) { Write-Output 'runner_not_found'; exit 0 }
$raw = python -c "import json,sys; print(json.load(open(sys.argv[1],encoding='utf-8'))['pid'])" $status
$runnerPid=[int]$raw
New-Item -ItemType File -Force (Join-Path $runtime 'status\stop.request') | Out-Null
Wait-Process -Id $runnerPid -Timeout 30 -ErrorAction SilentlyContinue
if (Get-Process -Id $runnerPid -ErrorAction SilentlyContinue) { throw "Runner did not exit; no broad termination attempted" }
@{timestamp=(Get-Date).ToUniversalTime().ToString('o'); runner_pid=$runnerPid; residual=0; cleanup='runner_natural_exit'; non_owned_terminated=0} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $runtime 'status\cleanup_audit.json')
Write-Output "runner_stopped pid=$runnerPid residual=0"
