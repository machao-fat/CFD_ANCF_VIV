$project=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtime=Join-Path $project 'runtime\user_session_runner_v1'
$status=Join-Path $runtime 'status\runner_status.json'
if (!(Test-Path $status)) { Write-Output 'result=NONE'; exit 0 }
$runId=python -c "import json,sys; print(json.load(open(sys.argv[1],encoding='utf-8')).get('current_run_id') or '')" $status
if ([string]::IsNullOrWhiteSpace($runId)) { Write-Output 'result=NONE'; exit 0 }
$candidate=Join-Path $runtime "completed\$runId.json"
if (!(Test-Path $candidate)) { $candidate=Join-Path $runtime "failed\$runId.json" }
if (!(Test-Path $candidate)) { Write-Output "result=PENDING run_id=$runId"; exit 0 }
Get-Content $candidate -Raw
