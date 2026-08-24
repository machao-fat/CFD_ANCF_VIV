"""Restart the second real two-slice step from a committed v3 checkpoint."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import uuid
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.coupling.multi_slice_driver import (  # noqa: E402
    MotionRecord,
    MultiSliceConfig,
    MultiSliceScheduler,
    ProductionANCFAdapter,
    SliceManifest,
)
from src.coupling.multi_slice_mapping.mapping import (  # noqa: E402
    atomic_write_json,
    build_H_for_manifest,
    interpolate_ancf_state,
    motion_from_ancf_state,
    sha256_file,
)
from src.coupling.structure_runners.persistent_matlab_runner import PersistentMatlabRunner  # noqa: E402
from tests.multi_slice_integration.run_real_two_slice_closed_loop import (  # noqa: E402
    MatlabStateProvider,
    RealSliceProcess,
    parameter_consistency,
)


FLOAT_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _numbers(path: Path) -> np.ndarray:
    values = [float(item) for item in FLOAT_RE.findall(path.read_text(encoding="utf-8", errors="replace"))]
    return np.asarray(values, dtype=float)


def _relative_error(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        return float("inf")
    denominator = max(1.0, float(np.linalg.norm(left)), float(np.linalg.norm(right)))
    return float(np.linalg.norm(left - right) / denominator)


def _compare_files(left: Path, right: Path) -> dict[str, object]:
    a = _numbers(left)
    b = _numbers(right)
    return {
        "left": str(left), "right": str(right), "same_shape": a.shape == b.shape,
        "max_abs": float(np.max(np.abs(a - b))) if a.shape == b.shape and a.size else float("inf"),
        "relative_norm": _relative_error(a, b),
        "left_sha256": sha256_file(left), "right_sha256": sha256_file(right),
    }


def _case_from_summary(summary: dict[str, object], index: int) -> Path:
    return Path(str(summary["case_paths"][index])).resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--segment-summary", type=Path, required=True)
    parser.add_argument("--continuous-summary", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--restart-case0", type=Path, required=True)
    parser.add_argument("--restart-case1", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--start-time", type=float, default=0.0525)
    parser.add_argument("--runner-time-origin", type=float, default=0.05)
    parser.add_argument("--dt", type=float, default=0.0025)
    args = parser.parse_args()
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_id = f"stage4b_v3_restart_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{uuid.uuid4().hex[:8]}"
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    segment_summary = json.loads(args.segment_summary.read_text(encoding="utf-8"))
    continuous_summary = json.loads(args.continuous_summary.read_text(encoding="utf-8"))
    runtime_start_time = float(segment_summary.get("start_time_s", args.runner_time_origin))
    checkpoint = args.checkpoint.resolve()
    manifest = SliceManifest.from_mapping(json.loads((PROJECT_ROOT / "tests/multi_slice_mapping/fixtures/golden_manifest_0.2.1.json").read_text(encoding="utf-8")))
    config = MultiSliceConfig(
        case_id=manifest.case_id, dt_s=args.dt, timeout_s=30.0,
        start_time_s=runtime_start_time, manifest=manifest,
    )
    runner_config = {
        "L": 10.0, "D": 1.0, "dInner": 0.9, "nElem": 2,
        "nSlices": 2, "s_ref_m": [2.5, 7.5], "topTension_N": 1.0e7,
        "youngs_modulus_Pa": 2.07e11, "dt": args.dt,
        "newton_tolerance": 1.0e-8, "max_newton": 40,
    }
    runner = PersistentMatlabRunner(
        branch="ancf", config=runner_config, matlab_exe=r"D:\Matlab\bin\matlab.exe",
        request_dir=run_dir / "matlab_runner", timeout_s=120.0,
    )
    processes = [
        RealSliceProcess(
            slice_id=0, case=args.restart_case0.resolve(), exchange_root=run_dir / "exchange",
            manifest=manifest, runtime_config=config.runtime_config, library=args.library.resolve(), run_id=run_id,
            force_start_time_s=args.start_time,
            bridge_seed_step=1,
        ),
        RealSliceProcess(
            slice_id=1, case=args.restart_case1.resolve(), exchange_root=run_dir / "exchange",
            manifest=manifest, runtime_config=config.runtime_config, library=args.library.resolve(), run_id=run_id,
            force_start_time_s=args.start_time,
            bridge_seed_step=1,
        ),
    ]
    scheduler = None
    process_error = None
    result = None
    initial_state = None
    try:
        for process in processes:
            process.preflight(format(args.start_time + args.dt, ".12g"))
        runner.start()
        provider = MatlabStateProvider(runner)
        adapter = ProductionANCFAdapter(
            runner=runner, manifest=manifest, mesh_nodes=(0.0, 5.0, 10.0),
            state_provider=provider, runner_step_offset=1,
            runner_time_offset_s=-args.runner_time_origin,
        )
        scheduler = MultiSliceScheduler(
            config=config, exchange_root=run_dir / "exchange", structure=adapter,
            slice_processes=processes, checkpoint_root=run_dir / "checkpoints",
            case_root=processes[0].case_root,
        )
        restored = scheduler.restore_from_checkpoint(checkpoint)
        initial_state = provider()
        baseline_reference = {
            int(key): tuple(float(item) for item in value)
            for key, value in segment_summary["initial_reference_positions_m"].items()
        }
        seed_records: list[MotionRecord] = []
        for item in manifest.slices:
            seed = motion_from_ancf_state(
                manifest, item.slice_id, adapter.H_by_slice_id[item.slice_id],
                initial_state["q"], initial_state["qdot"], initial_state["qddot"],
                step=0, time_s=args.start_time,
                reference_position_m=baseline_reference[item.slice_id],
            )
            seed_records.append(seed)
            processes[item.slice_id].publish_seed(seed, start_time_s=args.start_time)
        for process in processes:
            process.start()
        for process, seed in zip(processes, seed_records):
            process.wait_seed_consumed(seed, timeout_s=config.timeout_s)
        result = scheduler.run_step(step=restored["next_step"], time_s=restored["next_time_s"])
    except Exception as exc:
        process_error = str(exc)
    finally:
        for process in processes:
            if process.process is not None:
                try:
                    process.process.wait(timeout=30.0)
                except Exception:
                    process.process.terminate()
        runner.shutdown()

    restart_checkpoints = sorted((run_dir / "checkpoints").glob("checkpoint_*.json"))
    hash_entries = []
    hash_error = None
    if scheduler is not None:
        for path in restart_checkpoints:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                scheduler.checkpoint_manager._validate_manifest(payload, require_status="committed", verify_files=True)
                hash_entries.append({"path": str(path), "step": payload["step"], "valid": True})
            except Exception as exc:
                hash_entries.append({"path": str(path), "valid": False, "error": str(exc)})
        hash_error = next((item.get("error") for item in hash_entries if not item.get("valid")), None)

    restart_max_cfl = 0.0
    restart_logs: list[str] = []
    for process in processes:
        restart_logs.append(str(process.log_path))
        if process.log_path.is_file():
            log_text = process.log_path.read_text(encoding="utf-8", errors="replace")
            values = [
                float(value) for value in re.findall(
                    r"Courant Number mean:\s+[^\s]+\s+max:\s+([-+0-9.eE]+)", log_text
                )
            ]
            restart_max_cfl = max(restart_max_cfl, max(values) if values else 0.0)

    baseline_step = next(item for item in continuous_summary.get("step_results", []) if item["step"] == 1) if continuous_summary.get("step_results") else None
    state_errors = {}
    force_error = None
    if result is not None and restart_checkpoints and baseline_step is not None:
        restart_payload = json.loads(restart_checkpoints[-1].read_text(encoding="utf-8"))
        for key in ("q", "qdot", "qddot"):
            state_errors[key] = _relative_error(
                np.asarray(baseline_step[key], dtype=float),
                np.asarray(restart_payload["structure"][key], dtype=float),
            )
        baseline_force = np.asarray(baseline_step["integrated_slice_forces_N"], dtype=float)
        restart_force = np.asarray(restart_payload["previous_slice_forces_N"], dtype=float)
        force_error = _relative_error(baseline_force, restart_force)

    field_comparison = {}
    points_max_abs = None
    motion_scale_equal = True
    if restart_checkpoints and continuous_summary.get("checkpoint_paths"):
        baseline_manifest = json.loads(Path(continuous_summary["checkpoint_paths"][-1]).read_text(encoding="utf-8"))
        restart_manifest = json.loads(restart_checkpoints[-1].read_text(encoding="utf-8"))
        names = ("U", "p", "phi", "Uf", "meshPhi", "polyMesh/points", "uniform/time")
        for sid in (0, 1):
            baseline_case = _case_from_summary(continuous_summary, sid)
            restart_case = args.restart_case0 if sid == 0 else args.restart_case1
            for name in names:
                baseline_file = baseline_case / next(
                    entry["relative_path"] for entry in baseline_manifest["slices"][sid]["time_files"]
                    if entry["relative_path"].endswith("/" + name)
                )
                restart_file = restart_case / next(
                    entry["relative_path"] for entry in restart_manifest["slices"][sid]["time_files"]
                    if entry["relative_path"].endswith("/" + name)
                )
                comparison = _compare_files(baseline_file, restart_file)
                field_comparison[f"slice_{sid:04d}/{name}"] = comparison
                if name == "polyMesh/points":
                    points_max_abs = max(points_max_abs or 0.0, float(comparison["max_abs"]))
        for sid in (0, 1):
            baseline_static = _case_from_summary(continuous_summary, sid) / "0" / "motionScale"
            restart_static = (args.restart_case0 if sid == 0 else args.restart_case1) / "0" / "motionScale"
            motion_scale_equal = motion_scale_equal and sha256_file(baseline_static) == sha256_file(restart_static)

    thresholds = {
        "time_error_s_max": 1.0e-12,
        "ancf_state_relative_error_max": 1.0e-10,
        "points_max_abs_error_m": 1.0e-10,
        "U_relative_error_max": 1.0e-8,
        "p_relative_error_max": 1.0e-8,
        "hydrodynamic_force_relative_error_max": 1.0e-6,
    }
    threshold_failures: list[str] = []
    if comparisons_time_error := abs(
        (baseline_step["time_s"] if baseline_step is not None else 0.0)
        - (result.time_s if result is not None else 0.0)
    ):
        if comparisons_time_error > thresholds["time_error_s_max"]:
            threshold_failures.append("time_error_s")
    if not state_errors or any(
        value > thresholds["ancf_state_relative_error_max"] for value in state_errors.values()
    ):
        threshold_failures.append("ancf_state_relative_error")
    if points_max_abs is None or points_max_abs > thresholds["points_max_abs_error_m"]:
        threshold_failures.append("points_max_abs_error_m")
    for field_name in ("U", "p"):
        values = [
            item["relative_norm"] for key, item in field_comparison.items()
            if key.endswith("/" + field_name)
        ]
        if not values or max(values) > thresholds[field_name + "_relative_error_max"]:
            threshold_failures.append(field_name + "_relative_error")
    if force_error is None or force_error > thresholds["hydrodynamic_force_relative_error_max"]:
        threshold_failures.append("hydrodynamic_force_relative_error")
    if not motion_scale_equal:
        threshold_failures.append("motionScale_hash")
    if result is None or process_error is not None or hash_error is not None:
        threshold_failures.append("restart_transaction")
    if any(code != 0 for code in [process.process.returncode for process in processes if process.process is not None]):
        threshold_failures.append("OpenFOAM_return_code")

    comparisons = {
        "schema_version": "stage4b-v3-real-restart-comparison",
        "run_id": run_id,
        "status": "completed" if not threshold_failures else "blocked",
        "continuous_checkpoint": str(continuous_summary.get("checkpoint_paths", [""])[-1]),
        "restart_checkpoint": str(restart_checkpoints[-1]) if restart_checkpoints else None,
        "continuous_step": 1 if baseline_step is not None else None,
        "restart_step": result.step if result is not None else None,
        "continuous_time_s": baseline_step["time_s"] if baseline_step is not None else None,
        "restart_time_s": result.time_s if result is not None else None,
        "time_error_s": abs((baseline_step["time_s"] if baseline_step is not None else 0.0) - (result.time_s if result is not None else 0.0)),
        "state_relative_errors": state_errors,
        "force_relative_error": force_error,
        "points_max_abs_error_m": points_max_abs,
        "field_comparison": field_comparison,
        "motionScale_hash_equal": motion_scale_equal,
        "thresholds": thresholds,
        "threshold_failures": threshold_failures,
        "hash_audit": hash_entries,
        "hash_audit_error": hash_error,
        "process_return_codes": [process.process.returncode if process.process is not None else None for process in processes],
        "logs": restart_logs,
        "max_cfl": restart_max_cfl,
        "parameters": parameter_consistency(manifest, dt_s=args.dt),
        "error": process_error,
    }
    atomic_write_json(run_dir / "restart_comparison.json", comparisons)
    atomic_write_json(root / "restart_comparison.json", comparisons)
    print(json.dumps(comparisons, ensure_ascii=False, sort_keys=True))
    return 0 if comparisons["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
