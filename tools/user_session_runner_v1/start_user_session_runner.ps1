$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ((Get-Location).Path -ne $project) { throw "Run from project root: $project" }
if ($env:USERNAME -ne 'Administrator') { throw "USERNAME must be Administrator" }
if ($env:SESSIONNAME -ne 'Console') { throw "SESSIONNAME must be Console" }
$runtime = Join-Path $project 'runtime\user_session_runner_v1'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
foreach ($n in 'inbox','accepted','running','completed','failed','status','logs','process','temp','tmp','tmpdir','prefdir') { New-Item -ItemType Directory -Force -Path (Join-Path $runtime $n) | Out-Null }
$existing = Get-ChildItem (Join-Path $runtime 'status\runner_status.json') -ErrorAction SilentlyContinue
if ($existing) {
  $existingPid = python -c "import json,sys; print(json.load(open(sys.argv[1],encoding='utf-8')).get('pid',''))" $existing.FullName
  if ($existingPid -match '^\d+$' -and (Get-Process -Id ([int]$existingPid) -ErrorAction SilentlyContinue)) { throw "Runner already active: PID $existingPid" }
}
Remove-Item (Join-Path $runtime 'status\stop.request') -Force -ErrorAction SilentlyContinue
$env:TEMP=Join-Path $runtime 'temp'; $env:TMP=Join-Path $runtime 'tmp'; $env:TMPDIR=Join-Path $runtime 'tmpdir'; $env:PREFDIR=Join-Path $runtime 'prefdir'
$p = Start-Process -FilePath (Get-Command python).Source -ArgumentList @((Join-Path $PSScriptRoot 'runner.py')) -WorkingDirectory $project -PassThru -WindowStyle Normal
$record = @{ runner_pid=$p.Id; creation_time=(Get-Date).ToUniversalTime().ToString('o'); session_id=1; username=$env:USERNAME; cwd=$project; command_line="python $($PSScriptRoot)\runner.py"; state='STARTING'; runtime=$runtime }
$record | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 (Join-Path $runtime 'status\runner_started.json')
Write-Output "runner_started pid=$($p.Id) runtime=$runtime state=STARTING"
