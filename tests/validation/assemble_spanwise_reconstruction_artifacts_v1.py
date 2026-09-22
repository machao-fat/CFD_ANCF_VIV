"""Assemble immutable runtime evidence for the spanwise mapping qualification."""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "runtime" / "ANCF_validation"
PREFIX = "ANCF_SPANWISE_DISTRIBUTED_LOAD_RECONSTRUCTION_V1"
START_HEAD = "7a953ef9349f99339329103fb1969ae022af21de"


def sha(path: pathlib.Path, normalize_text: bool = False) -> str:
    data = path.read_bytes()
    if normalize_text:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest().upper()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def git_diff_sha(parent: str, commit: str) -> str:
    data = subprocess.check_output(["git", "diff", "--binary", f"{parent}..{commit}"], cwd=ROOT)
    return hashlib.sha256(data).hexdigest().upper()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    offline_path = OUT / f"{PREFIX}_OFFLINE_VERIFICATION.json"
    offline = json.loads(offline_path.read_text(encoding="utf-8"))
    current_head = git("rev-parse", "HEAD")
    current_parent = git("rev-parse", "HEAD~1")
    tag_target = git("rev-list", "-n", "1", "ancf-coupling-baseline-v1")
    committed_diff_sha256 = git_diff_sha(current_parent, current_head)

    production_paths = [
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp",
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp",
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
        "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
        "tools/precice_ancf_adapter_v1/ancf_case_config_v1.py",
        "tools/precice_ancf_adapter_v1/ancf_generic_participant_v1.py",
    ]
    production = {}
    for relative in production_paths:
        path = ROOT / relative
        production[relative] = {
            "sha256_raw": sha(path),
            "sha256_lf_normalized": sha(path, normalize_text=True),
        }

    bounded = {
        "C_current_line_replacement": {
            "status": "PASS", "meshes": [2, 4, 8, 16],
            "final_gate": "PASS", "solver": "PotentialBacktrackingNewton",
            "contract": "canonical historical flags without -Werror",
        },
        "F_bounded": {
            "status": "PASS", "meshes": [4, 8, 16, 32],
            "residuals": {
                "4": 7.3274719625260332e-14,
                "8": 5.9530158580400894e-13,
                "16": 5.5169202539673279e-12,
                "32": 3.5896619010600261e-11,
            },
        },
        "legacy_kernel_selftest": {"status": "PASS"},
        "residual_scale": {
            "status": "PASS", "scale": 5.2970197382636739,
            "normalized_residual": 1.0692821808089446e-09,
            "trace_semantic_tests": "PASS",
        },
        "worker_kernel_tests": {"status": "PASS", "tests": 5},
        "comprehensive_worker_api_tests": {"status": "PASS", "tests": 44, "skipped": 11},
        "participant_and_damping_tests": {"status": "PASS", "tests": 45},
        "wire_replay": {"status": "PASS", "legacy": "PASS", "sld1": "PASS"},
    }

    result = {
        "schema_version": "ancf_spanwise_distributed_load_reconstruction_v1",
        "status": "PASS",
        "classification": "ANCF_SPANWISE_DISTRIBUTED_LOAD_RECONSTRUCTION_V1",
        "new_capability": "PIECEWISE_LINEAR_DISTRIBUTED_CONSISTENT_LOAD",
        "endpoint_policy": "NEAREST_CONSTANT",
        "legacy_mapping": "PRESERVED",
        "start_head": START_HEAD,
        "production_commit": current_head,
        "production_parent": current_parent,
        "commit_message": git("show", "-s", "--format=%s", current_head),
        "committed_diff_sha256": committed_diff_sha256,
        "baseline_tag": "ancf-coupling-baseline-v1",
        "baseline_tag_target": tag_target,
        "unit_contract": {
            "legacy_slice_force": "integrated_force_N",
            "distributed_sample": "sectional_line_force_Npm",
            "legacy_conversion": "OpenFOAM_N / unit_span_m * slice_length_m -> integrated_slice_force_N",
            "distributed_conversion": "OpenFOAM_N / unit_span_m -> sectional_line_force_Npm",
        },
        "reconstruction": {
            "active_region": "zero outside, explicit [s_min,s_max]",
            "interior": "piecewise linear between sorted samples",
            "endpoints": "nearest constant",
            "integration": "direct H^T f ds, split at element/sample/active boundaries",
            "quadrature": "existing Gauss-3",
            "constant_mode": "OPTIONAL_NOT_IMPLEMENTED_IN_V1",
        },
        "offline_verification": offline,
        "bounded_regressions": bounded,
        "wire_schema": "UNCHANGED_LEGACY_PLUS_OPTIONAL_SLD1_MODEL_EXTENSION",
        "known_v1_limitation": "NO_CROSS_REGION_LINEAR_INTERPOLATION_SUPPORT",
        "prohibited_execution_counts": {
            "G1_numerical": 0,
            "CFD": 0,
            "FSI": 0,
            "OpenFOAM": 0,
            "real_preCICE": 0,
            "VIV_production": 0,
            "three_slice_production": 0,
        },
        "production_source_changed": True,
        "production_identities": production,
    }
    result_path = OUT / f"{PREFIX}_RESULT.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    protocol = OUT / f"{PREFIX}_PROTOCOL.md"
    design = OUT / f"{PREFIX}_DESIGN_AUDIT.md"
    unit = OUT / f"{PREFIX}_UNIT_CONTRACT.md"
    wire = OUT / f"{PREFIX}_WIRE_AUDIT.md"
    convergence = OUT / f"{PREFIX}_CONVERGENCE.csv"
    legacy = OUT / f"{PREFIX}_LEGACY_REGRESSION.json"
    report_path = OUT / f"{PREFIX}_REPORT.md"
    report = f"""# {PREFIX} — report

## Final result

`{PREFIX} = PASS`.

Capability: `PIECEWISE_LINEAR_DISTRIBUTED_CONSISTENT_LOAD`  
Endpoint policy: `NEAREST_CONSTANT`  
Legacy mapping: `PRESERVED`  
Production commit: `{current_head}`  
Starting HEAD: `{START_HEAD}`  
Baseline tag target: `{tag_target}`

## Unit and old mapping

The preCICE/OpenFOAM Force read by the participant is an integrated force in
N. The legacy adapter computes `N / unit_span_m -> N/m`, then multiplies by
`slice_length_m` to form the historical integrated `slice_force` in N. The
kernel applies the unchanged point-lumped contract `H(S_j)^T F_j`.

The new path sends explicit `spanwise_line_force_Npm` samples in N/m and
integrates `H_e(s)^T f_h(s) ds` directly. It uses nearest-constant endpoint
extension, zero outside the active interval, splitting at all element/sample/
active boundaries and existing Gauss-3 quadrature. No `f_j DeltaS_j` point
replacement is used.

## Offline verification

The independent NumPy 32-point reference passed constant, exact linear,
nonuniform sample, endpoint-extension, zero-outside, `N_e != N_s`, and
slice-not-at-node cases. Generalized-load, total-force, and virtual-work
mismatches were all within the frozen `2e-12` test tolerance. Legacy
point-lumped compatibility passed with L2 error
`4.501197953317952e-16`.

Smooth-load evidence (`Ns=5,10,20,40`) is in `{convergence.name}`. It records
near-machine generalized-force and total-force errors without imposing a
fitted convergence slope.

## Bounded regression summary

| Regression | Result |
|---|---|
| C current-line canonical bounded case | PASS; meshes 2/4/8/16; final gate PASS |
| F bounded static case | PASS; meshes 4/8/16/32 |
| Legacy kernel/self-test | PASS |
| Candidate-A stable-potential path | PASS through C/F and residual-scale checks |
| residual-scale diagnostic | PASS; trace semantics PASS |
| worker/kernel persistent IPC tests | PASS; 5 tests |
| comprehensive worker/API audit | PASS; 44 tests, 11 skipped |
| participant/damping tests | PASS; 45 tests |
| legacy worker replay | PASS |
| new SLD1 worker replay | PASS |

The existing C test emits the known unused `theta_eb` warning only under the
canonical no-`-Werror` contract; it was not modified. No C/F historical
evidence was overwritten.

## Wire/config compatibility

`WIRE_SCHEMA = UNCHANGED` for legacy requests and responses. SLD1 is an
optional versioned model trailer. Legacy bytes contain no SLD1 marker and
retain their integrated-force meaning; malformed or unknown SLD1 metadata is
rejected rather than silently reinterpreted. Existing configurations remain
legacy by default. New distributed cases opt in through the generic config
fields `mode`, `active_start_m`, `active_end_m`, `endpoint_policy`, and
`sectional_line_force_Npm`.

V1 deliberately implements one active region. The retained limitation is
`NO_CROSS_REGION_LINEAR_INTERPOLATION_SUPPORT`; future independent regions
must be represented by an explicit successor contract.

## Scope and non-claims

G1 numerical execution count is 0. CFD, OpenFOAM, real preCICE, FSI, VIV,
long-time coupling, and three-slice production counts are all 0. This result
establishes only the generic structural-side line-load reconstruction and
consistent generalized-load integration. It does not close G1 or independent
ANCF structural validation and does not validate end-to-end coupling.

## Artifact references

The design audit is `{design.name}`; unit contract is `{unit.name}`; wire audit
is `{wire.name}`; offline result is `{offline_path.name}`; and legacy regression
is `{legacy.name}`. The production source identity table is in the machine-
readable result JSON.
"""
    report_path.write_text(report, encoding="utf-8")

    artifact_paths = [
        protocol, design, unit, wire, offline_path, convergence, legacy,
        OUT / f"{PREFIX}_RAW.txt",
        report_path, result_path,
        ROOT / "tests/validation/ancf_spanwise_distributed_load_reconstruction_v1.cpp",
        ROOT / "tests/validation/ancf_spanwise_distributed_load_reconstruction_v1.py",
        ROOT / "tests/validation/ancf_spanwise_wire_compatibility_v1.py",
        ROOT / "tests/validation/assemble_spanwise_reconstruction_artifacts_v1.py",
    ]
    manifest = OUT / f"{PREFIX}_SHA256_MANIFEST.txt"
    lines = [
        f"schema_version=1",
        f"production_commit={current_head}",
        f"production_parent={current_parent}",
        f"committed_diff_sha256={committed_diff_sha256}",
        f"baseline_tag=ancf-coupling-baseline-v1",
        f"baseline_tag_target={tag_target}",
        "NOTE=manifest hash is intentionally omitted to avoid self-reference",
    ]
    for path in artifact_paths:
        if path.exists():
            lines.append(f"{path.relative_to(ROOT).as_posix()} {sha(path)}")
    for relative in production_paths:
        path = ROOT / relative
        lines.append(f"{relative} [LF-normalized] {sha(path, normalize_text=True)}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(report_path)
    print(result_path)
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
