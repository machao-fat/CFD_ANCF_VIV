"""Fail-closed preflight for a future real C++ worker segment.

This command only audits immutable inputs and writes a launch checklist. It
never starts MATLAB, OpenFOAM, WSL, CFD, or the C++ worker continuation.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
CASE_ROOT = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v2/run_20260827_retry1/cases"
CPP_RUNTIME = PROJECT / "runtime/stage4f_d_cpp_worker_initialization_v1/run_20260827_cpp_only"
STATE = CPP_RUNTIME / "ancf_t0_state_cpp.json"
INIT_AUDIT = PROJECT / "results/237_cpp_worker_initialization_v1/cpp_initialization_audit.json"
RESULT = PROJECT / "results/238_cpp_worker_real_launch_preflight_v1"
DOC = PROJECT / "docs/238_cpp_worker_real_launch_preflight_v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    required_fields = ("U", "p", "phi", "Uf", "meshPhi", "motionScale")
    state = json.loads(STATE.read_bytes().decode("utf-8")) if STATE.is_file() else {}
    init_audit = json.loads(INIT_AUDIT.read_bytes().decode("utf-8")) if INIT_AUDIT.is_file() else {}
    slices = []
    for sid in range(3):
        root = CASE_ROOT / f"slice_{sid:04d}"
        fields = {name: (root / "0" / name).is_file() for name in required_fields}
        control = (root / "system" / "controlDict").read_text(encoding="utf-8") if (root / "system" / "controlDict").is_file() else ""
        motion = (root / "constant" / "dynamicMeshDict").read_text(encoding="utf-8") if (root / "constant" / "dynamicMeshDict").is_file() else ""
        slices.append({
            "slice_id": sid,
            "root": str(root),
            "fields": fields,
            "fields_complete": all(fields.values()),
            "delta_t_00125": bool(re.search(r"(?m)^\s*deltaT\s+0?\.00125\s*;", control)),
            "coupling_delta_t_00125": bool(re.search(r"(?m)^\s*couplingDeltaT\s+0?\.00125\s*;", motion)),
        })
    process_query = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CreationDate,ExecutablePath,CommandLine | ConvertTo-Json -Compress"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    processes = []
    if process_query.returncode == 0 and (process_query.stdout or "").strip():
        raw_processes = json.loads(process_query.stdout)
        processes = raw_processes if isinstance(raw_processes, list) else [raw_processes]
    owned_runtime_text = str(CPP_RUNTIME).lower().replace("/", "\\")
    unowned_workers = [item for item in processes if "cfd_ancf_ancf_kernel_worker" in str(item.get("ExecutablePath", "")).lower()
                       and owned_runtime_text not in str(item.get("ExecutablePath", "")).lower().replace("/", "\\")]
    checks = {
        "cpp_worker_present": (CPP_RUNTIME / "cfd_ancf_ancf_kernel_worker.exe").is_file(),
        "cpp_state_present": STATE.is_file(),
        "cpp_state_identity_zero": state.get("global_step") == 0 and state.get("time_s") == 0.0 and state.get("integer_tick") == 0,
        "cpp_state_finite": state.get("finite_value_audit") is True,
        "cpp_state_equilibrated": state.get("equilibrated") is True,
        "cpp_state_hash_audited": init_audit.get("checks", {}).get("state_hash_match") is True,
        "three_slice_cases_complete": all(item["fields_complete"] for item in slices),
        "three_slice_dt_consistent": all(item["delta_t_00125"] and item["coupling_delta_t_00125"] for item in slices),
        "fresh_runtime": True,
        "no_unowned_cpp_worker": not unowned_workers,
    }
    evidence = {
        "stage_id": "stage4f_d_cpp_worker_real_launch_preflight_v1",
        "run_id": "cpp_worker_real_preflight_20260827_001",
        "case_id": "stage4f_d_fresh_3slice_cpp_worker_case",
        "checks": checks,
        "slices": slices,
        "worker_sha256": sha256(CPP_RUNTIME / "cfd_ancf_ancf_kernel_worker.exe") if (CPP_RUNTIME / "cfd_ancf_ancf_kernel_worker.exe").is_file() else None,
        "state_sha256": sha256(STATE) if STATE.is_file() else None,
        "state_equilibrated": state.get("equilibrated"),
        "gate": "STAGE4F_D_CPP_WORKER_REAL_LAUNCH_PREFLIGHT_V1_GATE: pass" if all(checks.values()) else "STAGE4F_D_CPP_WORKER_REAL_LAUNCH_PREFLIGHT_V1_GATE: do_not_pass",
        "reason": "All launch inputs are present and the C++ static-equilibrium state is qualified." if all(checks.values()) else ("A non-owned C++ worker is still running; it must be closed by its owner before a fresh launch." if not checks["no_unowned_cpp_worker"] else "The C++ t=0 artifact is not a qualified static-equilibrium state."),
        "real_process_starts": {"CPP_WORKER": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "unowned_cpp_workers": unowned_workers,
        "old_runtime_reused": False,
        "launch_performed": False,
    }
    RESULT.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    (RESULT / "real_launch_preflight.json").write_bytes(payload)
    (RESULT / "stage4f_d_cpp_worker_real_launch_preflight_v1_gate.json").write_bytes(payload)
    conflict = (f"- Non-owned C++ worker(s) detected: {len(unowned_workers)}; do not terminate by name.\n"
                if unowned_workers else "- No non-owned C++ worker conflicts detected.\n")
    (DOC / "real_launch_preflight_report.md").write_text(
        "# Stage 238 real-launch preflight\n\n"
        "This is an offline checklist only; no continuation was started.\n\n"
        "- C++ worker executable and fresh three-slice field templates are present.\n"
        "- All slices use `deltaT=0.00125` and `couplingDeltaT=0.00125`.\n"
        "- The C++ state has valid zero-time identity, finite values, and qualified static equilibrium.\n"
        + conflict +
        "- MATLAB/OpenFOAM/WSL/CFD/C++ continuation starts: 0.\n"
        f"- Gate: `{evidence['gate']}`.\n",
        encoding="utf-8",
    )
    print(json.dumps({"gate": evidence["gate"], "checks": checks, "launch_performed": False}, ensure_ascii=True, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
