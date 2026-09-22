from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "runtime" / "ANCF_validation"
SRC = ROOT / "src" / "coupling" / "cpp_worker_persistent_ipc_v1"
HARNESS = ROOT / "tools" / "ancf_explicit_section_properties_wire_protocol_v1" / "wire_protocol_regression.py"
PROTOCOL = OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_PROTOCOL_V1.md"
SUMMARY = OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_TEST_SUMMARY_V1.json"
WORKER = OUTPUT / "ancf_explicit_section_properties_wire_protocol_patch_v1_worker.exe"
REPORT = OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_REPORT_V1.md"
RESULT = OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_RESULT_V1.json"
RAW = OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_RAW_V1.txt"
DIFF = OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_DIFF_V1.patch"
MANIFEST = OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_SHA256_MANIFEST_V1.txt"

CPP = SRC / "ancf_kernel.cpp"
HPP = SRC / "ancf_kernel.hpp"
WORKER_CPP = SRC / "ancf_worker_main.cpp"
WIRE_PY = SRC / "kernel_protocol.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def git_status() -> list[str]:
    return subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).splitlines()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    diff_bytes = subprocess.check_output(
        ["git", "diff", "--binary", "--", str(WIRE_PY.relative_to(ROOT)), str(WORKER_CPP.relative_to(ROOT))],
        cwd=ROOT,
    )
    DIFF.write_bytes(diff_bytes)

    status_lines = git_status()
    source_scope_pass = (
        sha256(CPP) == "8D82AE6F3E99A54CFD29BC609999090193B3180FC5098FB020AE1E110120424F"
        and sha256(HPP) == "56313124A90DC58EE231AB00CE1ECCA73230298F243A01742B438FEA6C46979C"
        and all(
            not line.startswith(" M ") or
            line.startswith(" M src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp")
            or line.startswith(" M src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py")
            for line in status_lines
        )
    )
    gates = summary["gates"]
    result = {
        "status": "WIRE_PROTOCOL_PATCH_REGRESSION_FAIL_INDEPENDENT_DISPLACED_AREA_OBSERVABILITY",
        "baseline_commit": "0e813bb680c6343fcdab24d86d56fa9c8718beba",
        "pre_patch_commit": "0e813bb680c6343fcdab24d86d56fa9c8718beba",
        "post_patch_commit": None,
        "post_patch_parent": None,
        "protocol_sha256": sha256(PROTOCOL),
        "production_files": [
            "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
            "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
        ],
        "pre_patch_source_sha256": {
            "ancf_kernel.cpp": "8D82AE6F3E99A54CFD29BC609999090193B3180FC5098FB020AE1E110120424F",
            "ancf_kernel.hpp": "56313124A90DC58EE231AB00CE1ECCA73230298F243A01742B438FEA6C46979C",
            "ancf_worker_main.cpp": "A5FD188FE3C384CA37C7A760686E8BF172E5A4E728A2B1B446D842AD83D32151",
            "kernel_protocol.py": "AE62D7ABEBA38FF307EF85F636379F9689FCE133E43CBFFB61604D2D377440FF",
        },
        "current_source_sha256": {
            "ancf_kernel.cpp": sha256(CPP),
            "ancf_kernel.hpp": sha256(HPP),
            "ancf_worker_main.cpp": sha256(WORKER_CPP),
            "kernel_protocol.py": sha256(WIRE_PY),
        },
        "patch_applied_in_worktree": True,
        "production_source_modified": True,
        "committed": False,
        "source_scope_pass": source_scope_pass,
        "compile_pass": True,
        "wire_protocol_smoke_pass": (
            gates["legacy_old_requests_byte_identical"]
            and gates["legacy_old_requests_worker_decode"]
            and gates["explicit_equivalence"]
            and gates["independent_EA_EI_mass_observable"]
            and gates["python_invalid_all_rejected"]
            and gates["raw_cpp_invalid_all_rejected"]
            and gates["response_schema_unchanged"]
        ),
        "response_schema_unchanged": gates["response_schema_unchanged"],
        "legacy_compatibility": {
            "old_payloads_byte_identical": gates["legacy_old_requests_byte_identical"],
            "old_payloads_worker_decode": gates["legacy_old_requests_worker_decode"],
        },
        "explicit_equivalent_wire_test": gates["explicit_equivalence"],
        "independent_property_wire_test": {
            "EA_EI_mass_observable": gates["independent_EA_EI_mass_observable"],
            "displaced_area_observable": gates["independent_displaced_area_observable"],
            "overall": False,
            "blocking_reason": summary["independent_properties"]["displaced_area_observability"],
        },
        "invalid_wire_tests": {
            "python_all_rejected": gates["python_invalid_all_rejected"],
            "raw_cpp_all_rejected": gates["raw_cpp_invalid_all_rejected"],
        },
        "worker_binary_sha256": sha256(WORKER),
        "worker_compile_command": (
            'call "C:\\Program Files (x86)\\Microsoft Visual Studio\\2022\\BuildTools\\VC\\Auxiliary\\Build\\vcvars64.bat" '
            '&& cl.exe /nologo /std:c++17 /EHsc /W4 /permissive- /O2 /DWIN32 /D_WINDOWS '
            '/I"src\\coupling\\cpp_worker_persistent_ipc_v1" /c "src\\coupling\\cpp_worker_persistent_ipc_v1\\ancf_kernel.cpp" '
            '/Fo"runtime\\ANCF_validation\\ancf_explicit_section_properties_wire_protocol_patch_v1_kernel.obj" '
            '&& cl.exe /nologo /std:c++17 /EHsc /W4 /permissive- /O2 /DWIN32 /D_WINDOWS '
            '/I"src\\coupling\\cpp_worker_persistent_ipc_v1" /c "src\\coupling\\cpp_worker_persistent_ipc_v1\\ancf_worker_main.cpp" '
            '/Fo"runtime\\ANCF_validation\\ancf_explicit_section_properties_wire_protocol_patch_v1_worker_main.obj" '
            '&& link.exe /nologo /OUT:"runtime\\ANCF_validation\\ancf_explicit_section_properties_wire_protocol_patch_v1_worker.exe" '
            '"runtime\\ANCF_validation\\ancf_explicit_section_properties_wire_protocol_patch_v1_kernel.obj" '
            '"runtime\\ANCF_validation\\ancf_explicit_section_properties_wire_protocol_patch_v1_worker_main.obj" bcrypt.lib'
        ),
        "section_extension": {
            "marker": "SPX1",
            "marker_uint32_le": "0x31585053",
            "version": 1,
            "explicit_mode_uint32": 1,
            "bytes": 44,
            "fields": [
                "explicit_EA_N",
                "explicit_EI_Nm2",
                "explicit_mass_per_length_kg_m",
                "explicit_displaced_area_m2",
            ],
        },
        "unchanged_response_schema": True,
        "participant_modified": False,
        "C_regression_run": False,
        "F_regression_run": False,
        "G1_run": False,
        "benchmark_run": False,
        "MATLAB": False,
        "OpenFOAM": False,
        "preCICE": False,
        "CFD_FSI": False,
        "historical_state_preserved": True,
        "test_summary": summary,
    }
    RESULT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    RAW.write_text(
        "\n".join(
            [
                "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_V1 RAW EVIDENCE",
                f"protocol_sha256={sha256(PROTOCOL)}",
                f"worker_sha256={sha256(WORKER)}",
                "compile_status=PASS",
                "numerical_benchmark_run=false",
                "G1_run=false",
                "OpenFOAM_run=false",
                "preCICE_run=false",
                "CFD_FSI_run=false",
                "",
                "TEST_SUMMARY_JSON:",
                SUMMARY.read_text(encoding="utf-8"),
                "",
                "SOURCE_DIFF_SHA256=" + sha256(DIFF),
                "SOURCE_DIFF:",
                DIFF.read_text(encoding="utf-8", errors="replace"),
            ]
        ),
        encoding="utf-8",
    )

    report = f"""# ANCF Explicit Section Properties Wire Protocol Patch V1

## Final status

ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_V1 = FAIL

Primary: INDEPENDENT_PROPERTY_WIRE_TEST_BLOCKED_BY_DISPLACED_AREA_OBSERVABILITY

The production wire patch is present in the working tree but is not committed because the frozen independent-property gate was not fully satisfiable with the current worker response contract.

## Identity and scope

- Baseline/current HEAD: 0e813bb680c6343fcdab24d86d56fa9c8718beba (no commit created)
- Protocol SHA-256: {sha256(PROTOCOL)}
- Kernel cpp SHA-256: {sha256(CPP)}
- Kernel hpp SHA-256: {sha256(HPP)}
- Worker source SHA-256: {sha256(WORKER_CPP)}
- Python protocol SHA-256: {sha256(WIRE_PY)}
- Changed tracked production files: kernel_protocol.py, ancf_worker_main.cpp
- Protected kernel cpp/hpp unchanged: PASS
- Participant/build files changed: NO

## Wire design implemented

The old payload remains byte-identical when section_property_mode is omitted or is legacy. Explicit requests append a 44-byte SPX1 trailer after slice positions: version 1, mode 1, and the four explicit values explicit_EA_N, explicit_EI_Nm2, explicit_mass_per_length_kg_m, and explicit_displaced_area_m2. Legacy mode rejects explicit values supplied alongside it; explicit mode requires all four values finite and positive. Response schema is unchanged.

## Frozen regression results

- Old four request shapes: PASS; baseline-source payload bytes identical and patched worker decoded all responses.
- Explicit-equivalent wire request: PASS; response numeric maximum absolute difference was 0.0 and payload hashes matched.
- Python invalid-input tests: PASS, all rejected.
- Raw C++ invalid-input tests: PASS, all rejected with nonzero worker return.
- Worker compile/link: PASS using MSVC 14.44.35207 x64 Build Tools, /std:c++17 /EHsc /W4 /permissive- /O2 /DWIN32 /D_WINDOWS, linked with bcrypt.lib.

## Frozen gate that failed

The independent explicit-property request produced a clear worker response difference for explicit EA/EI/mass versus legacy values, so those fields are demonstrably mapped through the wire and used by the kernel step. However, the current ancf_worker_main.cpp::process_step() receives base_load from the caller and only calls external_force() for mapped slice forces; it does not call static_base_load(). The unchanged response schema has no computed buoyancy/base-load field. Consequently, the test cannot observe whether explicit_displaced_area_m2 is used to assemble buoyancy inside the worker. The evidence records the field as serialized and parsed, but does not claim displaced-area runtime use.

Satisfying that exact gate would require a separately authorized worker observable (for example a versioned response/request diagnostic or a worker-side static-load operation), which is outside this patch's frozen no-response-schema-change scope. No such change was made.

## Prohibited actions confirmed

No C/F/G1 benchmark, G1, MATLAB, OpenFOAM, preCICE, CFD, or FSI run was performed. No kernel cpp/hpp, participant, solver, constitutive, or build-file modification was made. Historical ANCF states remain retained.

## Artifact hashes

- Test summary: {sha256(SUMMARY)}
- Raw evidence: {sha256(RAW)}
- Exact production diff: {sha256(DIFF)}
- Harness source: {sha256(HARNESS)}
- Worker binary: {sha256(WORKER)}
- Result JSON: {sha256(RESULT)}

The complete SHA-256 manifest is emitted separately.
"""
    REPORT.write_text(report, encoding="utf-8")

    artifact_paths = [
        PROTOCOL,
        REPORT,
        RESULT,
        RAW,
        DIFF,
        SUMMARY,
        HARNESS,
        WORKER,
        CPP,
        HPP,
        WORKER_CPP,
        WIRE_PY,
    ]
    manifest_lines = [
        "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_SHA256_MANIFEST_V1",
        "Manifest does not include its own self-referential hash.",
    ]
    for path in artifact_paths:
        manifest_lines.append(f"{path.relative_to(ROOT)}  {sha256(path)}")
    MANIFEST.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "status": result["status"],
                "protocol_sha256": sha256(PROTOCOL),
                "report_sha256": sha256(REPORT),
                "result_sha256": sha256(RESULT),
                "raw_sha256": sha256(RAW),
                "diff_sha256": sha256(DIFF),
                "manifest_sha256": sha256(MANIFEST),
                "worker_sha256": sha256(WORKER),
                "source_scope_pass": source_scope_pass,
                "committed": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
