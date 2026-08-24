param(
    [string]$StudyRoot = ''
)

$caseRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
if ([string]::IsNullOrWhiteSpace($StudyRoot)) {
    $StudyRoot = Join-Path (Split-Path -Parent $caseRoot) 'fixed_cylinder_study'
}
$sourceCase = $caseRoot
$meshRoot = Join-Path $caseRoot 'mesh\gmsh\generated'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$variants = @(
    @{ Name = 'coarse'; Mesh = 'fixed_cylinder_coarse.msh' },
    @{ Name = 'medium'; Mesh = 'fixed_cylinder_medium.msh' },
    @{ Name = 'fine'; Mesh = 'fixed_cylinder_fine.msh' }
)
$timeSteps = @('0p0025', '0p00125')

New-Item -ItemType Directory -Force -Path $StudyRoot | Out-Null

foreach ($variant in $variants) {
    foreach ($dtName in $timeSteps) {
        $dt = if ($dtName -eq '0p0025') { '0.0025' } else { '0.00125' }
        $name = '{0}_dt{1}' -f $variant.Name, $dtName
        $target = Join-Path $StudyRoot $name
        if (Test-Path -LiteralPath $target) {
            throw "Study case already exists; choose a new StudyRoot or remove it after verifying: $target"
        }

        New-Item -ItemType Directory -Force -Path $target | Out-Null
        Copy-Item -LiteralPath (Join-Path $sourceCase '0') -Destination $target -Recurse
        Copy-Item -LiteralPath (Join-Path $sourceCase '0.orig') -Destination $target -Recurse
        Copy-Item -LiteralPath (Join-Path $sourceCase '0.orig\U') -Destination (Join-Path $target '0\U')
        Copy-Item -LiteralPath (Join-Path $sourceCase '0.orig\p') -Destination (Join-Path $target '0\p')
        Copy-Item -LiteralPath (Join-Path $sourceCase 'scripts') -Destination $target -Recurse
        New-Item -ItemType Directory -Force -Path (Join-Path $target 'constant') | Out-Null
        Copy-Item -LiteralPath (Join-Path $sourceCase 'constant\physicalProperties') -Destination (Join-Path $target 'constant')
        Copy-Item -LiteralPath (Join-Path $sourceCase 'system') -Destination $target -Recurse

        $changeDictionary = @"
FoamFile
{
    format      ascii;
    class       dictionary;
    object      changeDictionaryDict;
}

boundary
{
    front
    {
        type empty;
    }
    back
    {
        type empty;
    }
    lower
    {
        type symmetryPlane;
    }
    upper
    {
        type symmetryPlane;
    }
}
"@
        [System.IO.File]::WriteAllText((Join-Path $target 'system\changeDictionaryDict'), $changeDictionary, $utf8NoBom)

        $control = Join-Path $target 'system\controlDict'
        $text = Get-Content -LiteralPath $control -Raw -Encoding utf8
        $text = [regex]::Replace($text, 'deltaT\s+[^;]+;', "deltaT       $dt;")
        $text = [regex]::Replace($text, 'endTime\s+[^;]+;', 'endTime      20;')
        [System.IO.File]::WriteAllText($control, $text, $utf8NoBom)

        $readme = @"
Gmsh OpenFOAM study case: $name
Mesh: $($variant.Mesh)
deltaT: $dt s
endTime: 20 s
The study case is generated from fixed_cylinder baseline files and must not overwrite the baseline.
"@
        [System.IO.File]::WriteAllText((Join-Path $target 'STUDY_CASE.txt'), $readme, $utf8NoBom)
    }
}

Write-Host "Prepared study cases in $StudyRoot"
