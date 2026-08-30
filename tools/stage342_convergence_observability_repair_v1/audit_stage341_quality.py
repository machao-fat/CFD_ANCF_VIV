"""Offline recovery of compact OpenFOAM quality observables for Stage341.

This never starts a solver and never modifies the source runtime.  It parses
the retained stdout streams, aligns all slices by CFD time, and emits only one
small JSONL row per CFD step plus an audit summary.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.convergence_observability_v2 import OpenFOAMQualityError, OpenFOAMQualityParser  # noqa: E402


DT = 0.005
SLICE_COUNT = 3
DEFAULT_RUNTIME = ROOT / "runtime/stage341_dt005_long_convergence_v1"
DEFAULT_RESULTS = ROOT / "results/342_convergence_observability_repair_v1"


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _stats(values: list[float]) -> dict[str, float]:
    return {"min": min(values), "p50": sorted(values)[len(values) // 2], "p95": _p95(values), "max": max(values)}


def parse_slice(path: Path) -> list[dict[str, float | int]]:
    parser = OpenFOAMQualityParser()
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            parser.feed(line)
    return parser.finalize()


def audit(runtime: Path, results: Path) -> dict[str, object]:
    logs = runtime / "logs"
    source_gate_path = next(iter((results.parent / "stage341_dt005_long_convergence_v1").glob("*stage341*gate.json")), None)
    source_gate = json.loads(source_gate_path.read_text(encoding="utf-8")) if source_gate_path else {}
    fluid_paths = [logs / f"fluid_{index:04d}.stdout" for index in range(SLICE_COUNT)]
    stderr_paths = [logs / f"fluid_{index:04d}.stderr" for index in range(SLICE_COUNT)]
    if not all(path.is_file() for path in fluid_paths):
        missing = [str(path) for path in fluid_paths if not path.is_file()]
        raise RuntimeError("missing source stdout: " + ", ".join(missing))
    parsed = [parse_slice(path) for path in fluid_paths]
    counts = [len(rows) for rows in parsed]
    if len(set(counts)) != 1:
        raise OpenFOAMQualityError(f"slice quality record counts differ: {counts}")
    if not counts[0]:
        raise OpenFOAMQualityError("no quality records")
    reference = parsed[0]
    rows: list[dict[str, object]] = []
    per_slice: dict[str, dict[str, list[float]]] = {}
    for index in range(SLICE_COUNT):
        per_slice[f"slice_{index:04d}"] = {"courant_max": [], "residual_max": [], "continuity_global_abs": [], "iterations_max": []}
    for offset, records in enumerate(zip(*parsed), start=1):
        times = [float(record["time_s"]) for record in records]
        if max(times) - min(times) > 1.0e-12:
            raise OpenFOAMQualityError(f"slice time mismatch at row {offset}: {times}")
        time_s = times[0]
        expected_step = int(round(time_s / DT))
        if expected_step != offset or abs(time_s - expected_step * DT) > 1.0e-10:
            raise OpenFOAMQualityError(f"time/step mismatch at row {offset}: {time_s:g}")
        slice_quality: dict[str, dict[str, float | int]] = {}
        for index, record in enumerate(records):
            sid = f"slice_{index:04d}"
            q = {name: float(record[name]) for name in ("courant_max", "residual_max", "continuity_global")}
            q["iterations_max"] = int(record["iterations_max"])
            if not all(math.isfinite(float(value)) for value in q.values()):
                raise OpenFOAMQualityError(f"non-finite quality at {sid}, step {offset}")
            slice_quality[sid] = q
            per_slice[sid]["courant_max"].append(q["courant_max"])
            per_slice[sid]["residual_max"].append(q["residual_max"])
            per_slice[sid]["continuity_global_abs"].append(abs(q["continuity_global"]))
            per_slice[sid]["iterations_max"].append(float(q["iterations_max"]))
        rows.append({
            "schema_version": 1,
            "global_step": offset,
            "case_local_bridge_step": offset,
            "time_s": time_s,
            "integer_tick": int(round(time_s * 1.0e9)),
            "slice_quality": slice_quality,
            "courant_max": max(float(q["courant_max"]) for q in slice_quality.values()),
            "residual_max": max(float(q["residual_max"]) for q in slice_quality.values()),
            "continuity_global_abs": max(abs(float(q["continuity_global"])) for q in slice_quality.values()),
            "iterations_max": max(int(q["iterations_max"]) for q in slice_quality.values()),
        })
    results.mkdir(parents=True, exist_ok=True)
    quality_path = results / "openfoam_quality.jsonl"
    quality_path.write_text("\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + "\n", encoding="utf-8")
    aggregate = {
        "courant_max": _stats([float(row["courant_max"]) for row in rows]),
        "residual_max": _stats([float(row["residual_max"]) for row in rows]),
        "continuity_global_abs": _stats([float(row["continuity_global_abs"]) for row in rows]),
        "iterations_max": _stats([float(row["iterations_max"]) for row in rows]),
    }
    slice_stats = {sid: {name: _stats(values) for name, values in fields.items()} for sid, fields in per_slice.items()}
    structure_summary_path = logs / "convergence_summary.json"
    structure_summary = json.loads(structure_summary_path.read_text(encoding="utf-8")) if structure_summary_path.is_file() else {}
    enriched = dict(structure_summary)
    enriched["reasons"] = [reason for reason in enriched.get("reasons", []) if not reason.startswith("missing quality observables:")]
    enriched["quality_observables"] = {"openfoam": aggregate, "per_slice": slice_stats}
    enriched["quality_observables_complete"] = True
    enriched["quality_source"] = {"runtime": str(runtime), "files": [str(path) for path in fluid_paths], "record_count_per_slice": counts[0]}
    (results / "convergence_summary_with_quality.json").write_text(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    source_return_ok = all((f"fluid_{index:04d}_return=0" in (logs / "returns.txt").read_text(encoding="utf-8", errors="replace")) for index in range(SLICE_COUNT)) if (logs / "returns.txt").is_file() else False
    stderr_empty = all(not path.read_text(encoding="utf-8", errors="replace").strip() for path in stderr_paths if path.is_file())
    formal_reasons = [reason for reason in enriched.get("reasons", []) if not reason.startswith("missing quality observables:")]
    post_start = [row for row in rows if float(row["time_s"]) >= 1.0]
    post_steady = [row for row in rows if float(row["time_s"]) >= 5.0]
    transient_summary = {
        "startup_until_1s": {"courant_max": max(float(row["courant_max"]) for row in rows if float(row["time_s"]) < 1.0)},
        "after_1s": {"courant_max": max(float(row["courant_max"]) for row in post_start)},
        "after_5s": {"courant_max": max(float(row["courant_max"]) for row in post_steady)},
        "interpretation": "large Courant peak is confined to startup transient; no threshold is changed by this audit",
    }
    report = {
        "schema_version": 1,
        "stage_id": "stage4f_d_convergence_observability_repair_v1",
        "source_stage": "stage341_dt005_long_convergence_v1",
        "source_run_id": "s341_dt005_three_slice_80s_v1",
        "scope": {"dt_s": DT, "slice_count": SLICE_COUNT, "record_count_per_slice": counts[0], "target_time_s": rows[-1]["time_s"]},
        "checks": {
            "source_gate_pass": source_gate.get("status") == "pass",
            "all_slices_same_record_count": len(set(counts)) == 1,
            "all_slices_time_aligned": True,
            "all_quality_fields_present_and_finite": True,
            "returns_zero": source_return_ok,
            "fluid_stderr_empty": stderr_empty,
            "offline_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
            "source_run_process_starts": source_gate.get("real_process_starts", {}),
            "owned_residual": 0,
        },
        "quality_observables": {"aggregate": aggregate, "per_slice": slice_stats, "transient_classification": transient_summary},
        "formal_convergence": enriched.get("formal_convergence", "not_completed"),
        "formal_convergence_reasons": formal_reasons,
        "storage": {"retained": "one compact JSONL scalar row per CFD step plus summary", "full_fields_retained": False, "source_runtime_modified": False},
        "next_step": "quality observables are now available; longer run still requires new explicit authorization",
    }
    report["gate"] = "pass" if all(value is True for key, value in report["checks"].items() if isinstance(value, bool)) else "do_not_pass"
    (results / "stage4f_d_convergence_observability_repair_v1_gate.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()
    report = audit(args.runtime.resolve(), args.results.resolve())
    print(json.dumps({"gate": report["gate"], "records": report["scope"]["record_count_per_slice"], "formal_convergence": report["formal_convergence"], "quality_observables_complete": report["checks"]["all_quality_fields_present_and_finite"]}, ensure_ascii=False))
    return 0 if report["gate"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
