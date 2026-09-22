"""Generate the read-only Coupling Baseline V2 freeze evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "runtime" / "ANCF_validation"
HEAD = "8443209c4db39572f5099bec5d66a093eec7cdc3"
PARENT = "f7dee49abd1510ce90d6163561a2d3155e49be65"
OLD_TAG = "ancf-coupling-baseline-v1"
OLD_TARGET = "dfb1a3e7e92220a2e4c9400317de372e637095eb"
NEW_TAG = "ancf-coupling-baseline-v2"
NEW_TARGET = HEAD
PREFIX = "COUPLING_BASELINE_V2"

SOURCE_PATHS = [
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
    "tools/precice_ancf_adapter_v1/ancf_generic_participant_v1.py",
    "tools/precice_ancf_adapter_v1/ancf_case_config_v1.py",
    "src/coupling/arbitrary_n_live_orchestration_v1/__init__.py",
    "src/coupling/arbitrary_n_live_orchestration_v1/manifest.py",
    "src/coupling/arbitrary_n_live_orchestration_v1/coordinator.py",
    "src/coupling/arbitrary_n_live_orchestration_v1/topology.py",
    "src/coupling/arbitrary_n_live_orchestration_v1/precice_backend.py",
    "src/coupling/multi_slice_mapping/__init__.py",
    "src/coupling/multi_slice_mapping/mapping.py",
    "src/coupling/checkpoint/__init__.py",
    "src/coupling/checkpoint/atomic_checkpoint.py",
    "tools/precice_ancf_adapter_v1/ancf_static_prestress_v1.py",
    "tools/precice_ancf_adapter_v1/ancf_static_prestress_driver_v1.cpp",
    "tools/precice_ancf_adapter_v1/ancf_damping_preprocessor_v1.py",
]

EVIDENCE_MANIFESTS = {
    "Ns1_LegacyPointLumped": "REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1_1_SHA256_MANIFEST.txt",
    "Ns2_PiecewiseLinearDistributed": "REAL_TWO_SLICE_SLD1_DISTRIBUTED_COUPLING_SMOKE_V1_SHA256_MANIFEST.txt",
    "Ns3_PiecewiseLinearDistributed": "REAL_THREE_SLICE_GENERIC_COUPLING_PREFLIGHT_V1_SHA256_MANIFEST.txt",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def raw_sha(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def lf_sha(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return sha256_bytes(data)


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    return result.stdout.strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def tracked(path: str) -> bool:
    result = subprocess.run(["git", "ls-files", "--error-unmatch", "--", path], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.returncode == 0


def evidence_index() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label, filename in EVIDENCE_MANIFESTS.items():
        path = OUT / filename
        entries = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []
        result[label] = {
            "manifest_path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "manifest_sha256": raw_sha(path) if path.is_file() else None,
            "entries": entries,
        }
    return result


def main() -> int:
    actual_head = git("rev-parse", "HEAD")
    actual_parent = git("rev-parse", "HEAD~1")
    old_target = git("rev-parse", f"{OLD_TAG}^{{commit}}")
    v2_existing = git("tag", "--list", NEW_TAG)
    tracked_clean = subprocess.run(["git", "diff", "--quiet"], cwd=ROOT).returncode == 0
    index_clean = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0
    if actual_head != HEAD or actual_parent != PARENT or old_target != OLD_TARGET or not tracked_clean or not index_clean:
        raise SystemExit("baseline identity or tracked/index cleanliness check failed")
    if v2_existing:
        existing_target = git("rev-parse", f"{NEW_TAG}^{{commit}}")
        if existing_target != NEW_TARGET:
            raise SystemExit("BASELINE_V2_TAG_CONFLICT")

    source_identity: dict[str, Any] = {
        "head": actual_head, "parent": actual_parent,
        "files": {},
        "topology_expected_sha256": "BC5A1159B459245EE9281021B8DA169189285DFA26A465E92F81BB485601A237",
    }
    for relative in SOURCE_PATHS:
        path = ROOT / relative
        if not path.is_file():
            source_identity["files"][relative] = {"exists": False, "tracked": tracked(relative), "raw_sha256": None, "lf_normalized_sha256": None}
            continue
        source_identity["files"][relative] = {
            "exists": True, "tracked": tracked(relative), "raw_sha256": raw_sha(path), "lf_normalized_sha256": lf_sha(path),
        }
    topology_actual = source_identity["files"]["src/coupling/arbitrary_n_live_orchestration_v1/topology.py"]["raw_sha256"]
    if topology_actual != source_identity["topology_expected_sha256"]:
        raise SystemExit("topology.py identity mismatch")

    statuses = {
        "A-F_CURRENT_LINE_VALIDATION": "CLOSED",
        "G1_CURRENT_LINE_VALIDATION": "NOT_CLOSED",
        "ANCF_INDEPENDENT_STRUCTURAL_VALIDATION": "NOT_CLOSED",
        "ANCF_SPANWISE_DISTRIBUTED_LOAD_RECONSTRUCTION_V1": "PASS",
        "ANCF_SPANWISE_RECONSTRUCTION_CONVERGENCE_CLOSURE_V1": "PASS",
        "PIECEWISE_LINEAR_CONTINUOUS_LOAD_RECONSTRUCTION_CONVERGENCE": "ESTABLISHED",
        "CURRENT_LINE_ARBITRARY_N_COUPLING_CAPABILITY_AUDIT_V1": "PASS",
        "ANCF_GENERIC_ARBITRARY_N_LIVE_COUPLING_ORCHESTRATION_V1": "PASS",
        "ANCF_GENERIC_TOPOLOGY_FORCE_EXCHANGE_REPAIR_CLOSURE_V1": "PASS",
        "REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1_1": "PASS_RETAINED_BY_SOURCE_IDENTITY",
        "REAL_TWO_SLICE_SLD1_DISTRIBUTED_COUPLING_SMOKE_V1": "PASS",
        "REAL_THREE_SLICE_GENERIC_COUPLING_PREFLIGHT_V1": "PASS",
        "GENERIC_LIVE_COUPLING_PIPELINE": "REAL_RUNTIME_ESTABLISHED_FOR_NS1_LEGACY_AND_NS2_NS3_SLD1",
        "SLD1_DISTRIBUTED_REAL_RUNTIME": "ESTABLISHED_FOR_NS2_NS3",
        "GLOBAL_STRUCTURE_STATE": "ONE_ANCF_STATE",
        "COUPLING_INFRASTRUCTURE_QUALIFICATION": "COMPLETE",
        "GENERIC_ARBITRARY_N_ARCHITECTURE": "ESTABLISHED_WITH_BOUNDED_REAL_RUNTIME_EVIDENCE",
        "INFRASTRUCTURE_SPECIFIC_VALIDATION": "CLOSED",
    }
    evidence = evidence_index()
    nonclaims = [
        "no Ns=5 real runtime", "no Ns=8 real runtime", "no slice-number-independence VIV study",
        "no long-time flexible-riser VIV validation", "no literature flexible-riser validation",
        "real rollback was not naturally triggered", "G1 remains NOT_CLOSED",
        "independent ANCF structural validation remains NOT_CLOSED",
        "interface remains STRUCTURE_3D_INTERFACE_2D",
        "this baseline does not claim every possible Ns has been physically validated",
    ]
    result = {
        "task": "COUPLING_BASELINE_V2_FREEZE", "status": "PASS",
        "production_commit": HEAD, "production_parent": PARENT,
        "old_baseline_tag": {"name": OLD_TAG, "target": old_target},
        "new_baseline_tag": {"name": NEW_TAG, "target": NEW_TARGET, "preexisting": bool(v2_existing)},
        "tracked_diff_empty": tracked_clean, "index_diff_empty": index_clean,
        "production_source_modified": 0, "numerical_execution_performed": False,
        "openfoam_runs": 0, "precice_runs": 0, "ancf_physics_runs": 0,
        "g1_runs": 0, "ns5_runs": 0, "ns8_runs": 0, "push_performed": False,
        "validation_status": statuses,
        "arbitrary_n_claim": {
            "offline_evidenced": [1, 2, 3, 5, 8],
            "real_runtime_evidenced": [1, 2, 3],
            "real_runtime_nonuniform_positions": {"Ns": 3, "positions_m": [4.65, 4.95, 5.35]},
            "real_runtime_sld1": [2, 3],
        },
        "ns3_identical_force_caveat": True,
        "wrapper_warning": "POST_RUNTIME_WRAPPER_PRESENTATION_WARNING",
        "authorized_next_phase": "RETURN_TO_SOLVER_VALIDATION_MAINLINE",
        "source_identity": source_identity,
        "evidence_index": evidence,
        "nonclaims": nonclaims,
    }

    protocol = f'''# COUPLING_BASELINE_V2_FREEZE\n\nStatus: `COUPLING_BASELINE_V2_FREEZE = PASS`\n\nThe frozen production commit is `{HEAD}`. The old tag remains `{OLD_TAG} -> {OLD_TARGET}`. The new local annotated tag is `{NEW_TAG} -> {NEW_TARGET}`.\n\nThis baseline consolidates existing identity and validation evidence only. It performs no OpenFOAM, preCICE, ANCF-physics, G1, Ns=5, Ns=8, or new smoke execution.\n'''
    status_json = {"schema_version": 1, "production_commit": HEAD, "validation_status": statuses, "arbitrary_n_claim": result["arbitrary_n_claim"], "nonclaims": nonclaims}
    runtime_md = f'''# COUPLING_BASELINE_V2 real-runtime evidence index\n\n## Ns=1\n\n`REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1_1 = PASS_RETAINED_BY_SOURCE_IDENTITY`\n\nLegacyPointLumped, SLD1=false, three accepted windows, real OpenFOAM, real preCICE, and real ANCF worker.\n\n## Ns=2\n\n`REAL_TWO_SLICE_SLD1_DISTRIBUTED_COUPLING_SMOKE_V1 = PASS`\n\nPiecewiseLinearDistributed, SLD1=true, positions 4.75/5.25 m, active interval [4.5,5.5] m, independent generalized-force agreement, and one global ANCF advance per window.\n\n## Ns=3\n\n`REAL_THREE_SLICE_GENERIC_COUPLING_PREFLIGHT_V1 = PASS`\n\nPiecewiseLinearDistributed, SLD1=true, nonuniform positions 4.65/4.95/5.35 m. The runtime read order was slice_0002, slice_0001, slice_0000 while the emitted manifest/SLD1 order was slice_0000, slice_0001, slice_0002. Three motion destinations were correct and one global ANCF advance occurred per complete force set.\n\nArtifact-manifest hashes are recorded in `COUPLING_BASELINE_V2_RESULT.json`.\n'''
    nonclaims_md = "# COUPLING_BASELINE_V2 non-claims\n\n" + "\n".join(f"- {item}" for item in nonclaims) + "\n\nThe Ns=3 cases used identical fluid configurations, so identical force vectors do not independently discriminate force magnitude. Identity remains supported by stable IDs, reversed read order, nonuniform coordinates, manifest reordering, SLD1 metadata, structural coordinates, motion destinations, and offline mismatch rejection.\n\nThe Ns=3 Windows wrapper UnicodeEncodeError is retained as `POST_RUNTIME_WRAPPER_PRESENTATION_WARNING`; it occurred after all participants finalized and does not change the Ns=3 PASS.\n"
    report = f'''# COUPLING_BASELINE_V2_FREEZE report\n\n- Production commit: `{HEAD}`\n- Old tag: `{OLD_TAG} -> {OLD_TARGET}`\n- New tag: `{NEW_TAG} -> {NEW_TARGET}`\n- Generic arbitrary-N architecture: `ESTABLISHED_WITH_BOUNDED_REAL_RUNTIME_EVIDENCE`\n- Offline evidence: Ns=1,2,3,5,8\n- Real runtime evidence: Ns=1,2,3\n- Distributed SLD1 real runtime: Ns=2,3\n- Global structure: `ONE_ANCF_STATE`\n- Infrastructure qualification: `COMPLETE`\n- G1: `NOT_CLOSED`\n- Independent ANCF structural validation: `NOT_CLOSED`\n- Production source modifications: `0`\n- Numerical execution in this freeze task: `0`\n- Push performed: `false`\n\nAuthorized next phase: `RETURN_TO_SOLVER_VALIDATION_MAINLINE`.\n'''
    write(OUT / f"{PREFIX}_FREEZE_PROTOCOL.md", protocol)
    write(OUT / f"{PREFIX}_SOURCE_IDENTITY.json", json.dumps(source_identity, ensure_ascii=False, indent=2) + "\n")
    write(OUT / f"{PREFIX}_VALIDATION_STATUS.json", json.dumps(status_json, ensure_ascii=False, indent=2) + "\n")
    write(OUT / f"{PREFIX}_RUNTIME_EVIDENCE_INDEX.md", runtime_md)
    write(OUT / f"{PREFIX}_NONCLAIMS.md", nonclaims_md)
    write(OUT / f"{PREFIX}_RESULT.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    write(OUT / f"{PREFIX}_REPORT.md", report)
    artifacts = [OUT / f"{PREFIX}_{suffix}" for suffix in ("FREEZE_PROTOCOL.md", "SOURCE_IDENTITY.json", "VALIDATION_STATUS.json", "RUNTIME_EVIDENCE_INDEX.md", "NONCLAIMS.md", "RESULT.json", "REPORT.md")]
    lines = ["# SHA256 manifest; self-entry excluded"] + [f"{path.name}  {raw_sha(path)}" for path in artifacts]
    write(OUT / f"{PREFIX}_SHA256_MANIFEST.txt", "\n".join(lines) + "\n")
    print(json.dumps({"status": "PASS", "head": actual_head, "old_tag_target": old_target, "v2_preexisting": bool(v2_existing), "artifact_manifest": str(OUT / f"{PREFIX}_SHA256_MANIFEST.txt")}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
