"""Offline preflight for the fresh C++ t=0 three-slice launch.

The command only validates immutable inputs and writes a launch checklist. It
never starts the worker, OpenFOAM, WSL, MATLAB, or CFD.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tools.cpp_worker_fresh_t0_v1 import run_authorized_fresh_t0_001 as launch
from coupling.cpp_worker_confirm_v1.contracts import CppConfirmContract, REAL_AUTHORIZATION_TOKEN


PROJECT = launch.PROJECT
RESULTS = PROJECT / "results/239_cpp_worker_fresh_t0_real_preflight_v1"
DOCS = PROJECT / "docs/239_cpp_worker_fresh_t0_real_preflight_v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _boundary_values_present(root: Path) -> bool:
    """OpenFOAM surface patch fields must declare explicit boundary values."""
    for name, value in (("meshPhi", "uniform 0"), ("phi", "uniform 0"),
                        ("Uf", "uniform (0 0 0)")):
        path = root / "0" / name
        if not path.is_file():
            return False
        text = path.read_text(encoding="utf-8")
        for patch in ("lower", "upper", "outlet", "inlet", "cylinder"):
            match = re.search(rf"(?ms)^\s*{patch}\s+\{{(.*?)\}}", text)
            if not match or f"value {value};" not in match.group(1):
                return False
    return True


def main() -> int:
    state = json.loads(launch.SOURCE.read_bytes().decode("utf-8")) if launch.SOURCE.is_file() else {}
    slices = []
    for sid in range(3):
        root = launch.TEMPLATE_ROOT / f"slice_{sid:04d}"
        required = {name: (root / "0" / name).is_file()
                    for name in ("U", "p", "phi", "Uf", "meshPhi", "motionScale")}
        control = (root / "system" / "controlDict").read_text(encoding="utf-8") if (root / "system" / "controlDict").is_file() else ""
        motion = (root / "constant" / "dynamicMeshDict").read_text(encoding="utf-8") if (root / "constant" / "dynamicMeshDict").is_file() else ""
        slices.append({"slice_id": sid, "fields_complete": all(required.values()),
                       "fields": required,
                       "boundary_values_present": _boundary_values_present(root),
                       "delta_t_00125": bool(re.search(r"(?m)^\s*deltaT\s+0?\.00125\s*;", control)),
                       "coupling_delta_t_00125": bool(re.search(r"(?m)^\s*couplingDeltaT\s+0?\.00125\s*;", motion))})
    try:
        contract = CppConfirmContract(
            stage_id=launch.STAGE_ID, run_id=launch.RUN_ID, case_id=launch.CASE_ID,
            runtime=launch.RUNTIME, results=launch.RESULTS,
            source_checkpoint=launch.SOURCE, source_checkpoint_sha256=launch.SOURCE_SHA256,
            source_global_step=0, source_time_s=0.0, source_tick=0, steps=40,
            segment_duration_s=0.05, global_dt_s=0.00125, slice_count=3,
            allow_real_external_processes=True, authorization=REAL_AUTHORIZATION_TOKEN)
        contract.validate(PROJECT)
        contract_valid = True
        contract_error = None
    except Exception as exc:
        contract_valid = False
        contract_error = str(exc)
    process_query = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    process_rows = []
    if process_query.returncode == 0 and process_query.stdout.strip():
        raw = json.loads(process_query.stdout)
        process_rows = raw if isinstance(raw, list) else [raw]
    runtime_marker = str(launch.RUNTIME).lower().replace("/", "\\")
    unowned = [row for row in process_rows
               if "cfd_ancf_ancf_kernel_worker" in str(row.get("ExecutablePath", "")).lower()
               and runtime_marker not in str(row.get("ExecutablePath", "")).lower().replace("/", "\\")]
    checks = {
        "contract_valid": contract_valid,
        "source_sha256": _sha256(launch.SOURCE) == launch.SOURCE_SHA256 if launch.SOURCE.is_file() else False,
        "source_identity_zero": state.get("global_step") == 0 and state.get("time_s") == 0.0 and state.get("integer_tick") == 0,
        "source_equilibrated": state.get("equilibrated") is True and state.get("finite_value_audit") is True,
        "worker_present": launch.WORKER_EXE.is_file(),
        "library_hash": launch.LIBRARY.is_file() and _sha256(launch.LIBRARY) == launch.EXPECTED_LIBRARY_SHA256,
        "three_slice_cases_complete": all(row["fields_complete"] and row["boundary_values_present"] for row in slices),
        "three_slice_dt_consistent": all(row["delta_t_00125"] and row["coupling_delta_t_00125"] for row in slices),
        "no_unowned_cpp_worker": not unowned,
    }
    evidence = {
        "stage_id": "stage4f_d_cpp_worker_fresh_t0_real_preflight_v1",
        "run_id": "cpp_worker_fresh_t0_preflight_20260827_001",
        "case_id": launch.CASE_ID,
        "checks": checks,
        "contract_error": contract_error,
        "source": {"path": str(launch.SOURCE), "sha256": _sha256(launch.SOURCE) if launch.SOURCE.is_file() else None,
                    "step": state.get("global_step"), "time_s": state.get("time_s"), "tick": state.get("integer_tick")},
        "slices": slices,
        "gate": "STAGE4F_D_CPP_WORKER_FRESH_T0_REAL_PREFLIGHT_V1_GATE: pass" if all(checks.values()) else "STAGE4F_D_CPP_WORKER_FRESH_T0_REAL_PREFLIGHT_V1_GATE: do_not_pass",
        "launch_performed": False,
        "real_process_starts": {"CPP_WORKER": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "old_evidence_modified": False,
        "old_runtime_reused": False,
        "unowned_cpp_workers": unowned,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    (RESULTS / "fresh_t0_real_launch_preflight.json").write_bytes(payload)
    (RESULTS / "stage4f_d_cpp_worker_fresh_t0_real_preflight_v1_gate.json").write_bytes(payload)
    (DOCS / "fresh_t0_real_launch_preflight_report.md").write_text(
        "# Fresh C++ t=0 real-launch preflight\n\n"
        "This is an offline checklist only; no real process was started.\n\n"
        f"- Gate: `{evidence['gate']}`\n"
        f"- Source: `{launch.SOURCE}` (step 0, time 0, tick 0)\n"
        "- Three slices, global dt=0.00125, bounded window=40 steps (0.05 s).\n"
        "- Real starts: MATLAB=0, OpenFOAM=0, WSL=0, CFD=0.\n",
        encoding="utf-8")
    print(json.dumps({"gate": evidence["gate"], "checks": checks, "launch_performed": False}, ensure_ascii=True, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
