$ErrorActionPreference = 'Stop'
$project=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path; $status=Join-Path $project 'runtime\performance_optimization_v2\status\runner_status.json'
if (!(Test-Path $status)) { Write-Output 'stage95_runner=NONE'; exit 0 }
$s=Get-Content $status -Raw | ConvertFrom-Json
foreach ($key in 'state','pid','session_id','username','sessionname','run_id','contract_sha256','matlab_pid','coordinator_pid','owned_residual','runtime','message','error_classification') { Write-Output "$key=$($s.$key)" }
