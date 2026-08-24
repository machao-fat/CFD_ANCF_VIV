$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ((Get-Location).Path -ne $project) { throw "Run from project root: $project" }
if ($env:USERNAME -ne 'Administrator') { throw 'USERNAME must be Administrator' }
if ($env:SESSIONNAME -ne 'Console') { throw 'SESSIONNAME must be Console' }
$sessionId = (Get-Process -Id $PID).SessionId
if ([int]$sessionId -ne 1) { throw "Current PowerShell is SessionId=$sessionId; required SessionId=1" }
if ($project.Substring(0,2).ToUpperInvariant() -ne 'D:') { throw 'Project must be on D:' }
$runtime = Join-Path $project 'runtime\performance_optimization_v2'
foreach ($name in 'inbox','accepted','running','completed','failed','status','logs','process','temp','tmp','tmpdir','prefdir') { New-Item -ItemType Directory -Force -Path (Join-Path $runtime $name) | Out-Null }
$status = Join-Path $runtime 'status\runner_status.json'
if (Test-Path $status) {
  $existing = Get-Content $status -Raw | ConvertFrom-Json
  if ($existing.pid -and (Get-Process -Id ([int]$existing.pid) -ErrorAction SilentlyContinue)) { throw "Stage95 runner already active: PID $($existing.pid)" }
}
Remove-Item (Join-Path $runtime 'status\stop.request') -Force -ErrorAction SilentlyContinue
$env:TEMP=Join-Path $runtime 'temp'; $env:TMP=Join-Path $runtime 'tmp'; $env:TMPDIR=Join-Path $runtime 'tmpdir'; $env:PREFDIR=Join-Path $runtime 'prefdir'; $env:CFD_ANCF_SESSION_ID=[string]$sessionId
$python = (Get-Command python).Source
$p = Start-Process -FilePath $python -ArgumentList @((Join-Path $PSScriptRoot 'runner.py')) -WorkingDirectory $project -PassThru -WindowStyle Normal
@{runner_pid=$p.Id; creation_time=(Get-Date).ToUniversalTime().ToString('o'); session_id=[int]$sessionId; username=$env:USERNAME; cwd=$project; runtime=$runtime; command_line="python $($PSScriptRoot)\runner.py"; state='STARTING'} | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 (Join-Path $runtime 'status\runner_started.json')
Write-Output "stage95_runner_started pid=$($p.Id) runtime=$runtime state=STARTING"
