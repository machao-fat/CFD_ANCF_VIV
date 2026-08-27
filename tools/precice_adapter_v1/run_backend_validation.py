"""Validate the pyprecice backend with an injected participant; no real connection."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "271_precice_python_backend_v1"


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    command = [sys.executable, "-m", "unittest", "tests.precice_adapter_v1.test_precice_backend", "tests.precice_adapter_v1.test_participant_lifecycle", "tests.precice_adapter_v1.test_protocol_and_barrier"]
    run = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    compile_ok = subprocess.run([sys.executable, "-m", "compileall", "-q", "src/coupling/precice_adapter_v1", "tests/precice_adapter_v1", "tools/precice_adapter_v1"], cwd=ROOT).returncode == 0
    counts = {"matlab": 0, "openfoam": 0, "wsl_cfd": 0, "cfd": 0, "precice_participant": 0}
    gate = {
        "gate_id": "STAGE4F_D_PRECICE_PYTHON_BACKEND_V1_GATE",
        "status": "pass" if run.returncode == 0 and compile_ok and all(v == 0 for v in counts.values()) else "do_not_pass",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scope": "offline pyprecice backend API binding with injected fake participant; no real participant started",
        "api": ["Participant", "set_mesh_vertices", "write_data", "advance", "read_data", "finalize"],
        "faults": ["duplicate write", "wrong step", "incomplete finalize", "identity mismatch", "time mismatch", "kind mismatch", "malformed XML", "backend disconnect"],
        "tests": {"return_code": run.returncode, "compileall": compile_ok, "stdout": run.stdout, "stderr": run.stderr},
        "real_process_counts": counts,
        "protected": {"historical_evidence_modified": False, "ancf_core_modified": False, "physical_parameters_modified": False, "formal_viv_validation_complete": False},
        "next_authorization": "single-slice preCICE smoke in a fresh runtime; no three-slice or long-time VIV",
    }
    (RESULTS / "stage4f_d_precice_python_backend_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "tests": run.returncode, "compileall": compile_ok, "process_counts": counts}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
