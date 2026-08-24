param(
    [string]$GmshExe = 'D:\Gmsh\gmsh-4.14.1-Windows64\gmsh-4.14.1-Windows64\gmsh.exe',
    [string]$OutputRoot = ''
)

$meshDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$geo = Join-Path $meshDir 'fixed_cylinder.geo'
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $meshDir 'generated'
}

if (-not (Test-Path -LiteralPath $GmshExe -PathType Leaf)) {
    throw "Gmsh executable not found: $GmshExe"
}
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$variants = @(
    @{ Name = 'coarse'; Wall = 0.12; Far = 0.70 },
    @{ Name = 'medium'; Wall = 0.08; Far = 0.50 },
    @{ Name = 'fine'; Wall = 0.05; Far = 0.32 }
)

foreach ($variant in $variants) {
    $out = Join-Path $OutputRoot ("fixed_cylinder_{0}.msh" -f $variant.Name)
    $args = @($geo, '-3', '-format', 'msh2', '-o', $out, '-setnumber', 'lcWall', $variant.Wall, '-setnumber', 'lcFar', $variant.Far)
    $process = Start-Process -FilePath $GmshExe -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "Gmsh failed for $($variant.Name) with exit code $($process.ExitCode)"
    }
}

Write-Host "Generated Gmsh meshes in $OutputRoot"
