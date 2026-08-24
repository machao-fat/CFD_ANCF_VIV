$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$cleanupDir = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'results\cleanup'))
$targets = @(Get-ChildItem -LiteralPath $projectRoot -Recurse -File -Force | Where-Object { $_.Name -like '*.pyc' -or $_.Directory.Name -eq '__pycache__' })
$records = @()
foreach ($target in $targets) {
    $absolute = [System.IO.Path]::GetFullPath($target.FullName)
    if (-not $absolute.StartsWith($projectRoot + '\')) { throw "target outside project root: $absolute" }
    if ($target.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "reparse target: $absolute" }
    $hash = (Get-FileHash -LiteralPath $absolute -Algorithm SHA256).Hash
    $records += [pscustomobject]@{ absolute_path = $absolute; size_bytes = $target.Length; sha256_before_delete = $hash; state = 'DELETE_REGENERABLE'; reason = 'Python bytecode/cache; reproducible from source' }
}
foreach ($target in $targets) { Remove-Item -LiteralPath $target.FullName -Force }
foreach ($target in $targets) { if (Test-Path -LiteralPath $target.FullName) { throw "delete verification failed: $($target.FullName)" } }
$payload = [pscustomobject]@{ schema_version = 'deleted_paths_v7'; operation = 'DELETE_REGENERABLE'; project_root = $projectRoot; deleted_at_utc = [DateTime]::UtcNow.ToString('o'); count = $records.Count; total_size_bytes = (($records | Measure-Object size_bytes -Sum).Sum); records = $records }
$payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $cleanupDir 'deleted_paths_v7.json') -Encoding UTF8
$payload | ConvertTo-Json -Depth 4
