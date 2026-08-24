"""Minimal MATLAB worker lifecycle check before the diagnostic cases."""
from __future__ import annotations

import json
from pathlib import Path

from ..multi_slice_mapping.mapping import atomic_write_json
from ..stage4f_equilibrated_startup_v3.equilibrium import _read_manifest
from ..stage4f_three_slice_short_window_v1_repair2.runner import VariableStepRunner, _native_from_checkpoint
from .real_runner import normalize_process_record


def run(parent: Path, runtime: Path, output: Path) -> dict:
    parent = parent.resolve()
    runtime = runtime.resolve()
    output = output.resolve()
    runtime.mkdir(parents=True, exist_ok=False)
    registry = []
    runner = VariableStepRunner(runtime / "matlab", _read_manifest(), native_resume=_native_from_checkpoint(parent),
                                dt_s=0.00125, process_registry=registry)
    error = None
    try:
        runner.start()
        state = runner.state_view()
        if not all(key in state and len(state[key]) == 102 for key in ("q", "qdot", "qddot")):
            raise RuntimeError("MATLAB worker state identity is incomplete")
        runner._run("stage4f_v2_worker=1; assert(stage4f_v2_worker==1);", "worker_initialize_shutdown")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        runner.shutdown()
    rows = []
    for row in registry:
        row.setdefault("start_timestamp", row.get("creation_time_utc"))
        row.setdefault("end_timestamp", row.get("creation_time_utc"))
        row.setdefault("log_path", row.get("log"))
        row.setdefault("shutdown_method", row.get("close_method", "natural_exit"))
        row.setdefault("ownership_basis", "Popen PID plus psutil creation time and observed parent PID")
        rows.append(normalize_process_record(row))
    residual = sum(not bool(row.get("closed")) for row in registry)
    passed = error is None and bool(rows) and all(row["evidence_complete"] for row in rows) and residual == 0
    result = {"schema": "stage4f-c-v2-runtime-preflight-1.0.0", "status": "passed" if passed else "blocked",
              "matlab_worker_initialized": error is None, "records": rows, "started": len(rows),
              "closed": len(rows) - residual, "residual": residual, "error": error}
    atomic_write_json(output, result)
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.parent, args.runtime, args.output), ensure_ascii=False))
