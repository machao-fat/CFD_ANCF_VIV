"""Read-only causal audit for the immutable formal 0.05 s runtime.

This tool deliberately consumes only retained JSON/JSONL/log evidence.  It
does not launch a participant, OpenFOAM, ANCF, or preCICE, and it refuses to
overwrite a prior diagnostic result.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.implicit_rollback_audit_correlation_v1 import correlate_rollback_trace


RUNTIME = ROOT / "runtime" / "formal_three_slice_implicit_0p05s_owned_mesh_history_v1_run_001"
RESULT = ROOT / "results" / "formal_three_slice_implicit_0p05s_causal_diagnostic_v1_run_002"


def rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def log_tail_observations(path: Path) -> list[dict[str, float]]:
    """Parse force components and Co only; never infer an unrecorded coupling ID."""
    pressure = viscous = None
    section = None
    observed: list[dict[str, float]] = []
    vector = re.compile(r"^\s*(pressure|viscous)\s*:\s*\(([-+0-9.eE]+)\s+([-+0-9.eE]+)")
    courant = re.compile(r"Courant Number mean:\s*([-+0-9.eE]+)\s+max:\s*([-+0-9.eE]+)")
    time = re.compile(r"Time =\s*([-+0-9.eE]+)s")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "sum of forces:" in line:
            section = "forces"
            pressure = viscous = None
            continue
        if "sum of moments:" in line:
            section = "moments"
            continue
        match = vector.match(line)
        if match and section == "forces":
            pair = (float(match.group(2)), float(match.group(3)))
            if match.group(1) == "pressure":
                pressure = pair
            else:
                viscous = pair
            continue
        match = courant.search(line)
        if match and pressure is not None and viscous is not None:
            observed.append({"mean_Co": float(match.group(1)), "max_Co": float(match.group(2)),
                             "pressure_Fx_N": pressure[0], "viscous_Fx_N": viscous[0],
                             "total_Fx_N": pressure[0] + viscous[0]})
            continue
        match = time.search(line)
        if match and observed and "of_time_s" not in observed[-1]:
            observed[-1]["of_time_s"] = float(match.group(1))
    return observed


def main() -> int:
    if RESULT.exists() and any(RESULT.iterdir()):
        raise RuntimeError(f"refusing to overwrite {RESULT}")
    RESULT.mkdir(parents=True, exist_ok=True)
    required = [RUNTIME / "records.jsonl", RUNTIME / "implicit_iterations.jsonl",
                RUNTIME / "structure_summary.json", RUNTIME / "containment_event.json"]
    required += [RUNTIME / f"fluid_{sid:04d}_adapter_trace.jsonl" for sid in range(3)]
    if any(not path.is_file() for path in required):
        missing = [str(path) for path in required if not path.is_file()]
        raise RuntimeError(f"missing immutable input: {missing}")

    records = rows(RUNTIME / "records.jsonl")
    iterations = rows(RUNTIME / "implicit_iterations.jsonl")
    traces = {str(sid): rows(RUNTIME / f"fluid_{sid:04d}_adapter_trace.jsonl") for sid in range(3)}
    containment = json.loads((RUNTIME / "containment_event.json").read_text(encoding="utf-8"))
    summary = json.loads((RUNTIME / "structure_summary.json").read_text(encoding="utf-8"))

    record_series = []
    for row in records:
        loads = row["loads"]
        motion = row["motion"]
        record_series.append({
            "window": row["global_step"], "coupling_tau_s": row["time_s"],
            "final_iteration": row["coupling_iteration_final"],
            "raw_force_N": [load["openfoam_force_x_N"] for load in loads],
            "integrated_force_N": [load["force_x_N"] for load in loads],
            "ux_m": [item["ux_m"] for item in motion],
            "vx_mps": [item["vx_mps"] for item in motion],
        })

    force_sequence = []
    for row in iterations:
        if row.get("event") == "pre_cpp_correction":
            force_sequence.append({"window": row["window_index"], "iteration": row["iteration_index"],
                                   "coupling_tau_s": row["physical_tau_target_s"],
                                   "integrated_force_N": [force[0] for force in row["forces_N"]]})

    trace_summary: dict[str, object] = {}
    audits: dict[str, object] = {}
    for sid, trace in traces.items():
        counts: dict[str, int] = {}
        for row in trace:
            event = str(row["event"])
            counts[event] = counts.get(event, 0) + 1
        trace_summary[sid] = {"events": counts,
                              "last_final_commit": [row for row in trace if row["event"] == "FINAL_COMMIT"][-1]}
        audits[sid] = correlate_rollback_trace(trace, allow_derived_lazy=True)

    log_observations = {str(sid): log_tail_observations(RUNTIME / "logs" / f"fluid_{sid:04d}.stdout")
                        for sid in range(3)}
    result = {
        "schema_version": "formal-three-slice-causal-diagnostic-v1",
        "mode": "READ_ONLY_NO_NEW_CFD_OR_ANCF",
        "immutable_runtime": str(RUNTIME),
        "input_sha256": {path.name: sha256(path) for path in required},
        "structure": {"committed_steps": summary["committed_steps"],
                      "coupling_iterations_total": summary["coupling_iterations_total"],
                      "error": summary["error"]},
        "containment": containment,
        "committed_window_series": record_series,
        "force_values_seen_by_structure_pre_correction": force_sequence,
        "fluid_trace_transaction_summary": trace_summary,
        "owner_rollback_reanalysis_current_schema": audits,
        "fluid_log_force_and_Co_observations": log_observations,
        "audit_limits": [
            "no inference that OpenFOAM log force and mapped preCICE force are identical without a same-event identity",
            "persistent oldTime lacking value fingerprints remains not observable",
            "a fluid FINAL_COMMIT is not a Structure physical checkpoint commit",
        ],
    }
    (RESULT / "causal_diagnostic.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"result": str(RESULT / "causal_diagnostic.json"),
                      "committed_steps": summary["committed_steps"],
                      "containment_window": containment["window_index"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
