$project=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$p=Join-Path $project 'runtime\user_session_runner_v1\status\runner_status.json'
python (Join-Path $PSScriptRoot 'status.py') $p
