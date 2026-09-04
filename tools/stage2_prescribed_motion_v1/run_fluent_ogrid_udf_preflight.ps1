$ErrorActionPreference = 'Stop'

$fluent = 'D:\Program Files\ANSYS Inc\v232\fluent\ntbin\win64\fluent.exe'
$journal = Join-Path $PSScriptRoot 'fluent_ogrid_udf_preflight.jou'
$source = Join-Path $PSScriptRoot 'prescribed_motion.c'
$runRoot = 'D:\CFD\stage2_prescribed_motion_ogrid_v1\fluent_udf_preflight_v2'
$stdout = Join-Path $runRoot 'fluent_ogrid_udf_preflight.stdout.log'
$stderr = Join-Path $runRoot 'fluent_ogrid_udf_preflight.stderr.log'

if (-not (Test-Path -LiteralPath $fluent -PathType Leaf)) { throw "Fluent not found: $fluent" }
if (-not (Test-Path -LiteralPath $journal -PathType Leaf)) { throw "Journal not found: $journal" }
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "UDF source not found: $source" }
if (Test-Path -LiteralPath (Join-Path $runRoot 'libudf')) { throw "Refusing to reuse an existing UDF library: $runRoot\libudf" }
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
Copy-Item -LiteralPath $source -Destination (Join-Path $runRoot 'prescribed_motion.c') -ErrorAction Stop

# This starts a fresh Fluent session solely to compile/load the 3ddp library.
# It contains no initialization, dynamic-mesh, or time-advance command.
$process = Start-Process -FilePath $fluent -ArgumentList @('3ddp', '-g', '-i', $journal) -WorkingDirectory $runRoot -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$transcript = Get-ChildItem -LiteralPath $runRoot -Filter '*.trn' | Sort-Object LastWriteTime | Select-Object -Last 1
$transcriptText = if ($transcript) { Get-Content -LiteralPath $transcript.FullName -Raw } else { '' }
if ($process.ExitCode -ne 0 -or $transcriptText -match '(?im)^Error\s*:' -or $transcriptText -notmatch 'stage2_cylinder_motion') {
    throw "Fluent UDF preflight failed; inspect $runRoot"
}
Write-Output "fluent_ogrid_udf_preflight=PASS"
Write-Output "transcript=$($transcript.FullName)"
