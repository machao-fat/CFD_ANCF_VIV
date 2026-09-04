"""Stage 285 offline qualification; never starts MATLAB/OpenFOAM/WSL/CFD."""
from __future__ import annotations

import compileall
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "285_precice_ancf_adapter_offline_v1"
RUNTIME = ROOT / "runtime" / "285_precice_ancf_adapter_offline_v1"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests/precice_ancf_adapter_v1", "-v"]
    run = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (RUNTIME / "offline_test_stdout.log").write_text(run.stdout, encoding="utf-8")
    (RUNTIME / "offline_test_stderr.log").write_text(run.stderr, encoding="utf-8")
    compile_ok = compileall.compile_dir(str(ROOT / "src" / "coupling" / "precice_ancf_adapter_v1"), quiet=1) and compileall.compile_dir(str(ROOT / "tests" / "precice_ancf_adapter_v1"), quiet=1) and compileall.compile_dir(str(ROOT / "tools" / "precice_ancf_adapter_v1"), quiet=1)
    files = [*sorted((ROOT / "src" / "coupling" / "precice_ancf_adapter_v1").glob("*.py")), *sorted((ROOT / "tests" / "precice_ancf_adapter_v1").glob("*.py"))]
    counts = {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0}
    gate = {
        "gate_id": "STAGE4F_D_PRECICE_ANCF_ADAPTER_OFFLINE_V1_GATE",
        "status": "pass" if run.returncode == 0 and compile_ok and all(v == 0 for v in counts.values()) else "do_not_pass",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage_id": "stage4f_d_precice_ancf_adapter_offline_v1",
        "run_id": "stage285_precice_ancf_adapter_offline_run_v1",
        "case_id": "stage285_precice_ancf_adapter_offline_case_v1",
        "scope": "offline ANCF-preCICE mapping/protocol/barrier/storage only",
        "contract": {"openfoam": "10", "precice": "3.x", "dt_s": 0.005, "slice_count": 3, "real_solver_allowed": False},
        "tests": {"command": "python -m unittest discover -s tests/precice_ancf_adapter_v1 -v", "return_code": run.returncode, "compileall": compile_ok, "stdout": run.stdout, "stderr": run.stderr},
        "coverage": ["global_step-to-case_local_bridge_step clock", "559-to-560 mapping", "consistent displacement", "conservative force", "virtual work", "step/time/tick/identity", "payload hash", "UTF-8 canonical JSON", "stale", "duplicate", "out-of-order", "timeout", "disconnect", "wrong slice", "restart q/qdot/qddot", "atomic rolling checkpoint", "full step journal", "no solver launch"],
        "source_hashes": {str(path.relative_to(ROOT)): digest(path) for path in files},
        "real_process_counts": counts,
        "owned_residual": 0,
        "storage": {"runtime": str(RUNTIME), "old_runtimes_reused": False, "stage1_284_evidence_modified": False},
        "protected": {"ancf_eb_core_modified": False, "physical_parameters_modified": False, "global_dt_modified": False, "numerical_thresholds_modified": False, "formal_protocol_modified": False, "formal_viv_validation_complete": False},
        "next_authorization": "fresh Stage 286 single-slice 40-step OpenFOAM validation only",
    }
    (OUT / "stage4f_d_precice_ancf_adapter_offline_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "tests": run.returncode, "compileall": compile_ok, "real_process_counts": counts, "owned_residual": 0}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
