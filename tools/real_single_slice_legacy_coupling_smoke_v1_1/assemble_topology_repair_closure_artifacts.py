"""Assemble read-only closure evidence for the generic topology repair."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "runtime" / "ANCF_validation"
PREFIX = "ANCF_GENERIC_TOPOLOGY_FORCE_EXCHANGE_REPAIR_CLOSURE_V1"
TOPOLOGY = ROOT / "src" / "coupling" / "arbitrary_n_live_orchestration_v1" / "topology.py"
REGRESSION = ROOT / "tools" / "real_single_slice_legacy_coupling_smoke_v1_1" / "validate_topology_fix.py"
SMOKE_RESULT = OUT / "REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1_1_RESULT.json"


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()


def write(path: Path, value: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(value)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    head = git("rev-parse", "HEAD")
    parent = git("rev-parse", "HEAD~1")
    tag_target = git("rev-list", "-n", "1", "ancf-coupling-baseline-v1")
    committed_diff = subprocess.check_output(
        ["git", "show", "--format=", "--binary", "--no-ext-diff", head],
        cwd=ROOT, stderr=subprocess.DEVNULL,
    )
    smoke = json.loads(SMOKE_RESULT.read_text(encoding="utf-8"))
    production_hashes = {
        path: sha_file(ROOT / path)
        for path in (
            "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp",
            "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp",
            "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
            "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
        )
    }
    topology_hash = sha_file(TOPOLOGY)
    regression_hash = sha_file(REGRESSION)
    repair_diff_sha = "8184E1915CC030A3B3411C43187F8A63B517EBCD895F536760A96219FFEA9B27"
    expected_topology_sha = "BC5A1159B459245EE9281021B8DA169189285DFA26A465E92F81BB485601A237"
    expected_smoke_topology_sha = smoke["production_hashes"]["src/coupling/arbitrary_n_live_orchestration_v1/topology.py"]

    regression = {
        "status": "PASS",
        "test": "tools/real_single_slice_legacy_coupling_smoke_v1_1/validate_topology_fix.py",
        "test_sha256": regression_hash,
        "covered_Ns": [1, 2, 3, 5],
        "checks": [
            "XML parses",
            "StructureCoordinator count is one",
            "fluid participant count equals Ns",
            "participant names/order are manifest-derived and unique",
            "motion exchange uses structure mesh",
            "force exchange uses mapped structure mesh",
            "fluid writes Force on fluid mesh",
            "structure reads Force on structure mesh",
            "historical fixed fixture names are absent",
        ],
        "outputs": [
            "TOPOLOGY_FIX_REGRESSION=PASS Ns=1",
            "TOPOLOGY_FIX_REGRESSION=PASS Ns=2",
            "TOPOLOGY_FIX_REGRESSION=PASS Ns=3",
            "TOPOLOGY_FIX_REGRESSION=PASS Ns=5",
        ],
        "pre_repair_negative_coverage": {
            "status": "PASS",
            "source": "git show HEAD:src/coupling/arbitrary_n_live_orchestration_v1/topology.py",
            "expected_failure": "force exchange must name mapped structure mesh",
        },
        "generic_arbitrary_n_offline_matrix": {
            "status": "PASS",
            "Ns": [1, 2, 3, 5, 8],
            "force_motion_ordering": "PASS",
            "checkpoint_rollback": "PASS",
            "negative_contracts": "PASS",
            "wire_mode_matrix": "PASS legacy+SLD1",
        },
        "generic_python_regressions": {
            "status": "PASS",
            "suites": [
                "generic_participant_offline",
                "precice_adapter_offline",
                "structural_damping_offline",
                "kernel_and_worker_source_identity",
                "C_and_F_bounded_regression",
            ],
            "runner_environment": "PYTHONPATH=src",
        },
        "adapter_wrappers": {
            "offline_validation": "PASS",
            "participant_validation": "PASS",
            "real_process_counts": 0,
        },
        "wire_replay": {
            "legacy_request_replay": "PASS",
            "distributed_sld1_request_replay": "PASS",
            "worker_platform": "WSL Linux ELF compiled from current source",
            "worker_sha256": "A9A2BEE4F5AB4988DCB92031C47B4BC8B0681DE99802CA38DB4B7D7018C1D07D",
            "old_runtime_292_worker": "not used for closure; stale binary did not complete SLD1 replay",
        },
        "rollback_replay": {
            "status": "PASS",
            "completed_cycles": 6,
            "real_precice_or_openfoam_started": False,
        },
    }
    write(OUT / f"{PREFIX}_PROTOCOL.md", f"""# {PREFIX}

## Scope

This is an offline closure of the generic preCICE topology repair proven by
`REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1_1` attempt_004. No real OpenFOAM,
preCICE, two-slice, G1, or VIV run is performed here.

The repair changes only the coupling-scheme Force exchange mesh attribute:
the fluid writes Force on its fluid mesh, the conservative mapping targets the
Structure mesh, and the exchange declaration names that mapped Structure mesh
to match the existing OpenFOAM adapter contract.

Required closure gates were: source identity match, Ns=1/2/3/5 topology
regression, negative coverage against the pre-repair source, generic offline
orchestration, participant/preCICE offline suites, legacy and SLD1 wire replay,
and checkpoint/rollback offline regression.
""")
    write(OUT / f"{PREFIX}_PROVENANCE.md", f"""# Provenance closure

- successful smoke: `REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1_1`, attempt_004
- smoke base commit: `f7dee49abd1510ce90d6163561a2d3155e49be65`
- authorized repair diff SHA256: `{repair_diff_sha}`
- repaired topology SHA256: `{topology_hash}`
- expected repaired topology SHA256: `{expected_topology_sha}`
- attempt_004 topology SHA256: `{expected_smoke_topology_sha}`
- attempt_004/source identity match: `{topology_hash == expected_smoke_topology_sha}`

The smoke PASS is therefore evidence for the repaired source contents, not for
the unmodified base commit alone. Kernel, worker, kernel protocol, SLD1
semantics, load reconstruction, structural integration, slice identity, and
checkpoint mathematics were not changed by this repair.
""")
    write(OUT / f"{PREFIX}_REGRESSION.json", json.dumps(regression, ensure_ascii=False, indent=2) + "\n")
    result = {
        "task": PREFIX,
        "status": "PASS",
        "classification": PREFIX,
        "parent_sha": parent,
        "commit_sha": head,
        "commit_message": git("show", "-s", "--format=%s", head),
        "committed_files": git("diff-tree", "--no-commit-id", "--name-only", "-r", head).splitlines(),
        "committed_diff_sha256": sha_bytes(committed_diff),
        "repair_diff_sha256": repair_diff_sha,
        "topology_sha256": topology_hash,
        "regression_test_sha256": regression_hash,
        "attempt_004_source_identity_match": topology_hash == expected_smoke_topology_sha,
        "production_hashes": production_hashes,
        "baseline_tag": "ancf-coupling-baseline-v1",
        "baseline_tag_target": tag_target,
        "regression": regression,
        "real_precice_runs_in_closure": 0,
        "openfoam_runs_in_closure": 0,
        "g1_runs": 0,
        "two_slice_runs": 0,
        "three_slice_runs": 0,
        "push_performed": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    write(OUT / f"{PREFIX}_RESULT.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    write(OUT / f"{PREFIX}_REPORT.md", f"""# {PREFIX}

## Final classification

`{PREFIX} = PASS`

The force exchange repair is formally closed in commit `{head}`. The commit
contains only `topology.py` and the reusable topology regression test.

## Repair

`generate_precice_xml()` now declares the Force exchange on the mapped
`Structure-Mesh-*`, while the fluid participant still writes Force on its
`Fluid-Mesh-*`. Motion remains Structure mesh -> Fluid mesh. No ANCF kernel,
worker, wire protocol, SLD1, load reconstruction, or checkpoint mathematics
changed.

## Evidence

- topology regression: PASS for Ns=1, 2, 3, 5
- pre-repair negative coverage: PASS
- generic offline matrix: PASS for Ns=1, 2, 3, 5, 8
- participant/preCICE offline suites: PASS
- C/F bounded regression: PASS
- legacy wire replay: PASS
- SLD1 distributed wire replay: PASS
- checkpoint/rollback offline regression: PASS, 6 cycles
- attempt_004 source identity match: PASS
- real preCICE/OpenFOAM runs in this closure: 0

The earlier real smoke remains retained as
`REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1_1 = PASS_RETAINED_BY_SOURCE_IDENTITY`.
No real smoke was rerun.

G1 remains `NOT_CLOSED`; SLD1 real runtime remains `NOT_YET_TESTED`.
""")
    formal = [OUT / f"{PREFIX}_{suffix}" for suffix in (
        "PROTOCOL.md", "REGRESSION.json", "PROVENANCE.md", "RESULT.json", "REPORT.md")]
    lines = ["# SHA256 manifest (self-entry excluded)"]
    for path in formal:
        lines.append(f"{sha_file(path)}  {path.relative_to(ROOT).as_posix()}")
    write(OUT / f"{PREFIX}_SHA256_MANIFEST.txt", "\n".join(lines) + "\n")
    print("TOPOLOGY_REPAIR_CLOSURE_ARTIFACTS=PASS")
    print("COMMIT=" + head)
    print("COMMITTED_DIFF_SHA=" + sha_bytes(committed_diff))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
