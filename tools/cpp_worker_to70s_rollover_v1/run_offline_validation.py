"""Validate the 0 s to 70 s rolling-retention design without CFD launches."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))

from coupling.cpp_worker_to70s_rollover_v1.retention import (  # noqa: E402
    RetentionPolicy,
    RollingRetentionStore,
)

STAGE_ID = "stage4f_d_cpp_worker_to70s_rolling_retention_v1"
RUN_ID = "cpp_worker_to70s_rollover_offline_001"
CASE_ID = "cpp_worker_to70s_rollover_offline_case_001"
RESULTS = PROJECT / "results/219_cpp_worker_to70s_rollover_v1"
TARGET_STEPS = 56_000
TARGET_TIME_S = 70.0
DT_S = 0.00125


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8")


def _simulate(store: RollingRetentionStore, steps: int = 120) -> dict[str, object]:
    for sid in range(3):
        source = store.runtime / "cases" / f"slice_{sid:04d}" / "0"
        source.mkdir(parents=True, exist_ok=True)
        (source / "U").write_text("source\n", encoding="utf-8")
    for step in range(1, steps + 1):
        time_s = step * DT_S
        for sid in range(3):
            root = store.runtime / "cases" / f"slice_{sid:04d}" / format(time_s, ".12g")
            root.mkdir(parents=True, exist_ok=True)
            (root / "U").write_text(f"offline-step={step}\n", encoding="utf-8")
        commit = store.runtime / "commit_journal" / f"commit_{step:08d}.json"
        commit.parent.mkdir(parents=True, exist_ok=True)
        commit.write_text("{}\n", encoding="utf-8")
        artifact = store.runtime / "exchange" / "slice_0000" / "force_artifacts" / f"force_step{step:08d}.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("{}\n", encoding="utf-8")
        checkpoint = {
            "run_id": RUN_ID, "case_id": CASE_ID, "global_step": step,
            "time_s": time_s, "integer_tick": step * 1_250_000,
            "committed": True,
        }
        store.commit_step(
            step=step, time_s=time_s, integer_tick=step * 1_250_000,
            checkpoint=checkpoint,
            compact_row={**checkpoint},
        )
    full_times = []
    for sid in range(3):
        full_times.append(sorted(item.name for item in (store.runtime / "cases" / f"slice_{sid:04d}").iterdir()))
    checkpoints = list((store.runtime / "checkpoint").glob("checkpoint_*.json"))
    artifacts = list((store.runtime / "exchange").rglob("*step*.json"))
    return {
        "simulated_commits": steps,
        "retained_case_entries_per_slice": [len(names) for names in full_times],
        "retained_checkpoint_files": len(checkpoints),
        "retained_exchange_step_artifacts": len(artifacts),
        "latest_restart_exists": store.index.is_file(),
        "previous_restart_exists": store.previous_index.is_file(),
        "journal_lines": len(store.journal.read_text(encoding="utf-8").splitlines()),
    }


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    test_command = [sys.executable, "-m", "unittest", "-q", "tests.cpp_worker_to70s_rollover_v1.test_retention"]
    test = subprocess.run(test_command, cwd=PROJECT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)
    with tempfile.TemporaryDirectory(prefix="stage219_rollover_") as temporary:
        root = Path(temporary)
        store = RollingRetentionStore(
            runtime=root / "runtime", results=root / "results", run_id=RUN_ID, case_id=CASE_ID,
            policy=RetentionPolicy(source_step=0, source_time_s=0.0, dt_s=DT_S,
                                   keep_full_steps=40, keep_restart_checkpoints=2,
                                   min_free_bytes=0),
        )
        simulation = _simulate(store)
        runtime_bytes = sum(item.stat().st_size for item in store.runtime.rglob("*") if item.is_file())
    test_ok = test.returncode == 0
    retention_ok = (
        simulation["retained_case_entries_per_slice"] == [41, 41, 41] and
        simulation["retained_checkpoint_files"] == 40 and
        simulation["retained_exchange_step_artifacts"] == 40 and
        simulation["latest_restart_exists"] and simulation["previous_restart_exists"]
    )
    gate_ok = test_ok and retention_ok
    evidence = {
        "gate": f"STAGE4F_D_CPP_WORKER_TO70S_ROLLING_RETENTION_V1_GATE: {'pass' if gate_ok else 'do_not_pass'}",
        "status": "pass" if gate_ok else "do_not_pass", "stage_id": STAGE_ID,
        "run_id": RUN_ID, "case_id": CASE_ID,
        "target": {"source_step": 0, "source_time_s": 0.0, "target_step": TARGET_STEPS,
                    "target_time_s": TARGET_TIME_S, "target_tick": 70_000_000_000,
                    "global_dt_s": DT_S, "slice_count": 3},
        "policy": {"full_case_steps": 40, "restart_checkpoints": 2,
                   "durable_compact_journal": True, "low_disk_fail_closed": True,
                   "overwrite_latest_fields": True},
        "simulation": simulation, "simulated_runtime_bytes": runtime_bytes,
        "tests": {"command": " ".join(test_command), "return_code": test.returncode,
                  "stdout": test.stdout, "stderr": test.stderr},
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0, "old_evidence_modified": False,
        "stage75_started": False, "e5c_started": False,
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed",
                           "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
                           "LOCK_IN_CLAIM": "not_completed"},
    }
    _write(RESULTS / "rolling_retention_offline_validation.json", evidence)
    _write(RESULTS / "stage4f_d_cpp_worker_to70s_rolling_retention_v1_gate.json", evidence)
    report = """# Stage 219 rolling retention offline validation\n\n"""
    report += f"- Gate: `{evidence['gate']}`\n"
    report += "- Scope: logical source step 0 to target step 56000 (70.0 s), three slices.\n"
    report += "- Policy: durable compact journal, latest and previous restart pointers, latest 40 full case steps, exact exchange-artifact eviction.\n"
    report += f"- Simulation: {simulation['simulated_commits']} commits; case entries per slice={simulation['retained_case_entries_per_slice']}; checkpoints={simulation['retained_checkpoint_files']}; exchange step artifacts={simulation['retained_exchange_step_artifacts']}.\n"
    report += "- Real starts: MATLAB=0, OpenFOAM=0, WSL=0, CFD=0; owned residual=0.\n"
    report += "- Stage 218/old evidence remains read-only; no Stage75 or E5-C was started.\n"
    report += "- This Gate qualifies the storage design only; a new explicit authorization is required for any real 0 s to 70 s campaign.\n"
    (PROJECT / "docs/219_cpp_worker_to70s_rollover_v1").mkdir(parents=True, exist_ok=True)
    (PROJECT / "docs/219_cpp_worker_to70s_rollover_v1/report.md").write_text(report, encoding="utf-8")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
