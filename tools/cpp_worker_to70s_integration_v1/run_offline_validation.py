"""Run Stage 220 integration simulation; never launch a real solver."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from src.coupling.cpp_worker_to70s_integration_v1.integration import OfflineThreeSliceCampaign  # noqa: E402

STAGE_ID = "stage4f_d_cpp_worker_to70s_integration_v1"
RUN_ID = "cpp_worker_to70s_integration_offline_001"
CASE_ID = "cpp_worker_to70s_integration_offline_case_001"
RESULTS = PROJECT / "results/220_cpp_worker_to70s_integration_v1"
DOCS = PROJECT / "docs/220_cpp_worker_to70s_integration_v1"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True,
                                separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "unittest", "-q",
               "tests.cpp_worker_to70s_integration_v1.test_integration"]
    test = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)
    with tempfile.TemporaryDirectory(prefix="stage220_integration_") as temporary:
        root = Path(temporary)
        campaign = OfflineThreeSliceCampaign(runtime=root / "runtime", results=root / "results",
                                              run_id=RUN_ID, case_id=CASE_ID)
        simulation = campaign.run(120)
    gate_ok = test.returncode == 0 and simulation["commit_count"] == 120 and simulation["barrier_count"] == 120 and simulation["case_entries_per_slice"] == [41, 41, 41] and simulation["checkpoint_count"] == 40 and simulation["exchange_artifact_count"] == 40 and simulation["owned_residual"] == 0
    evidence = {
        "gate": f"STAGE4F_D_CPP_WORKER_TO70S_INTEGRATION_V1_GATE: {'pass' if gate_ok else 'do_not_pass'}",
        "status": "pass" if gate_ok else "do_not_pass", "stage_id": STAGE_ID,
        "run_id": RUN_ID, "case_id": CASE_ID, "simulation": simulation,
        "test": {"command": " ".join(command), "return_code": test.returncode,
                  "stdout": test.stdout, "stderr": test.stderr},
        "scope": {"source_step": 0, "source_time_s": 0.0, "target_step": 56000,
                  "target_time_s": 70.0, "global_dt_s": 0.00125, "slice_count": 3},
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0, "old_evidence_modified": False,
        "old_runtime_reused": False, "stage75_started": False, "e5c_started": False,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed",
                           "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
                           "LOCK_IN_CLAIM": "not_completed"},
    }
    _write(RESULTS / "integration_offline_validation.json", evidence)
    _write(RESULTS / "stage4f_d_cpp_worker_to70s_integration_v1_gate.json", evidence)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "report.md").write_text(
        "# Stage 220 C++ worker to 70 s offline integration\n\n"
        f"- Gate: `{evidence['gate']}`\n"
        "- This is a 120-step three-slice simulation of the 0 s to 70 s contract; the 56,000-step target is not executed.\n"
        f"- Commits/barriers/acks: {simulation['commit_count']}/{simulation['barrier_count']}/{simulation['slice_ack_count']}.\n"
        f"- Retention: case entries per slice={simulation['case_entries_per_slice']}; checkpoints={simulation['checkpoint_count']}; exchange artifacts={simulation['exchange_artifact_count']}.\n"
        "- Mock worker/slice startup is recorded for lifecycle coverage; real MATLAB/OpenFOAM/WSL/CFD starts are all zero.\n"
        "- The integration Gate qualifies sequencing and storage only. A fresh explicit authorization is still required before a real campaign.\n",
        encoding="utf-8")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
