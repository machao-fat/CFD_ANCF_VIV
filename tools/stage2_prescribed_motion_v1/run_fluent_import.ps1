$ErrorActionPreference = 'Stop'
$fluent = 'D:\Program Files\ANSYS Inc\v232\fluent\ntbin\win64\fluent.exe'
$journal = Join-Path $PSScriptRoot 'fluent_read_mesh.jou'
$log = 'D:\研二文件\开题准备\CFD_ANCF_VIV\runtime\stage2_prescribed_motion_v1\fluent\import.log'
if (-not (Test-Path -LiteralPath $fluent -PathType Leaf)) { throw "Fluent not found: $fluent" }
$p = Start-Process -FilePath $fluent -ArgumentList @('3ddp','-g','-i',$journal) -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError ($log + '.stderr')
Write-Host "fluent_import_exit=$($p.ExitCode)"
if ($p.ExitCode -ne 0) { exit $p.ExitCode }
