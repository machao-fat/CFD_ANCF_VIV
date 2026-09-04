$ErrorActionPreference = 'Stop'

$gmsh = 'D:\Gmsh\gmsh-4.14.1-Windows64\gmsh-4.14.1-Windows64\gmsh.exe'
$geo = Join-Path $PSScriptRoot 'fixed_cylinder_ogrid_3d.geo'
$outDir = 'D:\CFD\stage2_prescribed_motion_ogrid_v1'
$msh = Join-Path $outDir 'stage2_ogrid_3d_gmsh.msh'
$log = Join-Path $outDir 'stage2_ogrid_3d_gmsh.log'

if (-not (Test-Path -LiteralPath $gmsh -PathType Leaf)) { throw "Gmsh not found: $gmsh" }
if (-not (Test-Path -LiteralPath $geo -PathType Leaf)) { throw "Geometry not found: $geo" }
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$stdout = Join-Path $outDir 'stage2_ogrid_3d_gmsh.stdout.log'
$stderr = Join-Path $outDir 'stage2_ogrid_3d_gmsh.stderr.log'
$process = Start-Process -FilePath $gmsh -ArgumentList @($geo, '-3', '-format', 'msh2', '-o', $msh) -Wait -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$output = ((Get-Content -LiteralPath $stdout), (Get-Content -LiteralPath $stderr))
$output | Set-Content -LiteralPath $log -Encoding utf8
if ($process.ExitCode -ne 0 -or ($output | Select-String -SimpleMatch 'Error:')) { throw 'Gmsh 3-D generation failed' }
Write-Output "mesh=$msh"
