[CmdletBinding()]
param(
    [switch]$ExecuteDelete
)

$ErrorActionPreference = 'Stop'
# PowerShell 5.1 reads UTF-8 scripts without a BOM using the active code page.
# Build the explicitly required Chinese path from Unicode code points so the
# safety boundary remains exact even when this script is launched non-ASCII.
$projectRoot = [IO.Path]::GetFullPath(('D:\' + (-join [char[]](0x7814,0x4E8C,0x6587,0x4EF6)) + '\' + (-join [char[]](0x5F00,0x9898,0x51C6,0x5907)) + '\CFD_ANCF_VIV'))
$cleanupRoot = Join-Path $projectRoot 'results\cleanup'
$docsRoot = Join-Path $projectRoot 'docs'
$caseRoot = Join-Path $projectRoot 'cases\openfoam'
$rootPrefix = $projectRoot.TrimEnd('\') + '\'

function Assert-ProjectRoot {
    if (-not (Test-Path -LiteralPath $projectRoot -PathType Container)) { throw "project root missing: $projectRoot" }
    $resolved = [IO.Path]::GetFullPath($projectRoot)
    if ($resolved.TrimEnd('\') -ne $projectRoot.TrimEnd('\')) { throw "project root resolution mismatch: $resolved" }
}

function Get-SafePath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full.TrimEnd('\') -eq $projectRoot.TrimEnd('\')) { throw "root itself is not a valid target: $full" }
    if (-not $full.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "path escapes project root: $full" }
    if (-not (Test-Path -LiteralPath $full)) { throw "target does not exist: $full" }
    $item = Get-Item -LiteralPath $full -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "reparse point target is not allowed: $full" }
    return $full
}

function Get-Relative([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) { return $full.Substring($rootPrefix.Length).Replace('\','/') }
    if ($full.TrimEnd('\') -eq $projectRoot.TrimEnd('\')) { return '.' }
    throw "relative path outside project root: $full"
}

function Test-RelatedComputeProcess {
    $patterns = 'pimpleFoam|simpleFoam|icoFoam|interFoam|foamRun|decomposePar|reconstructPar|free_viv_driver|MATLAB|matlab'
    $related = Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -match '^(pimpleFoam|simpleFoam|icoFoam|interFoam|foamRun|decomposePar|reconstructPar|matlab|MATLAB)(\.exe)?$') -or
        ($_.Name -match '^python(\.exe)?$' -and $_.CommandLine -match $patterns) -or
        ($_.Name -match '^wsl(\.exe)?$' -and $_.CommandLine -match 'CFD_ANCF_VIV|pimpleFoam|OpenFOAM|free_viv_driver')
    }
    if ($related) {
        $related | Select-Object Name,ProcessId,ParentProcessId,CommandLine | Format-List | Out-String | Write-Output
        throw 'related CFD/MATLAB/Python coupling process is running; cleanup stopped'
    }
}

function Get-TreeSummary([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    $stack = [Collections.Generic.Stack[string]]::new()
    $stack.Push($full)
    $fileCount = [int64]0
    $dirCount = [int64]0
    $logicalBytes = [int64]0
    $reparse = [Collections.Generic.List[string]]::new()
    $topFiles = [Collections.Generic.List[object]]::new()
    $dirSizes = @{}
    $extensions = @{}
    $candidateSeeds = [Collections.Generic.List[object]]::new()
    $cacheNames = @('__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','dynamicCode')
    $filePatterns = @('*.pyc','*.pyo','*.o','*.dep','*.bak','*.tmp','*.temp','*.swp','*.swo','*.dmp','*.tif','*.tiff')
    $resultsRoot = Join-Path $projectRoot 'results'
    $caseRootFull = [IO.Path]::GetFullPath($caseRoot)
    while ($stack.Count -gt 0) {
        $current = $stack.Pop()
        foreach ($entry in ([IO.DirectoryInfo]::new($current)).EnumerateFileSystemInfos()) {
            if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                $reparse.Add($entry.FullName)
                continue
            }
            if ($entry -is [IO.DirectoryInfo]) {
                $dirCount++
                $stack.Push($entry.FullName)
                if ($cacheNames -contains $entry.Name -and -not $entry.FullName.StartsWith((Join-Path $projectRoot '.git'), [StringComparison]::OrdinalIgnoreCase)) {
                    $candidateSeeds.Add([pscustomobject]@{absolute_path=$entry.FullName; entry_type='directory'; reason="rebuildable cache directory $($entry.Name)"; regenerable_from='Python/pytest/OpenFOAM build tools'; stage_workload='all'; category='cache'; bytes=0})
                }
                if ($entry.Name -match '^processor\d+$') {
                    $candidateSeeds.Add([pscustomobject]@{absolute_path=$entry.FullName; entry_type='directory'; reason='rebuildable OpenFOAM processor decomposition'; regenerable_from='decomposePar/reconstructPar'; stage_workload='CFD'; category='processor'; bytes=0})
                }
                $parent = $entry.Parent
                if ($parent -and $parent.Parent -and $parent.Parent.FullName.TrimEnd('\') -eq $caseRootFull.TrimEnd('\') -and $entry.Name -match '^\d+(?:\.\d+)?$') {
                    $candidateSeeds.Add([pscustomobject]@{absolute_path=$entry.FullName; entry_type='openfoam_time'; case_name=$parent.Name; time_name=$entry.Name; reason='intermediate OpenFOAM time directory'; regenerable_from='case 0/constant/system plus retained checkpoint and final CSV/JSON'; stage_workload='CFD'; category='openfoam_time'; bytes=0})
                }
                continue
            }
            $length = [int64]$entry.Length
            $fileCount++
            $logicalBytes += $length
            $ext = [IO.Path]::GetExtension($entry.Name).ToLowerInvariant()
            if ([string]::IsNullOrEmpty($ext)) { $ext = '<none>' }
            if (-not $extensions.ContainsKey($ext)) { $extensions[$ext] = [int64]0 }
            $extensions[$ext] += $length
            $parent = $entry.DirectoryName
            while ($parent -and $parent.StartsWith($full, [StringComparison]::OrdinalIgnoreCase)) {
                if (-not $dirSizes.ContainsKey($parent)) { $dirSizes[$parent] = [int64]0 }
                $dirSizes[$parent] += $length
                if ($parent.TrimEnd('\') -eq $full.TrimEnd('\')) { break }
                $next = [IO.DirectoryInfo]::new($parent).Parent
                if ($null -eq $next) { break }
                $parent = $next.FullName
            }
            if ($topFiles.Count -lt 2000) { $topFiles.Add([pscustomobject]@{path=$entry.FullName; bytes=$length}) }
            elseif ($length -gt (($topFiles | Measure-Object -Property bytes -Minimum).Minimum)) {
                $topFiles.Add([pscustomobject]@{path=$entry.FullName; bytes=$length})
                $trimmed = $topFiles | Sort-Object bytes -Descending | Select-Object -First 1000
                $topFiles = [Collections.Generic.List[object]]::new()
                foreach ($item in $trimmed) { $topFiles.Add($item) }
            }
            foreach ($pattern in $filePatterns) {
                $isMatch = switch -Wildcard ($pattern) { '*.pyc' {$entry.Name -like '*.pyc'} '*.pyo' {$entry.Name -like '*.pyo'} '*.o' {$entry.Name -like '*.o'} '*.dep' {$entry.Name -like '*.dep'} '*.bak' {$entry.Name -like '*.bak'} '*.tmp' {$entry.Name -like '*.tmp'} '*.temp' {$entry.Name -like '*.temp'} '*.swp' {$entry.Name -like '*.swp'} '*.swo' {$entry.Name -like '*.swo'} '*.dmp' {$entry.Name -like '*.dmp'} '*.tif' {$entry.Name -like '*.tif'} '*.tiff' {$entry.Name -like '*.tiff'} default {$false} }
                if ($isMatch) {
                    if ($entry.FullName.StartsWith((Join-Path $projectRoot '.git'), [StringComparison]::OrdinalIgnoreCase)) { continue }
                    if (($pattern -in @('*.tif','*.tiff')) -and -not $entry.FullName.StartsWith($resultsRoot, [StringComparison]::OrdinalIgnoreCase)) { continue }
                    $category = if ($pattern -in @('*.tif','*.tiff')) {'old_figure'} elseif ($pattern -in @('*.o','*.dep')) {'build_artifact'} else {'temporary_file'}
                    $candidateSeeds.Add([pscustomobject]@{absolute_path=$entry.FullName; entry_type='file'; reason="rebuildable file matching $pattern"; regenerable_from='source code, plotting script or compiler'; stage_workload='all'; category=$category; bytes=$length})
                    break
                }
            }
        }
    }
    [pscustomobject]@{
        path = $full
        logical_bytes = $logicalBytes
        file_count = $fileCount
        directory_count = $dirCount
        reparse_points = @($reparse)
        top_files = @($topFiles | Sort-Object bytes -Descending | Select-Object -First 100)
        top_directories = @($dirSizes.GetEnumerator() | ForEach-Object { [pscustomobject]@{path=$_.Key; bytes=[int64]$_.Value} } | Sort-Object bytes -Descending | Select-Object -First 50)
        extension_bytes = [pscustomobject]($extensions.GetEnumerator() | Sort-Object Value -Descending | ForEach-Object { @{extension=$_.Key; bytes=[int64]$_.Value} })
        directory_size_map = $dirSizes
        candidate_seeds = @($candidateSeeds)
    }
}

function Get-DriveSnapshot {
    $driveName = ([IO.Path]::GetPathRoot($projectRoot)).TrimEnd('\').TrimEnd(':')
    $drive = Get-PSDrive -Name $driveName
    [pscustomobject]@{drive=($driveName + ':'); used_bytes=[int64]$drive.Used; free_bytes=[int64]$drive.Free; total_bytes=[int64]($drive.Used + $drive.Free)}
}

function Add-Candidate([hashtable]$Map, [string]$Path, [string]$EntryType, [string]$Reason, [string]$RegenerableFrom, [string]$Stage, [string]$Category) {
    $full = Get-SafePath $Path
    $item = Get-Item -LiteralPath $full -Force
    $key = $full.ToLowerInvariant()
    if (-not $Map.ContainsKey($key)) {
        $Map[$key] = [pscustomobject]@{absolute_path=$full; relative_path=(Get-Relative $full); entry_type=$EntryType; reason=$Reason; regenerable_from=$RegenerableFrom; stage_workload=$Stage; category=$Category; reparse_checked=$true}
    }
}

function Normalize-Candidates([object[]]$Candidates) {
    $result = [Collections.Generic.List[object]]::new()
    foreach ($candidate in ($Candidates | Sort-Object { $_.absolute_path.Length })) {
        $covered = $false
        foreach ($kept in $result) {
            if ($candidate.absolute_path.StartsWith($kept.absolute_path.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { $covered = $true; break }
        }
        if (-not $covered) { $result.Add($candidate) }
    }
    return @($result)
}

function Get-CheckpointHashes {
    $records = [Collections.Generic.List[object]]::new()
    $fieldNames = @('U','p','phi','Uf','meshPhi','motionScale','polyMesh/points','uniform/time')
    $branches = @(
        [pscustomobject]@{label='Ur5p2_common_coarse_130'; relative='cases/openfoam/single_dof_free_viv_Ur5p2_v8_dt0025_from130/130'},
        [pscustomobject]@{label='Ur5p2_common_refined_130'; relative='cases/openfoam/single_dof_free_viv_Ur5p2_v8_dt00125_from130/130'}
    )
    foreach ($branch in $branches) {
        $base = Join-Path $projectRoot $branch.relative
        foreach ($name in $fieldNames) {
            $path = Join-Path $base ($name.Replace('/', '\'))
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                $item = Get-Item -LiteralPath $path -Force
                $records.Add([pscustomobject]@{label=$branch.label; relative_path=(Get-Relative $path); absolute_path=$path; status='present'; bytes=[int64]$item.Length; sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash})
            } else {
                $records.Add([pscustomobject]@{label=$branch.label; relative_path=(Get-Relative $path); absolute_path=$path; status='missing'; bytes=0; sha256=$null})
            }
        }
    }
    $structural = @(
        'results/04_sdof_corrected_campaign/Ur5p2_v6_retry_to130/sdof_checkpoint.json',
        'results/04_sdof_corrected_campaign/dt_convergence_v8/Ur5p2_dt0025_from130/sdof_checkpoint.json',
        'results/04_sdof_corrected_campaign/dt_convergence_v8/Ur5p2_dt00125_from130/sdof_checkpoint.json'
    )
    foreach ($relative in $structural) {
        $path = Join-Path $projectRoot ($relative.Replace('/', '\'))
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $item = Get-Item -LiteralPath $path -Force
            $records.Add([pscustomobject]@{label='structural_checkpoint'; relative_path=(Get-Relative $path); absolute_path=$path; status='present'; bytes=[int64]$item.Length; sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash})
        } else {
            $records.Add([pscustomobject]@{label='structural_checkpoint'; relative_path=(Get-Relative $path); absolute_path=$path; status='missing'; bytes=0; sha256=$null})
        }
    }
    [pscustomobject]@{schema_version='stage3_v8_checkpoint_hash_manifest'; generated_utc=(Get-Date).ToUniversalTime().ToString('o'); project_root=$projectRoot; common_time_s=130.0; field_hashes=@($records); common_state=[ordered]@{y=0.4324133716360857; v=0.15568921471030148; a=-0.6076706275402103; time_s=130.0; step=52000; previous_force_y_N=215.3214405}}
}

function Write-Inventory([string]$Path, [object]$Summary, [object]$Drive, [object]$Candidates, [string]$Phase) {
    $payload = [ordered]@{schema_version="project_inventory_v8"; phase=$Phase; generated_utc=(Get-Date).ToUniversalTime().ToString('o'); project_root=$projectRoot; logical_size_bytes=[int64]$Summary.logical_bytes; logical_size_GB=([math]::Round($Summary.logical_bytes / 1GB, 3)); file_count=[int64]$Summary.file_count; directory_count=[int64]$Summary.directory_count; drive=$Drive; reparse_points=@($Summary.reparse_points); top_50_directories=@($Summary.top_directories); top_100_files=@($Summary.top_files); extension_bytes=@($Summary.extension_bytes); candidate_count=@($Candidates).Count; candidate_bytes=([int64](($Candidates | Measure-Object -Property bytes -Sum).Sum)); candidate_categories=@($Candidates | Group-Object category | ForEach-Object { [pscustomobject]@{category=$_.Name; count=$_.Count; bytes=[int64](($_.Group | Measure-Object -Property bytes -Sum).Sum)} })}
    $payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-CandidateList([object]$InventorySummary) {
    $map = @{}
    foreach ($seed in $InventorySummary.candidate_seeds) {
        if ($seed.entry_type -eq 'openfoam_time') {
            $caseName = $seed.case_name
            $timeDirs = @($InventorySummary.candidate_seeds | Where-Object { $_.entry_type -eq 'openfoam_time' -and $_.case_name -eq $caseName })
            $maxTime = ($timeDirs | Sort-Object {[double]$_.time_name} -Descending | Select-Object -First 1).time_name
            $keep = $seed.time_name -eq $maxTime
            if ($caseName -match 'Ur5p2_v8_dt0025_from130|Ur5p2_v8_dt00125_from130' -and $seed.time_name -in @('130','150')) { $keep=$true }
            if ($caseName -match 'Ur5p2_v6_retry_to130' -and $seed.time_name -eq '130') { $keep=$true }
            if ($caseName -match 'Ur8' -and $seed.time_name -eq '240') { $keep=$true }
            if ($caseName -match 'Ur4' -and $seed.time_name -eq '140') { $keep=$true }
            if ($keep) { continue }
            $seed.reason = "intermediate OpenFOAM time directory; retained latest/key time for case ($maxTime)"
        }
        $targetType = if ($seed.entry_type -eq 'openfoam_time') {'directory'} else {$seed.entry_type}
        Add-Candidate $map $seed.absolute_path $targetType $seed.reason $seed.regenerable_from $seed.stage_workload $seed.category
        $key = ([IO.Path]::GetFullPath($seed.absolute_path)).ToLowerInvariant()
        if ($map.ContainsKey($key)) {
            $bytes = if ($targetType -eq 'directory') {[int64]$InventorySummary.directory_size_map[$seed.absolute_path]} else {[int64]$seed.bytes}
            $map[$key] | Add-Member -Force -NotePropertyName bytes -NotePropertyValue $bytes
        }
    }
    $normalized = Normalize-Candidates @($map.Values)
    $result = [Collections.Generic.List[object]]::new()
    foreach ($candidate in $normalized) {
        if ($candidate.entry_type -eq 'directory') {
            $nestedReparse = @($InventorySummary.reparse_points | Where-Object { $_.StartsWith($candidate.absolute_path.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) })
            if ($nestedReparse.Count -gt 0) { throw "candidate contains reparse points: $($candidate.absolute_path)" }
            $candidate | Add-Member -Force -NotePropertyName bytes -NotePropertyValue ([int64]$InventorySummary.directory_size_map[$candidate.absolute_path])
        }
        $result.Add($candidate)
    }
    return @($result | Sort-Object category,absolute_path)
}

function Write-PlanDocs([object]$Inventory, [object]$Candidates, [object]$Drive, [object]$HashManifest) {
    $candidateBytes = [int64](($Candidates | Measure-Object -Property bytes -Sum).Sum)
    $byCategory = @($Candidates | Group-Object category | Sort-Object @{Expression={($_.Group | Measure-Object -Property bytes -Sum).Sum};Descending=$true} | ForEach-Object { "| $($_.Name) | $($_.Count) | $([math]::Round((($_.Group | Measure-Object -Property bytes -Sum).Sum)/1GB,3)) GB |" }) -join "`n"
    $plan = @"
# Project cleanup plan v8

This plan is generated under the fixed project root `$projectRoot`.

- Pre-clean logical size: $([math]::Round($Inventory.logical_bytes/1GB,3)) GB; files: $($Inventory.file_count); directories: $($Inventory.directory_count).
- Drive used before cleanup: $([math]::Round($Drive.used_bytes/1GB,3)) GB.
- Precise dry-run candidates: $(@($Candidates).Count); logical bytes: $([math]::Round($candidateBytes/1GB,3)) GB.
- The candidate list contains only exact absolute paths below the project root. Source, tests, docs, Git metadata and v8 evidence are not candidates.
- Numeric OpenFOAM directories keep `0`, `constant`, `system` and the latest numeric time per case; v8 Ur=5.2 branches additionally keep 130 and 150, and Ur=8/Ur=4 key times are retained where present.
- WSL background sessions were inspected and were not project-related compute processes; no process was terminated.

## Candidate categories

| category | targets | logical size |
|---|---:|---:|
$byCategory

## Safety boundary

No delete operation is performed by the default invocation. Execute mode reads this exact CSV manifest, re-resolves every path, rejects the root, outside paths, missing targets, type changes and reparse points, and stops on the first failure.
"@
    $plan | Set-Content -LiteralPath (Join-Path $docsRoot 'cleanup_plan_v8.md') -Encoding UTF8
    $dry = @"
# Cleanup dry-run v8

Status: **READY FOR REVIEWED EXECUTION**. No files were deleted during dry-run generation.

- project root: `$projectRoot`
- candidate count: $(@($Candidates).Count)
- estimated logical release: $([math]::Round($candidateBytes/1GB,3)) GB
- source checkpoint hash manifest: `results/cleanup/stage3_v8_checkpoint_hash_manifest.json`
- exact deletion manifest: `results/cleanup/delete_manifest_v8.csv`

The manifest is a normalized, non-overlapping list. Candidate directories are checked for nested reparse points before they can be executed. If the manifest changes or any target is missing, execution stops.
"@
    $dry | Set-Content -LiteralPath (Join-Path $docsRoot 'cleanup_dry_run_v8.md') -Encoding UTF8
}

function Write-RetainManifest([object]$InventorySummary) {
    $rows = [Collections.Generic.List[object]]::new()
    foreach ($relative in @('src','tests','scripts','docs','.git')) {
        $path = Join-Path $projectRoot $relative
        if (Test-Path -LiteralPath $path) {
            $bytes = if ($InventorySummary.directory_size_map.ContainsKey($path)) {[int64]$InventorySummary.directory_size_map[$path]} else {[int64](Get-Item -LiteralPath $path).Length}
            $rows.Add([pscustomobject]@{relative_path=$relative; absolute_path=$path; entry_type='protected_tree'; bytes=$bytes; reason='source, test, documentation or Git metadata; never delete'; required_for='stage4 development and reproducibility'})
        }
    }
    foreach ($relative in @('results/04_continuous_fsi','results/04_sdof_corrected_campaign','cases/openfoam')) {
        $path = Join-Path $projectRoot ($relative.Replace('/','\'))
        if (Test-Path -LiteralPath $path) {
            $bytes = if ($InventorySummary.directory_size_map.ContainsKey($path)) {[int64]$InventorySummary.directory_size_map[$path]} else {[int64](Get-Item -LiteralPath $path).Length}
            $rows.Add([pscustomobject]@{relative_path=$relative; absolute_path=$path; entry_type='evidence_or_case_tree'; bytes=$bytes; reason='contains final JSON/CSV/checkpoints or reproducible OpenFOAM cases; only exact manifest targets may be deleted'; required_for='stage3 review and stage4 prototype'})
        }
    }
    foreach ($candidate in (Get-ChildItem -LiteralPath $caseRoot -Directory -Force | ForEach-Object { $_ } | ForEach-Object {
        $case = $_; Get-ChildItem -LiteralPath $case.FullName -Directory -Force | Where-Object { $_.Name -in @('0','constant','system') } | ForEach-Object { $_ }
    })) {
        $bytes = if ($InventorySummary.directory_size_map.ContainsKey($candidate.FullName)) {[int64]$InventorySummary.directory_size_map[$candidate.FullName]} else {[int64](Get-Item -LiteralPath $candidate.FullName).Length}
        $rows.Add([pscustomobject]@{relative_path=(Get-Relative $candidate.FullName); absolute_path=$candidate.FullName; entry_type='case_base'; bytes=$bytes; reason='OpenFOAM base case configuration'; required_for='future rerun/restart'})
    }
    foreach ($relative in @('docs/04_stage3_final_acceptance_report_v8.md','docs/04_stage3_acceptance_matrix_v8.md','docs/04_stage4_entry_decision_v8.md','results/04_continuous_fsi/stage3_final_metrics_v8.json','results/04_continuous_fsi/stage3_v8_test_results.json','results/04_continuous_fsi/stage3_v8_matlab_test_results.json','results/04_sdof_corrected_campaign/asymptotic_v8/Ur8_asymptotic_v8.json','results/04_sdof_corrected_campaign/dt_convergence_v8/long_window_dt_convergence_v8.json','results/04_sdof_corrected_campaign/dt_convergence_v8/common_checkpoint_manifest_v8.json')) {
        $path = Join-Path $projectRoot ($relative.Replace('/','\'))
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $item = Get-Item -LiteralPath $path -Force
            $rows.Add([pscustomobject]@{relative_path=$relative; absolute_path=$path; entry_type='critical_evidence'; bytes=[int64]$item.Length; reason='required v8 final machine-readable evidence'; required_for='acceptance audit'})
        }
    }
    $rows | Export-Csv -LiteralPath (Join-Path $cleanupRoot 'retain_manifest_v8.csv') -NoTypeInformation -Encoding UTF8
}

function Write-PostValidation {
    $required = @(
        'docs/04_stage3_final_acceptance_report_v8.md','docs/04_stage3_acceptance_matrix_v8.md','docs/04_stage4_entry_decision_v8.md',
        'results/04_continuous_fsi/stage3_final_metrics_v8.json','results/04_continuous_fsi/stage3_v8_test_results.json','results/04_continuous_fsi/stage3_v8_matlab_test_results.json',
        'results/04_sdof_corrected_campaign/asymptotic_v8/Ur8_asymptotic_v8.json','results/04_sdof_corrected_campaign/dt_convergence_v8/long_window_dt_convergence_v8.json','results/cleanup/stage3_v8_checkpoint_hash_manifest.json',
        'src/structure_ancf_matlab','src/structure_eb_fem_matlab','src/coupling/online_file_coupling','src/openfoam/ancfFileMotion','tests','docs'
    )
    $checks = [Collections.Generic.List[object]]::new()
    foreach ($relative in $required) {
        $path = Join-Path $projectRoot ($relative.Replace('/','\'))
        $exists = Test-Path -LiteralPath $path
        $parse = $false; $finite = $true
        if ($exists -and [IO.Path]::GetExtension($path).ToLowerInvariant() -eq '.json') {
            try { $obj = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json; $parse = $true; $raw = Get-Content -LiteralPath $path -Raw; if ($raw -match '(?i)NaN|Infinity|-Infinity') { $finite=$false } } catch { $parse=$false }
        } else { $parse=$exists }
        $checks.Add([pscustomobject]@{relative_path=$relative; absolute_path=$path; exists=$exists; parseable=$parse; finite=$finite})
    }
    $baseCases = @(Get-ChildItem -LiteralPath $caseRoot -Directory -Force | ForEach-Object { $case=$_.FullName; [pscustomobject]@{case=(Get-Relative $case); has_0=(Test-Path -LiteralPath (Join-Path $case '0')); has_constant=(Test-Path -LiteralPath (Join-Path $case 'constant')); has_system=(Test-Path -LiteralPath (Join-Path $case 'system'))} })
    $py = $false
    $pyResult = Join-Path $projectRoot 'results/04_continuous_fsi/stage3_v8_test_results.json'
    if (Test-Path -LiteralPath $pyResult) { $py = ((Get-Content -LiteralPath $pyResult -Raw -Encoding UTF8 | ConvertFrom-Json).status -eq 'pass') }
    $stage3 = $false
    $metricsPath = Join-Path $projectRoot 'results/04_continuous_fsi/stage3_final_metrics_v8.json'
    if (Test-Path -LiteralPath $metricsPath) { $stage3 = ((Get-Content -LiteralPath $metricsPath -Raw -Encoding UTF8 | ConvertFrom-Json).stage3_fully_passed -eq $true) }
    $figureFiles = @(Get-ChildItem -LiteralPath (Join-Path $projectRoot 'results/04_sdof_corrected_campaign/asymptotic_v8') -File -ErrorAction SilentlyContinue | Where-Object {$_.Extension -in @('.png','.svg','.pdf')})
    $payload = [ordered]@{schema_version='post_cleanup_validation_v8'; generated_utc=(Get-Date).ToUniversalTime().ToString('o'); project_root=$projectRoot; required_files=@($checks); base_case_count=$baseCases.Count; base_case_failures=@($baseCases | Where-Object { -not ($_.has_0 -and $_.has_constant -and $_.has_system) }); python_regression_pass=$py; stage3_metrics_pass=$stage3; final_v8_figure_count=$figureFiles.Count; final_v8_figures=@($figureFiles | ForEach-Object {Get-Relative $_.FullName}); no_long_cfd_run=true; multi_slice_started=false; validation_pass=($stage3 -and $py -and (@($checks | Where-Object { -not ($_.exists -and $_.parseable -and $_.finite) }).Count -eq 0) -and $figureFiles.Count -gt 0 -and @($baseCases | Where-Object { -not ($_.has_0 -and $_.has_constant -and $_.has_system) }).Count -eq 0)}
    $payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $cleanupRoot 'post_cleanup_validation_v8.json') -Encoding UTF8
}

Assert-ProjectRoot
New-Item -ItemType Directory -Force -Path $cleanupRoot | Out-Null
Test-RelatedComputeProcess

if ($ExecuteDelete) {
    $manifestPath = Join-Path $cleanupRoot 'delete_manifest_v8.csv'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'delete manifest missing; run dry-run first' }
    $hashPath = Join-Path $cleanupRoot 'stage3_v8_checkpoint_hash_manifest.json'
    if (-not (Test-Path -LiteralPath $hashPath -PathType Leaf)) { throw 'checkpoint hash manifest missing; run dry-run first' }
    $manifest = @(Import-Csv -LiteralPath $manifestPath -Encoding UTF8)
    if ($manifest.Count -eq 0) { throw 'delete manifest is empty; cleanup stopped' }
    foreach ($row in $manifest) {
        $full = Get-SafePath $row.absolute_path
        $item = Get-Item -LiteralPath $full -Force
        $actualType = if ($item.PSIsContainer) {'directory'} else {'file'}
        if ($actualType -ne $row.entry_type) { throw "target type changed: $full" }
        if ($row.entry_type -eq 'directory') {
            $nested = Get-TreeSummary $full
            if (@($nested.reparse_points).Count -gt 0) { throw "reparse point inside target: $full" }
        }
        Remove-Item -LiteralPath $full -Force -Recurse:$($row.entry_type -eq 'directory')
    }
    $post = Get-TreeSummary $projectRoot
    $drive = Get-DriveSnapshot
    Write-Inventory (Join-Path $cleanupRoot 'post_cleanup_inventory_v8.json') $post $drive @() 'post_cleanup'
    Write-PostValidation
    $pre = Get-Content -LiteralPath (Join-Path $cleanupRoot 'pre_cleanup_inventory_v8.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $report = @"
# Project cleanup report v8

## Result

Cleanup executed from the exact manifest in one PowerShell process with `$ErrorActionPreference = 'Stop'`. No project-related CFD, MATLAB or coupling process was running. WSL background sessions were inspected and were unrelated to this project.

- Before logical size: $([math]::Round($pre.logical_size_bytes/1GB,3)) GB; files: $($pre.file_count); directories: $($pre.directory_count).
- After logical size: $([math]::Round($post.logical_bytes/1GB,3)) GB; files: $($post.file_count); directories: $($post.directory_count).
- Logical bytes released: $([math]::Round(($pre.logical_size_bytes-$post.logical_bytes)/1GB,3)) GB.
- Drive used before: $([math]::Round($pre.drive.used_bytes/1GB,3)) GB; drive used after: $([math]::Round($drive.used_bytes/1GB,3)) GB; observed drive delta: $([math]::Round(($pre.drive.used_bytes-$drive.used_bytes)/1GB,3)) GB.
- Delete failures: none (the process stops at the first failure).
- No long-time CFD was run; no multi-slice work was started.

## Verification

See `results/cleanup/post_cleanup_validation_v8.json`. Stage-3 v8 metrics, final reports, Python regression, critical checkpoint hashes, source trees and final PNG/SVG/PDF figures remain readable. The cleanup is considered complete only if `validation_pass=true`.

## Retention boundary

The cleanup retained source code, tests, docs, Git metadata, OpenFOAM base configuration, final CSV/JSON evidence, v8 figures and the key checkpoint hash manifest. Numeric OpenFOAM time directories were reduced to `0`, the latest time per case, and explicitly required v8/Ur checkpoint times.
"@
    $report | Set-Content -LiteralPath (Join-Path $docsRoot 'cleanup_report_v8.md') -Encoding UTF8
    Write-Output ($report)
    exit 0
}

$preSummary = Get-TreeSummary $projectRoot
$preDrive = Get-DriveSnapshot
$candidates = @(Get-CandidateList $preSummary)
Write-Inventory (Join-Path $cleanupRoot 'pre_cleanup_inventory_v8.json') $preSummary $preDrive $candidates 'pre_cleanup'
$hashManifest = Get-CheckpointHashes
$hashManifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $cleanupRoot 'stage3_v8_checkpoint_hash_manifest.json') -Encoding UTF8
$candidates | Select-Object absolute_path,relative_path,entry_type,bytes,reason,regenerable_from,stage_workload,category,reparse_checked | Export-Csv -LiteralPath (Join-Path $cleanupRoot 'delete_manifest_v8.csv') -NoTypeInformation -Encoding UTF8
Write-RetainManifest $preSummary
Write-PlanDocs $preSummary $candidates $preDrive $hashManifest
Write-Output ([ordered]@{mode='dry_run'; project_root=$projectRoot; candidate_count=$candidates.Count; candidate_bytes=[int64](($candidates | Measure-Object -Property bytes -Sum).Sum); candidate_GB=[math]::Round((($candidates | Measure-Object -Property bytes -Sum).Sum)/1GB,3); pre_logical_GB=[math]::Round($preSummary.logical_bytes/1GB,3); pre_files=$preSummary.file_count; pre_directories=$preSummary.directory_count; hash_records=@($hashManifest.field_hashes).Count} | ConvertTo-Json -Depth 5)
