$ErrorActionPreference='Stop'
$project=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtime=Join-Path $project 'runtime\user_session_runner_v1'
python (Join-Path $PSScriptRoot 'write_probe.py') $project $runtime
