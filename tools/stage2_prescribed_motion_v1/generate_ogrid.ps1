$ErrorActionPreference = 'Stop'

$gmsh = 'D:\Gmsh\gmsh-4.14.1-Windows64\gmsh-4.14.1-Windows64\gmsh.exe'
$geo = Join-Path $PSScriptRoot 'fixed_cylinder_ogrid_2d.geo'
$outDir = 'D:\CFD\stage2_prescribed_motion_ogrid_v1'
$msh = Join-Path $outDir 'stage2_ogrid.msh'
$candidate = Join-Path $outDir 'stage2_ogrid.candidate.msh'
$log = Join-Path $outDir 'stage2_ogrid.gmsh.log'
$audit = Join-Path $outDir 'stage2_ogrid.audit.json'
$meshAudit = Join-Path $PSScriptRoot 'audit_ogrid_mesh.py'

if (-not (Test-Path -LiteralPath $gmsh -PathType Leaf)) {
    throw "Gmsh not found: $gmsh"
}
if (-not (Test-Path -LiteralPath $geo -PathType Leaf)) {
    throw "Geometry not found: $geo"
}
if (-not (Test-Path -LiteralPath $meshAudit -PathType Leaf)) {
    throw "Mesh audit not found: $meshAudit"
}
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$genStdout = Join-Path $outDir 'stage2_ogrid.generate.stdout.log'
$genStderr = Join-Path $outDir 'stage2_ogrid.generate.stderr.log'
$gen = Start-Process -FilePath $gmsh -ArgumentList @($geo, '-2', '-format', 'msh2', '-o', $candidate) -Wait -PassThru -NoNewWindow -RedirectStandardOutput $genStdout -RedirectStandardError $genStderr
$genExit = $gen.ExitCode
$genOutput = (Get-Content -LiteralPath $genStdout), (Get-Content -LiteralPath $genStderr)
$genOutput | Set-Content -LiteralPath $log -Encoding utf8
Write-Output $genOutput
if ($genExit -ne 0 -or -not (Test-Path -LiteralPath $candidate -PathType Leaf) -or ($genOutput | Select-String -SimpleMatch 'Error:')) {
    throw "Gmsh generation failed"
}

$checkStdout = Join-Path $outDir 'stage2_ogrid.check.stdout.log'
$checkStderr = Join-Path $outDir 'stage2_ogrid.check.stderr.log'
$check = Start-Process -FilePath $gmsh -ArgumentList @($candidate, '-check') -Wait -PassThru -NoNewWindow -RedirectStandardOutput $checkStdout -RedirectStandardError $checkStderr
$checkExit = $check.ExitCode
$checkOutput = (Get-Content -LiteralPath $checkStdout), (Get-Content -LiteralPath $checkStderr)
$checkOutput | Add-Content -LiteralPath $log -Encoding utf8
Write-Output $checkOutput
if ($checkExit -ne 0 -or ($checkOutput | Select-String -SimpleMatch 'Error:')) {
    throw "Gmsh mesh check failed"
}

$python = Get-Command python -ErrorAction Stop
& $python.Source $meshAudit $candidate '--output' $audit
if ($LASTEXITCODE -ne 0) {
    throw "Independent mesh audit failed"
}

if (Test-Path -LiteralPath $msh -PathType Leaf) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Copy-Item -LiteralPath $msh -Destination (Join-Path $outDir "stage2_ogrid.preexisting_$stamp.msh")
}
Move-Item -LiteralPath $candidate -Destination $msh -Force

# Record the promoted pathname in the durable audit artifact.
& $python.Source $meshAudit $msh '--output' $audit
if ($LASTEXITCODE -ne 0) {
    throw "Post-promotion mesh audit failed"
}

$hash = (Get-FileHash -LiteralPath $msh -Algorithm SHA256).Hash.ToLowerInvariant()
$geoHash = (Get-FileHash -LiteralPath $geo -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output "mesh=$msh"
Write-Output "mesh_sha256=$hash"
Write-Output "geo_sha256=$geoHash"
Write-Output "audit=$audit"
