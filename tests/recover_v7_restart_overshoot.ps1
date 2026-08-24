$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$archiveDir = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'archives\stage3_v7'))
$archive = [System.IO.Path]::GetFullPath((Join-Path $archiveDir 'restart_overshoot_after_221p25.zip'))
$caseRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'cases\openfoam\single_dof_free_v6_to200'))
$targets = @(
    [System.IO.Path]::GetFullPath((Join-Path $caseRoot '221.5')),
    [System.IO.Path]::GetFullPath((Join-Path $caseRoot '221.75')),
    [System.IO.Path]::GetFullPath((Join-Path $caseRoot '222')),
    [System.IO.Path]::GetFullPath((Join-Path $caseRoot '222.25'))
)
if (Test-Path -LiteralPath $archive) { throw "archive already exists: $archive" }
if (-not (Test-Path -LiteralPath $archiveDir)) { New-Item -ItemType Directory -Path $archiveDir | Out-Null }
foreach ($target in $targets) {
    if (-not $target.StartsWith($projectRoot + '\')) { throw "target outside project root: $target" }
    if (-not (Test-Path -LiteralPath $target -PathType Container)) { throw "missing target: $target" }
    $item = Get-Item -LiteralPath $target
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "reparse target: $target" }
}
Compress-Archive -LiteralPath $targets -DestinationPath $archive -CompressionLevel Optimal
$zip = [IO.Compression.ZipFile]::OpenRead($archive)
try {
    if ($zip.Entries.Count -lt 28) { throw "archive entry count too small: $($zip.Entries.Count)" }
    $stream = $zip.Entries[0].Open()
    try {
        $buffer = New-Object byte[] 64
        if ($stream.Read($buffer, 0, 64) -le 0) { throw 'archive random read failed' }
    } finally { $stream.Dispose() }
} finally { $zip.Dispose() }
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
foreach ($target in $targets) { Remove-Item -LiteralPath $target -Recurse -Force }
foreach ($target in $targets) { if (Test-Path -LiteralPath $target) { throw "delete verification failed: $target" } }
[pscustomobject]@{ archive = $archive; sha256 = $hash; deleted = $targets } | ConvertTo-Json -Depth 3
