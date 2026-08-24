[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# Build the required Chinese path from code points so this script is not
# dependent on the active PowerShell code page.
$projectRoot = [IO.Path]::GetFullPath(('D:\' + (-join [char[]](0x7814,0x4E8C,0x6587,0x4EF6)) + '\' + (-join [char[]](0x5F00,0x9898,0x51C6,0x5907)) + '\CFD_ANCF_VIV'))
$rootPrefix = $projectRoot.TrimEnd('\') + '\'
$cleanupRoot = Join-Path $projectRoot 'results\cleanup'
$docsRoot = Join-Path $projectRoot 'docs'

function Assert-Inside([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full.TrimEnd('\') -eq $projectRoot.TrimEnd('\')) { throw "project root is not a delete target: $full" }
    if (-not $full.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "target escapes project root: $full" }
    if (-not (Test-Path -LiteralPath $full)) { throw "target is missing: $full" }
    $item = Get-Item -LiteralPath $full -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "reparse point target is forbidden: $full" }
    return $full
}

function Relative([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "path outside project root: $full" }
    return $full.Substring($rootPrefix.Length).Replace('\','/')
}

function Is-ProtectedTree([string]$Path) {
    $rel = (Relative $Path).ToLowerInvariant()
    return $rel -eq 'src' -or $rel.StartsWith('src/') -or
           $rel -eq 'tests' -or $rel.StartsWith('tests/') -or
           $rel -eq 'docs' -or $rel.StartsWith('docs/') -or
           $rel -eq '.git' -or $rel.StartsWith('.git/')
}

function Is-ReservedCaseDirectory([string]$Path) {
    $name = ([IO.DirectoryInfo]$Path).Name.ToLowerInvariant()
    return $name -in @('0','constant','system','coupling','postprocessing','scripts')
}

function Get-Inventory {
    $stack = [Collections.Generic.Stack[string]]::new()
    $stack.Push($projectRoot)
    $files = [int64]0
    $dirs = [int64]0
    $bytes = [int64]0
    $zeroFiles = [Collections.Generic.List[object]]::new()
    $cacheDirs = [Collections.Generic.List[object]]::new()
    $emptyDirs = [Collections.Generic.List[object]]::new()
    $reparse = [Collections.Generic.List[string]]::new()
    $dirSizes = @{}

    while ($stack.Count -gt 0) {
        $current = $stack.Pop()
        $childCount = 0
        foreach ($entry in ([IO.DirectoryInfo]::new($current)).EnumerateFileSystemInfos()) {
            $childCount++
            $attrs = $entry.Attributes
            if (($attrs -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                $reparse.Add($entry.FullName)
                continue
            }
            if ($entry -is [IO.DirectoryInfo]) {
                $dirs++
                $stack.Push($entry.FullName)
                $dirSizes[$entry.FullName] = [int64]0
                if ($entry.Name -in @('__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','dynamicCode')) {
                    $cacheDirs.Add([pscustomobject]@{absolute_path=$entry.FullName; relative_path=(Relative $entry.FullName); entry_type='directory'; category='cache'; bytes=0; reason="rebuildable cache directory $($entry.Name)"; regenerable_from='Python/pytest/OpenFOAM build tools'})
                }
                continue
            }
            $len = [int64]$entry.Length
            $files++
            $bytes += $len
            $parent = $entry.DirectoryName
            while ($parent) {
                if (-not $dirSizes.ContainsKey($parent)) { $dirSizes[$parent] = [int64]0 }
                $dirSizes[$parent] += $len
                if ($parent.TrimEnd('\') -eq $projectRoot.TrimEnd('\')) { break }
                $parentInfo = [IO.DirectoryInfo]::new($parent).Parent
                if ($null -eq $parentInfo) { break }
                $parent = $parentInfo.FullName
            }
            $ext = [IO.Path]::GetExtension($entry.Name).ToLowerInvariant()
            if ($len -eq 0 -and $ext -in @('.log','.out','.err','.tmp','.temp','.bak','.swp','.swo')) {
                $zeroFiles.Add([pscustomobject]@{absolute_path=$entry.FullName; relative_path=(Relative $entry.FullName); entry_type='file'; category='zero_diagnostic'; bytes=0; reason="zero-byte rebuildable diagnostic file $ext"; regenerable_from='the corresponding run or test'})
            }
            if ($entry.Name -match '(?i)\.(pyc|pyo|o|dep|tmp|temp|bak|swp|swo|dmp|core)$' -and -not (Is-ProtectedTree $entry.FullName)) {
                $zeroFiles.Add([pscustomobject]@{absolute_path=$entry.FullName; relative_path=(Relative $entry.FullName); entry_type='file'; category='rebuildable_artifact'; bytes=$len; reason='rebuildable compiler/cache/temporary artifact'; regenerable_from='source code, compiler or test runner'})
            }
        }
        if ($childCount -eq 0 -and $current.TrimEnd('\') -ne $projectRoot.TrimEnd('\')) {
            $info = [IO.DirectoryInfo]::new($current)
            if (-not (Is-ProtectedTree $current) -and -not (Is-ReservedCaseDirectory $current)) {
                $emptyDirs.Add([pscustomobject]@{absolute_path=$current; relative_path=(Relative $current); entry_type='directory'; category='empty_directory'; bytes=0; reason='empty non-core workspace directory'; regenerable_from='case or output scripts recreate it when needed'})
            }
        }
    }
    foreach ($candidate in $cacheDirs) { $candidate.bytes = [int64]$dirSizes[$candidate.absolute_path] }
    [pscustomobject]@{
        generated_utc=(Get-Date).ToUniversalTime().ToString('o')
        project_root=$projectRoot
        logical_bytes=$bytes
        logical_GB=[math]::Round($bytes/1GB,3)
        file_count=$files
        directory_count=$dirs
        reparse_points=@($reparse)
        zero_files=@($zeroFiles)
        cache_dirs=@($cacheDirs)
        empty_dirs=@($emptyDirs)
    }
}

function Assert-NoRelatedProcess {
    $related = Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -match '^(pimpleFoam|simpleFoam|icoFoam|interFoam|foamRun|decomposePar|reconstructPar|matlab|MATLAB)(\.exe)?$') -or
        ($_.Name -match '^python(\.exe)?$' -and $_.CommandLine -match 'CFD_ANCF_VIV|pimpleFoam|free_viv_driver|coupling') -or
        ($_.Name -match '^wsl(\.exe)?$' -and $_.CommandLine -match 'CFD_ANCF_VIV|pimpleFoam|OpenFOAM|free_viv_driver')
    }
    if ($related) { throw "related compute process is running: $($related | Select-Object -ExpandProperty ProcessId -ErrorAction SilentlyContinue -join ',')" }
}

if (-not (Test-Path -LiteralPath $projectRoot -PathType Container)) { throw "project root missing: $projectRoot" }
Assert-NoRelatedProcess

$pre = Get-Inventory
if (@($pre.reparse_points).Count -gt 0) {
    # Reparse points are recorded and skipped. No candidate may contain one.
}

$protectedZero = @('tests/continuous_handshake/__init__.py')
$candidates = [Collections.Generic.List[object]]::new()
foreach ($row in @($pre.zero_files)) {
    $rel = $row.relative_path.ToLowerInvariant()
    if ($protectedZero -contains $rel) { continue }
    $full = Assert-Inside $row.absolute_path
    if (Is-ProtectedTree $full -and $row.category -ne 'rebuildable_artifact') { continue }
    $candidates.Add($row)
}
foreach ($row in @($pre.cache_dirs)) {
    $full = Assert-Inside $row.absolute_path
    $candidates.Add($row)
}
# Empty directories are removed deepest first. Core source/test/doc trees and
# OpenFOAM base/protocol directory names are protected above.
foreach ($row in @($pre.empty_dirs | Sort-Object { $_.absolute_path.Length } -Descending)) {
    $full = Assert-Inside $row.absolute_path
    $candidates.Add($row)
}

$unique = @{}
$normalized = [Collections.Generic.List[object]]::new()
foreach ($row in $candidates) {
    $key = ([IO.Path]::GetFullPath($row.absolute_path)).ToLowerInvariant()
    if (-not $unique.ContainsKey($key)) { $unique[$key] = $true; $normalized.Add($row) }
}
$candidates = $normalized

$manifestPath = Join-Path $cleanupRoot 'residuals_delete_manifest_v8.csv'
$prePath = Join-Path $cleanupRoot 'residuals_pre_inventory_v8.json'
$postPath = Join-Path $cleanupRoot 'residuals_post_inventory_v8.json'
$validationPath = Join-Path $cleanupRoot 'residuals_validation_v8.json'
$reportPath = Join-Path $docsRoot 'cleanup_residuals_v8.md'
New-Item -ItemType Directory -Force -Path $cleanupRoot | Out-Null

$manifestRows = @($candidates | Select-Object absolute_path,relative_path,entry_type,category,bytes,reason,regenerable_from)
$manifestRows | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding UTF8
$prePayload = [ordered]@{
    schema_version='residual_cleanup_inventory_v8'
    phase='pre_cleanup'
    generated_utc=$pre.generated_utc
    project_root=$projectRoot
    logical_size_bytes=[int64]$pre.logical_bytes
    logical_size_GB=$pre.logical_GB
    file_count=[int64]$pre.file_count
    directory_count=[int64]$pre.directory_count
    reparse_points=@($pre.reparse_points)
    candidate_count=$candidates.Count
    candidate_bytes=[int64](($candidates | Measure-Object -Property bytes -Sum).Sum)
    candidate_categories=@($candidates | Group-Object category | ForEach-Object {[pscustomobject]@{category=$_.Name;count=$_.Count;bytes=[int64](($_.Group | Measure-Object -Property bytes -Sum).Sum)}})
    protected_zero_files=$protectedZero
}
$prePayload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $prePath -Encoding UTF8

$deleted = [Collections.Generic.List[object]]::new()
$failure = $null
foreach ($row in $manifestRows) {
    try {
        $full = Assert-Inside $row.absolute_path
        $item = Get-Item -LiteralPath $full -Force
        $type = if ($item.PSIsContainer) {'directory'} else {'file'}
        if ($type -ne $row.entry_type) { throw "type changed: $full" }
        if ($type -eq 'directory') {
            $nested = [IO.DirectoryInfo]::new($full).EnumerateFileSystemInfos()
            foreach ($child in $nested) {
                if (($child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "reparse point inside target: $full" }
            }
            Remove-Item -LiteralPath $full -Force -Recurse
        } else {
            Remove-Item -LiteralPath $full -Force
        }
        if (Test-Path -LiteralPath $full) { throw "target still exists after delete: $full" }
        $deleted.Add([pscustomobject]@{relative_path=$row.relative_path;entry_type=$row.entry_type;category=$row.category;bytes=[int64]$row.bytes;status='deleted'})
    } catch {
        $failure = [pscustomobject]@{relative_path=$row.relative_path;absolute_path=$row.absolute_path;error=$_.Exception.Message}
        break
    }
}

$post = Get-Inventory
$postPayload = [ordered]@{
    schema_version='residual_cleanup_inventory_v8'
    phase='post_cleanup_before_audit_files'
    generated_utc=$post.generated_utc
    project_root=$projectRoot
    logical_size_bytes=[int64]$post.logical_bytes
    logical_size_GB=$post.logical_GB
    file_count=[int64]$post.file_count
    directory_count=[int64]$post.directory_count
    reparse_points=@($post.reparse_points)
    deleted_count=$deleted.Count
    deleted_bytes=[int64](($deleted | Measure-Object -Property bytes -Sum).Sum)
    deletion_failure=$failure
}
$postPayload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $postPath -Encoding UTF8
$validation = [ordered]@{
    schema_version='residual_cleanup_validation_v8'
    generated_utc=(Get-Date).ToUniversalTime().ToString('o')
    project_root=$projectRoot
    deletion_failed=($null -ne $failure)
    deleted_count=$deleted.Count
    deleted_bytes=[int64](($deleted | Measure-Object -Property bytes -Sum).Sum)
    protected_package_marker_exists=(Test-Path -LiteralPath (Join-Path $projectRoot 'tests/continuous_handshake/__init__.py') -PathType Leaf)
    source_exists=(Test-Path -LiteralPath (Join-Path $projectRoot 'src') -PathType Container)
    tests_exists=(Test-Path -LiteralPath (Join-Path $projectRoot 'tests') -PathType Container)
    docs_exists=(Test-Path -LiteralPath (Join-Path $projectRoot 'docs') -PathType Container)
    stage3_v8_metrics_exists=(Test-Path -LiteralPath (Join-Path $projectRoot 'results/04_continuous_fsi/stage3_final_metrics_v8.json') -PathType Leaf)
    checkpoint_hash_manifest_exists=(Test-Path -LiteralPath (Join-Path $cleanupRoot 'stage3_v8_checkpoint_hash_manifest.json') -PathType Leaf)
    reparse_points_preserved=@($post.reparse_points)
    validation_pass=($null -eq $failure -and (Test-Path -LiteralPath (Join-Path $projectRoot 'src') -PathType Container) -and (Test-Path -LiteralPath (Join-Path $projectRoot 'tests') -PathType Container) -and (Test-Path -LiteralPath (Join-Path $projectRoot 'docs') -PathType Container) -and (Test-Path -LiteralPath (Join-Path $projectRoot 'results/04_continuous_fsi/stage3_final_metrics_v8.json') -PathType Leaf))
}
$validation | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $validationPath -Encoding UTF8
$deleted | Export-Csv -LiteralPath (Join-Path $cleanupRoot 'residuals_deleted_v8.csv') -NoTypeInformation -Encoding UTF8

$report = @"
# Residual workspace cleanup v8

This cleanup used one PowerShell process with ``ErrorActionPreference = Stop`` and exact paths below the project root.

- Project root: ``$projectRoot``
- Before: $($pre.logical_GB) GB logical, $($pre.file_count) files, $($pre.directory_count) directories.
- Deleted: $($deleted.Count) exact targets, $([math]::Round((($deleted | Measure-Object -Property bytes -Sum).Sum)/1GB,6)) GB logical.
- After: $($post.logical_GB) GB logical, $($post.file_count) files, $($post.directory_count) directories (before this audit's own output files).
- Deletion failure: $(if ($null -eq $failure) {'none'} else {$failure.error})

## Deleted categories

$(($deleted | Group-Object category | Sort-Object Count -Descending | ForEach-Object {"- $($_.Name): $($_.Count) targets, $([math]::Round((($_.Group | Measure-Object -Property bytes -Sum).Sum)/1GB,6)) GB"}) -join "`n")

## Protected items

- ``tests/continuous_handshake/__init__.py`` was retained as a Python package marker.
- ``src/``, ``tests/``, ``docs/``, final v8 evidence and checkpoint hash manifest were not deletion candidates.
- Reparse points under ``src/openfoam/ancfFileMotion/lnInclude`` were skipped and preserved.
- No long-time CFD, multi-slice case or physical-model change was performed.

## Machine-readable records

- ``results/cleanup/residuals_pre_inventory_v8.json``
- ``results/cleanup/residuals_delete_manifest_v8.csv``
- ``results/cleanup/residuals_deleted_v8.csv``
- ``results/cleanup/residuals_post_inventory_v8.json``
- ``results/cleanup/residuals_validation_v8.json``
"@
$report | Set-Content -LiteralPath $reportPath -Encoding UTF8

if ($failure) { throw "cleanup stopped at first failure: $($failure.error)" }
Write-Output ($validation | ConvertTo-Json -Depth 10)
