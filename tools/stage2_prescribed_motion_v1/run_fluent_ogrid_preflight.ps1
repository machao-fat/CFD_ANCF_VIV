$ErrorActionPreference = 'Stop'

$fluent = 'D:\Program Files\ANSYS Inc\v232\fluent\ntbin\win64\fluent.exe'
$journal = Join-Path $PSScriptRoot 'fluent_read_ogrid_mesh_3d.jou'
$mesh = 'D:\CFD\stage2_prescribed_motion_ogrid_v1\openfoam_ogrid_3d\fluentInterface\openfoam_ogrid_3d.msh'
$runRoot = 'D:\CFD\stage2_prescribed_motion_ogrid_v1\fluent_preflight'
$stdout = Join-Path $runRoot 'fluent_ogrid_import.stdout.log'
$stderr = Join-Path $runRoot 'fluent_ogrid_import.stderr.log'

if (-not (Test-Path -LiteralPath $fluent -PathType Leaf)) { throw "Fluent not found: $fluent" }
if (-not (Test-Path -LiteralPath $journal -PathType Leaf)) { throw "Journal not found: $journal" }
if (-not (Test-Path -LiteralPath $mesh -PathType Leaf)) { throw "Validated O-grid mesh not found: $mesh" }
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

# The single slice is represented as one z-cell with front/back symmetry in
# Fluent. This preflight intentionally does not load a UDF, enable dynamic
# mesh, initialize, or advance time.
$process = Start-Process -FilePath $fluent -ArgumentList @('3ddp', '-g', '-i', $journal) -WorkingDirectory $runRoot -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$combined = ((Get-Content -LiteralPath $stdout), (Get-Content -LiteralPath $stderr)) -join [Environment]::NewLine
if ($process.ExitCode -ne 0 -or $combined -match '(?im)^Error\s*:|negative cell volume|Update-Dynamic-Mesh failed') {
    throw "Fluent 2-D O-grid import preflight failed; inspect $stdout and $stderr"
}
Write-Output "fluent_ogrid_import_preflight=PASS"
Write-Output "stdout=$stdout"
Write-Output "stderr=$stderr"
