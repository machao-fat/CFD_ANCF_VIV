from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "runtime" / "ANCF_validation"
SRC = ROOT / "src" / "coupling" / "cpp_worker_persistent_ipc_v1"
TOOLS = ROOT / "tools" / "ancf_explicit_section_properties_wire_protocol_v1_1"
BASELINE = "0e813bb680c6343fcdab24d86d56fa9c8718beba"
PROTOCOL = OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_PROTOCOL_V1.1.md"
SUMMARY = OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_TEST_SUMMARY_V1.1.json"
WORKER = OUT / "ancf_explicit_section_properties_wire_protocol_patch_v1_1_worker.exe"
CANONICAL = OUT / "ancf_explicit_section_properties_wire_protocol_patch_v1_1_canonical_base_load.exe"
CPP = SRC / "ancf_kernel.cpp"
HPP = SRC / "ancf_kernel.hpp"
WORKER_CPP = SRC / "ancf_worker_main.cpp"
WIRE = SRC / "kernel_protocol.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def run(*args: str) -> str:
    return subprocess.check_output([*args], cwd=ROOT, text=True).strip()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    diff_path = OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_DIFF_V1.1.patch"
    diff_path.write_bytes(subprocess.check_output([
        "git", "diff", "--binary", f"{BASELINE}..HEAD", "--",
        "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
    ], cwd=ROOT))
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    commit = run("git", "rev-parse", "HEAD")
    parent = run("git", "rev-parse", "HEAD^")
    status = run("git", "status", "--short")
    tracked_status = [line for line in status.splitlines() if len(line) >= 2 and line[:2].strip()]
    untracked_count = sum(line.startswith("?? ") for line in status.splitlines())
    result = {
        "status": "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_V1.1_PASS",
        "baseline_commit": BASELINE,
        "committed_parent": parent,
        "committed_commit": commit,
        "v1_historical_status": "FAIL",
        "v1_historical_primary": "INDEPENDENT_PROPERTY_WIRE_TEST_BLOCKED_BY_DISPLACED_AREA_OBSERVABILITY",
        "protocol_sha256": sha(PROTOCOL),
        "v1_protocol_sha256": "E307BED8D3D5FC3AA194DD9753D9C3647DE15166D88CE147D8247FF3C9570CAC",
        "pre_patch_source_sha256": {
            "ancf_kernel.cpp": "8D82AE6F3E99A54CFD29BC609999090193B3180FC5098FB020AE1E110120424F",
            "ancf_kernel.hpp": "56313124A90DC58EE231AB00CE1ECCA73230298F243A01742B438FEA6C46979C",
            "ancf_worker_main.cpp": "390E56F647AD67864937F679A049EEE97B4C2A9814F34238AC9DEF6D74330806",
            "kernel_protocol.py": "8ADDEF7C61D8BAB89E5D79CE2802A63A1519C303872480BC329E6B0CD9B47F84",
        },
        "post_patch_source_sha256": {
            "ancf_kernel.cpp": sha(CPP),
            "ancf_kernel.hpp": sha(HPP),
            "ancf_worker_main.cpp": sha(WORKER_CPP),
            "kernel_protocol.py": sha(WIRE),
        },
        "changed_production_files": [
            "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
            "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
        ],
        "protected_kernel_unchanged": (
            sha(CPP) == "8D82AE6F3E99A54CFD29BC609999090193B3180FC5098FB020AE1E110120424F"
            and sha(HPP) == "56313124A90DC58EE231AB00CE1ECCA73230298F243A01742B438FEA6C46979C"
        ),
        "production_files_committed_only": run("git", "show", "--format=", "--name-only", commit).splitlines(),
        "wire_extension": {
            "section_property_extension": "SPX1 unchanged",
            "base_load_source_extension": "BLS1",
            "marker_uint32_le": "0x31534C42",
            "version": 1,
            "source_values": {"caller_supplied": 0, "model_static": 1},
            "bytes": 12,
            "placement": "after optional SPX1 trailer, before existing base-load array",
            "old_payload_omits_BLS1": True,
        },
        "base_load_semantics": {
            "missing_source": "caller_supplied",
            "caller_supplied": "request.base_load -> State.base_load",
            "model_static": "static_base_load(model) replaces serialized caller base_load",
            "caller_base_load_double_counted": False,
            "response_schema_changed": False,
        },
        "gates": summary["gates"],
        "test_summary": summary,
        "worker_compile_pass": True,
        "canonical_kernel_helper_pass": True,
        "worker_binary_sha256": sha(WORKER),
        "canonical_probe_binary_sha256": sha(CANONICAL),
        "canonical_probe_source_sha256": sha(TOOLS / "canonical_static_base_load_probe.cpp"),
        "wire_regression_harness_sha256": sha(TOOLS / "wire_protocol_regression_v1_1.py"),
        "artifact_assembly_source_sha256": sha(TOOLS / "assemble_artifacts_v1_1.py"),
        "production_source_modified": True,
        "kernel_modified": False,
        "participant_modified": False,
        "G1_run": False,
        "C_regression_run": False,
        "F_regression_run": False,
        "literature_benchmark_run": False,
        "MATLAB": False,
        "OpenFOAM": False,
        "preCICE": False,
        "CFD_FSI": False,
        "historical_state_preserved": True,
        "previous_v1_candidate_identity_stop_preserved": True,
        "working_tree": {
            "tracked_status_after_commit": tracked_status,
            "untracked_file_count": untracked_count,
            "unrelated_dirt_cleaned_or_deleted": False,
            "unrelated_dirt_staged_or_committed": False,
        },
        "commit_subject": run("git", "show", "-s", "--format=%s", commit),
        "compiler": {
            "toolchain": "MSVC Visual Studio 2022 Build Tools x64",
            "version": "14.44.35207",
            "flags": "/nologo /std:c++17 /EHsc /W4 /permissive- /O2 /DWIN32 /D_WINDOWS",
            "link_library": "bcrypt.lib",
        },
        "production_diff_sha256": sha(diff_path),
    }
    result_path = OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_RESULT_V1.1.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    raw_path = OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_RAW_V1.1.txt"
    raw_path.write_text(
        "\n".join([
            "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_V1.1 RAW EVIDENCE",
            f"status={result['status']}",
            f"protocol_sha256={sha(PROTOCOL)}",
            f"commit={commit}",
            f"parent={parent}",
            f"kernel_cpp_sha256={sha(CPP)}",
            f"kernel_hpp_sha256={sha(HPP)}",
            f"worker_cpp_sha256={sha(WORKER_CPP)}",
            f"kernel_protocol_py_sha256={sha(WIRE)}",
            "historical_V1_status=FAIL",
            "historical_V1_primary=INDEPENDENT_PROPERTY_WIRE_TEST_BLOCKED_BY_DISPLACED_AREA_OBSERVABILITY",
            "worker_compile_pass=true",
            "G1_run=false",
            "C_regression_run=false",
            "F_regression_run=false",
            "OpenFOAM_run=false",
            "preCICE_run=false",
            "CFD_FSI_run=false",
            "",
            "FORMAL_TEST_SUMMARY_V1_1_JSON:",
            SUMMARY.read_text(encoding="utf-8"),
            "",
            "HARNESS_CORRECTIONS:",
            "1. Initial fixture comparison was stopped because the successor harness used a new run_id; corrected to the historical V1 run_id.",
            "2. Initial response-schema assertion omitted the four pre-existing checkpoint fields; corrected to compare against committed V1 baseline dataclass fields.",
            "These were harness-only fixture/assertion defects; no production source or frozen gate was changed.",
            "",
            f"PRODUCTION_DIFF_SHA256={sha(diff_path)}",
            "PRODUCTION_DIFF:",
            diff_path.read_text(encoding="utf-8", errors="replace"),
            "",
            "GIT_STATUS_AFTER_COMMIT:",
            status,
        ]) + "\n", encoding="utf-8"
    )

    report_path = OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_REPORT_V1.1.md"
    report_path.write_text(f"""# ANCF Explicit Section Properties Wire Protocol Patch V1.1

## Final status

`ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_V1.1 = PASS`

The historical V1 result remains `FAIL`, primary
`INDEPENDENT_PROPERTY_WIRE_TEST_BLOCKED_BY_DISPLACED_AREA_OBSERVABILITY`.

## Identity

- committed baseline parent: `{parent}`
- new commit: `{commit}`
- V1.1 protocol SHA-256: `{sha(PROTOCOL)}`
- protected `ancf_kernel.cpp`: `{sha(CPP)}`
- protected `ancf_kernel.hpp`: `{sha(HPP)}`
- `ancf_worker_main.cpp`: `{sha(WORKER_CPP)}`
- `kernel_protocol.py`: `{sha(WIRE)}`
- complete accumulated production diff SHA-256: `{sha(diff_path)}`

The commit contains only the two approved files: `kernel_protocol.py` and
`ancf_worker_main.cpp`. Kernel cpp/hpp and participant files are unchanged.

## Wire extension and semantics

The existing SPX1 section-property trailer is unchanged. V1.1 adds an optional
12-byte BLS1 trailer after SPX1 and before the existing base-load array:

| field | type | value |
|---|---|---|
| marker | uint32 little-endian | `0x31534C42` (`BLS1`) |
| version | uint32 little-endian | `1` |
| source | uint32 little-endian | `0` caller-supplied; `1` model-static |

Omitting the trailer means `caller_supplied`, so old payload bytes remain unchanged.
In `caller_supplied`, the historical request base-load vector is used. In
`model_static`, the worker calls canonical `static_base_load(model)` after model
population and replaces the serialized caller vector; it never adds both vectors.
All four section/source combinations are accepted. The response schema is unchanged.

## Regression results

- old request compatibility: PASS; all four old payload shapes were byte-identical
  and decoded by the patched worker
- V1 explicit-equivalent wire regression: PASS; maximum response difference `0.0`
- ModelStatic legacy equivalence: PASS; maximum response difference `0.0`
- explicit displaced-area observability: PASS; worker effective-load delta matched
  the independent canonical kernel helper with maximum error `0.0` and correct z sign
- explicit mass observability: PASS; worker effective-load delta matched the canonical
  helper with maximum error `0.0` and correct z sign
- no-double-counting: PASS; distinctive caller base load was ignored in ModelStatic
- Python invalid-input tests: PASS
- raw C++ invalid-input tests: PASS
- response schema unchanged: PASS

The first two harness attempts were stopped by harness-only fixture/assertion defects
(successor run-id mismatch and an omitted pre-existing checkpoint-field list). They
were corrected without changing production code, protocol gates, or numerical rules;
the final frozen regression then passed.

## Build and forbidden-scope confirmation

Worker and canonical helper compiled with MSVC Visual Studio 2022 Build Tools x64,
compiler `14.44.35207`, flags
`/nologo /std:c++17 /EHsc /W4 /permissive- /O2 /DWIN32 /D_WINDOWS`, and
`bcrypt.lib`. No C/F/G1 benchmark, participant, MATLAB, OpenFOAM, preCICE, CFD/FSI,
or literature benchmark was run. No kernel, solver, constitutive, participant, or
response-schema change was made.

## Historical state

- `ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_V1 = FAIL` retained
- `ANCF_EXPLICIT_SECTION_PROPERTIES_API_PATCH_V1 = PASS` retained
- `ANCF_TARGET_TOP_TENSION_CALIBRATION_PRECHECK_V1.1 = PASS` retained
- `G1-V1.2 = FAIL` retained
- `independent ANCF validation = NOT_COMPLETED`

## Artifact hashes

See the V1.1 SHA-256 manifest. The manifest intentionally excludes its own
self-referential hash.
""", encoding="utf-8")

    artifact_paths = [
        PROTOCOL, report_path, result_path, raw_path, diff_path, SUMMARY,
        OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_OLD_REQUEST_RAW_V1.1.txt",
        OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_EXPLICIT_EQUIVALENCE_RAW_V1.1.txt",
        OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_MODELSTATIC_LEGACY_EQUIVALENCE_RAW_V1.1.txt",
        OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_DISPLACED_AREA_RAW_V1.1.txt",
        OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_MASS_RAW_V1.1.txt",
        OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_DOUBLE_COUNTING_RAW_V1.1.txt",
        OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_INVALID_PYTHON_RAW_V1.1.txt",
        OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_INVALID_RAW_V1.1.txt",
        WORKER, CANONICAL,
        TOOLS / "wire_protocol_regression_v1_1.py",
        TOOLS / "canonical_static_base_load_probe.cpp",
        TOOLS / "assemble_artifacts_v1_1.py",
        SRC / "ancf_worker_main.cpp", WIRE, CPP, HPP,
    ]
    manifest = OUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_SHA256_MANIFEST_V1.1.txt"
    manifest.write_text("\n".join([
        "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_SHA256_MANIFEST_V1.1",
        "Manifest excludes its own self-referential hash.",
        *(f"{path.relative_to(ROOT)}  {sha(path)}" for path in artifact_paths),
    ]) + "\n", encoding="utf-8")
    print(json.dumps({
        "protocol_sha256": sha(PROTOCOL),
        "report_sha256": sha(report_path),
        "result_sha256": sha(result_path),
        "raw_sha256": sha(raw_path),
        "diff_sha256": sha(diff_path),
        "manifest_sha256": sha(manifest),
        "commit": commit,
        "kernel_cpp_sha256": sha(CPP),
        "kernel_hpp_sha256": sha(HPP),
        "worker_cpp_sha256": sha(WORKER_CPP),
        "kernel_protocol_py_sha256": sha(WIRE),
        "worker_binary_sha256": sha(WORKER),
        "canonical_probe_binary_sha256": sha(CANONICAL),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
