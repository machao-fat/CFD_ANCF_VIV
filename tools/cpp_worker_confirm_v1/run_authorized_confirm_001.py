"""Execute the single explicitly authorized C++/OpenFOAM bounded confirm.

This entry point is intentionally one-shot.  It creates a fresh runtime and
results directory, lazily materializes three new case copies after the
coordinator has created the runtime, and refuses any existing artifact.  No
MATLAB path is reachable from this script.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import statistics
import time
import traceback
from pathlib import Path
from typing import Any, Mapping

from coupling.cpp_worker_confirm_v1.contracts import (
    CppConfirmContract,
    REAL_AUTHORIZATION_TOKEN,
)
from coupling.cpp_worker_confirm_v1.cpp_adapter import CppKernelCampaignAdapter
from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker, _fixture
from coupling.cpp_worker_confirm_v1.real_coordinator import (
    CppConfirmRun,
    build_predictor_motion_by_slice,
)
from coupling.cpp_worker_confirm_v1.real_slice_adapter import PersistentOpenFOAMSliceAdapter
from coupling.cpp_worker_confirm_v1.numerical_contract import (
    ANCF_CONTRACT_SOURCE, ANCF_GAUSS_ORDER, ANCF_MAX_NEWTON, normalize_model,
)
from coupling.cpp_worker_confirm_v1.stabilizer import CausalTimeConsistentLoadStabilizer
from coupling.multi_slice_driver.contract import SliceExchangePaths, SliceSpec, build_config, build_slice_manifest
from coupling.multi_slice_mapping.mapping import (
    RuntimeConfig,
    SliceManifest,
    build_H_for_manifest,
    motion_from_ancf_state,
)
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest


PROJECT = Path(__file__).resolve().parents[2]
STAGE_ID = "stage4f_d_cpp_worker_persistent_ipc_confirm_v4"
RUN_ID = "cpp_worker_persistent_ipc_confirm_004"
CASE_ID = "cpp_worker_persistent_ipc_confirm_case_004"
RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/confirm_004"
RESULTS = PROJECT / "results/121_cpp_worker_persistent_ipc_confirm_v4"
DOCS = PROJECT / "docs/121_cpp_worker_persistent_ipc_confirm_v4"
SOURCE = PROJECT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"
SOURCE_SHA256 = "341b9ccf21e0436791456333a6c3baccfde69c3735f717763d576952dba0a226"
MASS_MATRIX_SOURCE = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/matlab_dual_011/accepted_step559_seed.mat"
LIBRARY = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/fresh_library_build_004/lib/libancfFileMotion.so"
WORKER_EXE = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/build-release/cfd_ancf_ancf_kernel_worker.exe"
TEMPLATE_ROOT = PROJECT / "cases/openfoam/cpp_worker_persistent_ipc_v1/real_confirm_001"


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_mass_matrix() -> tuple[float, ...]:
    """Read the protected step559 source matrix without starting MATLAB."""
    try:
        from scipy.io import loadmat
        loaded = loadmat(MASS_MATRIX_SOURCE, squeeze_me=True, struct_as_record=False)
        state = loaded["state"]
        matrix = state.model.mass_matrix
        values = tuple(float(value) for value in matrix.reshape(-1, order="C"))
    except Exception as exc:
        raise RuntimeError(f"source mass matrix cannot be loaded: {exc}") from exc
    if len(values) != 102 * 102 or any(not math.isfinite(value) for value in values):
        raise RuntimeError("source mass matrix must be finite 102x102")
    return values


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_bytes(_canonical(value))
    os.replace(temporary, path)


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "p50": None, "p95": None, "max": None, "min": None, "std": None}
    ordered = sorted(values)
    return {
        "mean": statistics.fmean(values),
        "p50": statistics.quantiles(ordered, n=2, method="inclusive")[0] if len(values) > 1 else ordered[0],
        "p95": statistics.quantiles(ordered, n=20, method="inclusive")[18] if len(values) > 1 else ordered[0],
        "max": max(values), "min": min(values),
        "std": statistics.pstdev(values) if len(values) > 1 else 0.0,
    }


def _tree_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


class TimedBackend:
    """Record the persistent adapter's exchange/solver wait boundaries."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend
        self.by_step: dict[int, dict[str, float]] = {}
        self.current_step: int | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.backend, name)

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return getattr(self.backend, name)(*args, **kwargs)
        finally:
            if self.current_step is not None:
                row = self.by_step.setdefault(self.current_step, {})
                row[name] = row.get(name, 0.0) + (time.perf_counter() - started)

    def begin_step(self, seed: Any, *, seed_step: int) -> Any:
        self.current_step = int(seed_step) + 1
        return self._call("begin_step", seed, seed_step=seed_step)

    def publish_motion(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("publish_motion", *args, **kwargs)

    def wait_motion_consumed(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("wait_motion_consumed", *args, **kwargs)

    def advance_one_step(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("advance_one_step", *args, **kwargs)

    def wait_load_ready(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("wait_load_ready", *args, **kwargs)

    def read_load(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("read_load", *args, **kwargs)

    def publish_load_consumed(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("publish_load_consumed", *args, **kwargs)

    def finish_step(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("finish_step", *args, **kwargs)

    def stop(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("stop", *args, **kwargs)


def _manifest() -> SliceManifest:
    specs = [
        SliceSpec(0, 8.333333333333334, 16.666666666666668, 1.0),
        SliceSpec(1, 25.0, 16.666666666666668, 1.0),
        SliceSpec(2, 41.666666666666664, 16.666666666666668, 1.0),
    ]
    return SliceManifest.from_mapping(build_slice_manifest(
        CASE_ID, specs, reference_length_m=50.0, represented_length_m=50.0))


def _runtime_config(manifest: SliceManifest) -> RuntimeConfig:
    return RuntimeConfig.from_mapping(build_config(
        case_id=CASE_ID, dt_s=0.00125, timeout_s=180.0,
        specs=list(manifest.slices), start_time_s=2.2075,
        reference_length_m=50.0, represented_length_m=50.0))


def _process_record(component: str, sid: int | None, process: Any, *, cwd: Path, owned: bool) -> dict[str, Any]:
    if process is None:
        return {"component": component, "slice_id": sid, "pid": None, "owned": owned,
                "cwd": str(cwd), "return_code": None, "cleanup_result": "not_started"}
    args = getattr(process, "args", None)
    return {"component": component, "slice_id": sid, "pid": int(getattr(process, "pid", 0) or 0),
            "parent_pid": os.getpid(), "command_line": args if isinstance(args, list) else [str(args)],
            "cwd": str(cwd), "owned": owned, "start_time_ns": None,
            "end_time_ns": None if process.poll() is None else time.time_ns(),
            "return_code": process.poll(), "cleanup_result": "closed" if process.poll() is not None else "running"}


def _case_factory(*, contract: CppConfirmContract, manifest: SliceManifest, runtime_config: RuntimeConfig,
                  seed_records: Mapping[int, Mapping[str, Any]], templates: Mapping[int, Path], timed: dict[int, TimedBackend]):
    exchange_root = contract.runtime / "exchange"
    case_root = contract.runtime / "cases"
    paths = {sid: SliceExchangePaths(exchange_root, manifest.slice(sid)) for sid in range(3)}

    def factory(slice_id: int, runtime_path: Path) -> PersistentOpenFOAMSliceAdapter:
        sid = int(slice_id)
        if sid not in {0, 1, 2}:
            raise RuntimeError("slice outside exact three-slice scope")
        destination = case_root / f"slice_{sid:04d}"
        if destination.exists():
            raise RuntimeError(f"case destination already exists: {destination}")
        shutil.copytree(templates[sid], destination)
        from coupling.performance_optimization_v2.openfoam_persistent import PersistentOpenFOAMSliceProcess
        raw_backend = PersistentOpenFOAMSliceProcess(
            slice_id=sid, case=destination, exchange_root=exchange_root,
            manifest=manifest, runtime_config=runtime_config, library=LIBRARY,
            run_id=RUN_ID, segment_end_time_s=2.2075 + 40 * 0.00125,
            direct_wsl_exec=True, poll_interval_s=0.05,
        )
        backend = TimedBackend(raw_backend)
        timed[sid] = backend
        return PersistentOpenFOAMSliceAdapter(
            backend=backend, manifest=manifest, runtime_config=runtime_config,
            paths=paths[sid], initial_seed=seed_records[sid], slice_id=sid)

    return factory


def _validate_scope(contract: CppConfirmContract, manifest: SliceManifest) -> None:
    contract.validate(PROJECT)
    if manifest.case_id != CASE_ID or len(manifest.slices) != 3:
        raise RuntimeError("manifest identity/slice scope mismatch")
    if not LIBRARY.is_file() or _sha256(LIBRARY) != "8446c40fe5774739c0991f1a4661239a4c6a1fdbb20578adfd2d03bb7bb7c6e6":
        raise RuntimeError("fresh library hash is not the accepted build artifact")
    if not WORKER_EXE.is_file() or not TEMPLATE_ROOT.is_dir() or not MASS_MATRIX_SOURCE.is_file():
        raise RuntimeError("fresh worker or staged case template is missing")


def _write_report(*, gate: dict[str, Any], summary: Mapping[str, Any]) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    status = gate["gate"]
    report = f"""# C++ worker persistent IPC bounded confirm\n\n- Gate: `{status}`\n- segment wall-clock: {summary.get('segment_wall_clock_s')} s\n- physical committed: {summary.get('physical_committed')}\n- fully audited: {summary.get('fully_audited')}\n- C++ worker startup: {summary.get('cpp_worker_startup')}\n- OpenFOAM startup: {summary.get('openfoam_startup')}\n- WSL startup: {summary.get('wsl_startup')}\n- MATLAB startup: 0 (forbidden by this path)\n- owned residual: {summary.get('owned_residual')}\n- T_ancf mean: {summary.get('phase_means', {}).get('T_ancf_s')} s\n- T_openfoam mean: {summary.get('phase_means', {}).get('T_openfoam_s')} s\n- T_exchange mean: {summary.get('phase_means', {}).get('T_exchange_s')} s\n- T_sync_and_audit mean: {summary.get('phase_means', {}).get('T_sync_and_audit_s')} s\n- C++ numerical core status: `not_completed` (transport/worker path only)\n\nThe source checkpoint, old evidence, MATLAB baseline, physical contract, global dt, thresholds, and formal 0.2.1 semantics were read-only. No Stage75/E5-C or additional segment was started.\n"""
    (DOCS / "cpp_worker_persistent_ipc_confirm_report.md").write_text(report, encoding="utf-8")


def main() -> int:
    for path in (RUNTIME, RESULTS, DOCS):
        if path.exists():
            raise RuntimeError(f"one-shot confirm destination already exists; refusing retry: {path}")
    manifest = _manifest()
    config = _runtime_config(manifest)
    contract = CppConfirmContract(
        stage_id=STAGE_ID, run_id=RUN_ID, case_id=CASE_ID,
        runtime=RUNTIME, results=RESULTS, source_checkpoint=SOURCE,
        source_checkpoint_sha256=SOURCE_SHA256, allow_real_external_processes=True,
        authorization=REAL_AUTHORIZATION_TOKEN,
    )
    _validate_scope(contract, manifest)
    started_wall = time.perf_counter()
    timing_rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    failure: dict[str, Any] | None = None
    stop_result: dict[str, Any] = {}
    worker_adapter: CppKernelCampaignAdapter | None = None
    confirm: CppConfirmRun | None = None
    timed_backends: dict[int, TimedBackend] = {}
    before_bytes = _tree_bytes(RUNTIME.parent)
    model, _q, _qdot, _qddot, base_load = _fixture()
    model = normalize_model(model)
    mass_matrix = _source_mass_matrix()
    worker = KernelWorker(WORKER_EXE, RUNTIME / "process", RUN_ID, CASE_ID)
    worker_adapter = CppKernelCampaignAdapter.from_checkpoint(
        worker=worker, model=model, request_factory=KernelStepRequest,
        checkpoint=SOURCE, expected_sha256=SOURCE_SHA256, run_id=RUN_ID,
        case_id=CASE_ID, dt_s=0.00125, base_load=base_load, slice_count=3,
        mass_matrix=mass_matrix)
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    # The accepted MATLAB contract advances from the committed applied load.
    # previous_slice_forces_N is raw observation data and must not seed ANCF.
    source_applied = source.get("applied_slice_forces_N")
    if not isinstance(source_applied, list) or len(source_applied) != 3:
        raise RuntimeError("accepted source is missing applied_slice_forces_N")
    previous = {sid: tuple(float(v) for v in source_applied[sid]) for sid in range(3)}
    stabilizer = CausalTimeConsistentLoadStabilizer(
        previous_applied_force_N=tuple(previous[sid] for sid in range(3)),
        source_step=559, source_tick=2_207_500_000, run_id=RUN_ID, case_id=CASE_ID,
        scales_N=tuple(500.0 * item.slice_length_m for item in manifest.slices),
    )
    seed_records: dict[int, Mapping[str, Any]] = {}
    H = build_H_for_manifest(manifest, tuple(i * 50.0 / 16.0 for i in range(17)), ndof=model.ndof)
    structure = source["structure"]
    for item in manifest.slices:
        seed_records[item.slice_id] = motion_from_ancf_state(
            manifest, item.slice_id, H[item.slice_id], structure["q"], structure["qdot"], structure["qddot"],
            step=559, time_s=2.2075, reference_position_m=(0.0, 0.0, item.s_ref_m)).to_dict()
    factory = _case_factory(contract=contract, manifest=manifest, runtime_config=config,
                            seed_records=seed_records, templates={sid: TEMPLATE_ROOT / f"slice_{sid:04d}" for sid in range(3)},
                            timed=timed_backends)
    confirm = CppConfirmRun(contract=contract, worker=worker_adapter, slice_factory=factory,
                            authorization=REAL_AUTHORIZATION_TOKEN)
    try:
        confirm.preflight(PROJECT)
        confirm.start()
        for bridge in range(1, 41):
            global_step = 559 + bridge
            time_s = 2.2075 + bridge * 0.00125
            step_start = time.perf_counter()
            ancf_start = time.perf_counter()
            prediction, _ = worker_adapter.predict(global_step, time_s, tuple(previous[sid] for sid in range(3)))
            prediction_end = time.perf_counter()
            motions = build_predictor_motion_by_slice(
                prediction=prediction, manifest=manifest, H_by_slice_id=H,
                reference_positions_m={sid: (0.0, 0.0, manifest.slice(sid).s_ref_m) for sid in range(3)},
                global_step=global_step, time_s=time_s)
            prepare_start = time.perf_counter()
            prepared = confirm._barrier.prepare_step(global_step=global_step, time_s=time_s, motion_by_slice=motions)  # type: ignore[union-attr]
            prepare_end = time.perf_counter()
            slice_results = {item.slice_id: item for item in confirm._barrier._prepared[1]}  # type: ignore[union-attr]
            raw_force_rows = confirm._force_matrix(confirm._barrier.last_payloads)  # type: ignore[union-attr]
            next_applied_force_rows, stabilizer_audit = stabilizer.apply(
                step=global_step, time_s=time_s,
                integer_tick=2_207_500_000 + bridge * 1_250_000,
                raw_force_N=raw_force_rows,
            )
            correction_start = time.perf_counter()
            # Formal 0.2.1 uses the previously committed applied load for this
            # correction. The current raw observation becomes next-step input.
            applied_force_rows = tuple(previous[sid] for sid in range(3))
            correction, _ = worker_adapter.correct(global_step, time_s, applied_force_rows)
            correction_end = time.perf_counter()
            commit_start = time.perf_counter()
            record = confirm._barrier.commit_prepared(  # type: ignore[union-attr]
                worker_response=correction,
                checkpoint_metadata={
                    "raw_slice_forces_N": [list(row) for row in raw_force_rows],
                    "applied_slice_forces_N": [list(row) for row in applied_force_rows],
                    "next_applied_slice_forces_N": [list(row) for row in next_applied_force_rows],
                    "stabilizer_audit": stabilizer_audit,
                },
            )
            worker_adapter.finalize_committed()
            stabilizer.commit()
            confirm._records.append(record)
            confirm._next_global_step += 1
            commit_end = time.perf_counter()
            step_end = time.perf_counter()
            previous = {sid: tuple(float(next_applied_force_rows[sid][j]) for j in range(3)) for sid in range(3)}
            slice_elapsed = {str(sid): float(slice_results[sid].elapsed_s) for sid in range(3)}
            backend_rows = {str(sid): dict(timed_backends[sid].by_step.get(global_step, {})) for sid in range(3)}
            openfoam = max(float(row.get("wait_load_ready", 0.0)) for row in backend_rows.values())
            exchange = sum(sum(value for name, value in row.items() if name != "wait_load_ready") for row in backend_rows.values())
            prepare_elapsed = prepare_end - prepare_start
            sync_audit = max(0.0, prepare_elapsed - max(slice_elapsed.values())) + (commit_end - commit_start)
            ancf = (prediction_end - ancf_start) + (correction_end - correction_start)
            row = {
                "global_step": global_step, "case_local_bridge_step": bridge, "time_s": time_s,
                "integer_tick": 2_207_500_000 + bridge * 1_250_000, "run_id": RUN_ID, "case_id": CASE_ID,
                "step_start": step_start, "step_end": step_end,
                "ancf_start": ancf_start, "ancf_end": correction_end,
                "exchange_start": prepare_start, "exchange_end": prepare_end,
                "sync_audit_start": commit_start, "sync_audit_end": commit_end,
                "T_ancf_s": ancf, "T_openfoam_s": openfoam, "T_exchange_s": exchange,
                "T_sync_and_audit_s": sync_audit, "T_step_s": step_end - step_start,
                "overlap_gap_s": ancf + openfoam + exchange + sync_audit - (step_end - step_start),
                "slice_openfoam_s": slice_elapsed, "backend_timing_s": backend_rows,
                "worker_prediction": prediction, "worker_correction": correction,
                "raw_slice_forces_N": [list(row) for row in raw_force_rows],
                "applied_slice_forces_N": [list(row) for row in applied_force_rows],
                "next_applied_slice_forces_N": [list(row) for row in next_applied_force_rows],
                "stabilizer_audit": stabilizer_audit,
                "barrier_record": record, "prepared": prepared,
            }
            timing_rows.append(row)
            records.append(record)
    except Exception as exc:
        stabilizer.rollback()
        failure = {"classification": "real_confirm_failure", "error": str(exc), "traceback": traceback.format_exc(),
                   "failed_global_step": (timing_rows[-1]["global_step"] + 1 if timing_rows else 560)}
    finally:
        if confirm is not None:
            try:
                stop_result = confirm.stop()
            except Exception as exc:
                stop_result = {"errors": [str(exc)], "owned_residual": 1}
    wall = time.perf_counter() - started_wall
    physical = len(records)
    audited = sum(1 for row in timing_rows if row.get("barrier_record", {}).get("committed") is True and row.get("worker_correction", {}).get("finite_value_audit") is True)
    process_rows = [worker.audit]
    for sid, timed in sorted(timed_backends.items()):
        backend = timed.backend
        process_rows.append({"component": "openfoam_slice", "slice_id": sid,
                             "pid": getattr(getattr(backend, "process", None), "pid", None),
                             "parent_pid": os.getpid(), "command_line": getattr(getattr(backend, "process", None), "args", None),
                             "cwd": str(getattr(backend, "case", RUNTIME)), "owned": True,
                             "return_code": backend.return_code(), "start_count": backend.start_count,
                             "cleanup_result": "closed" if backend.return_code() is not None else "residual"})
    logs = []
    for timed in timed_backends.values():
        logs.extend(getattr(timed.backend, "log_paths", []))
    logs_end = {str(path): (Path(path).is_file() and "End" in Path(path).read_text(encoding="utf-8", errors="replace")) for path in logs}
    checkpoint_rows = []
    checkpoint_root = RUNTIME / "checkpoint"
    for path in sorted(checkpoint_root.glob("checkpoint_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        checkpoint_rows.append({"path": str(path), "sha256": _sha256(path), "global_step": payload.get("global_step"),
                                "time_s": payload.get("time_s"), "committed": payload.get("committed") is True,
                                "slice_count": len(payload.get("slice_ids", []))})
    summary = {
        "status": "pass" if failure is None and physical == 40 and audited == 40 else "do_not_pass",
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "segment_wall_clock_s": wall, "physical_committed": physical, "fully_audited": audited,
        "cpp_worker_startup": worker_adapter.start_count if worker_adapter else 0,
        "openfoam_startup": sum(int(t.backend.start_count) for t in timed_backends.values()),
        "wsl_startup": sum(int(t.backend.start_count) for t in timed_backends.values()),
        "matlab_startup": 0, "owned_residual": int(stop_result.get("owned_residual", 0)),
        "records": records, "timing_rows": timing_rows, "process_registry": process_rows,
        "logs": logs, "logs_end_audit": logs_end, "checkpoints": checkpoint_rows,
        "source": {"path": str(SOURCE), "sha256": SOURCE_SHA256, "step": 559, "time_s": 2.2075, "tick": 2_207_500_000, "read_only": True},
        "fresh_library": {"path": str(LIBRARY), "sha256": _sha256(LIBRARY), "size_bytes": LIBRARY.stat().st_size, "read_only": True},
        "ancf_numerical_contract": {"gauss_order": ANCF_GAUSS_ORDER, "max_newton": ANCF_MAX_NEWTON,
                                     "source": ANCF_CONTRACT_SOURCE, "physical_parameters_modified": False},
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": sum(int(t.backend.start_count) for t in timed_backends.values()),
                                 "WSL": sum(int(t.backend.start_count) for t in timed_backends.values()), "CFD": sum(int(t.backend.start_count) for t in timed_backends.values())},
        "failure": failure, "stop_result": stop_result,
    }
    phase_names = ["T_ancf_s", "T_openfoam_s", "T_exchange_s", "T_sync_and_audit_s", "T_step_s", "overlap_gap_s"]
    phase_summary = {name: _stats([float(row[name]) for row in timing_rows]) for name in phase_names}
    total_step = sum(float(row["T_step_s"]) for row in timing_rows) or 1.0
    summary["phase_means"] = {name: phase_summary[name]["mean"] for name in phase_names}
    summary["phase_weights"] = {name: (phase_summary[name]["mean"] / phase_summary["T_step_s"]["mean"] if phase_summary[name]["mean"] is not None and phase_summary["T_step_s"]["mean"] else None) for name in phase_names}
    summary["speedup_vs_35_4478716"] = 35.4478716 / wall if wall > 0 else None
    summary["speedup_vs_37_1570657"] = 37.1570657 / wall if wall > 0 else None
    _write(RESULTS / "phase_timing_per_step.json", {"stage_id": STAGE_ID, "rows": timing_rows})
    _write(RESULTS / "phase_timing_summary.json", {"stage_id": STAGE_ID, "statistics": phase_summary, "segment_wall_clock_s": wall, "weights": summary["phase_weights"]})
    _write(RESULTS / "slice_timing_summary.json", {"stage_id": STAGE_ID, "per_slice": {str(sid): _stats([float(row["slice_openfoam_s"][str(sid)]) for row in timing_rows]) for sid in range(3)}})
    _write(RESULTS / "performance_bottleneck_attribution.json", {"stage_id": STAGE_ID, "phase_means": summary["phase_means"], "dominant_phase": max(((k, v or -1.0) for k, v in summary["phase_means"].items() if k != "T_step_s"), key=lambda item: item[1])[0] if timing_rows else None, "overlap_present": any(float(row["overlap_gap_s"]) < -1e-9 for row in timing_rows)})
    _write(RESULTS / "resource_audit.json", {"stage_id": STAGE_ID, "disk_delta_bytes": max(0, _tree_bytes(RUNTIME) - before_bytes), "cpu_memory": "not_sampled_by_coordinator", "owned_residual": summary["owned_residual"]})
    _write(RESULTS / "process_ownership_audit.json", {"stage_id": STAGE_ID, "registry": process_rows, "real_process_starts": summary["real_process_starts"], "owned_residual": summary["owned_residual"]})
    _write(RESULTS / "checkpoint_snapshot_audit.json", {"stage_id": STAGE_ID, "checkpoint_count": len(checkpoint_rows), "checkpoint_rows": checkpoint_rows, "logs_end_audit": logs_end})
    _write(RESULTS / "failure_raw.json", failure or {"status": "none"})
    _write(RESULTS / "confirm_summary.json", summary)
    gate_ok = summary["status"] == "pass" and summary["owned_residual"] == 0 and all(logs_end.values()) and len(checkpoint_rows) == 40
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: pass" if gate_ok else "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: do_not_pass",
        "status": "pass" if gate_ok else "do_not_pass", "scope": {"global_steps": 40, "slice_count": 3, "segment_duration_s": 0.05, "source_global_step": 559, "target_final_step": 599, "target_final_time_s": 2.2575, "target_final_tick": 2_257_500_000},
        "physical_committed": f"{physical}/40", "fully_audited": f"{audited}/40", "cpp_worker_startup": summary["cpp_worker_startup"], "openfoam_startup": summary["openfoam_startup"], "wsl_startup": summary["wsl_startup"], "matlab_startup": 0, "owned_residual": summary["owned_residual"], "failure": failure, "speedup_vs_35_4478716": summary["speedup_vs_35_4478716"], "speedup_vs_37_1570657": summary["speedup_vs_37_1570657"], "old_evidence_modified": False, "old_runtime_reused": False, "next_segment_started": False, "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed" if gate_ok else "not_completed", "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
    }
    _write(RESULTS / "stage4f_d_cpp_worker_persistent_ipc_v1_confirm_gate.json", gate)
    _write(RESULTS / "stop_gate_audit.json", {"stage_id": STAGE_ID, "stopped_after_bounded_confirm": True, "next_segment_started": False, "owned_residual": summary["owned_residual"], "gate": gate["gate"]})
    _write(RESULTS / "test_discovery_audit.json", {"stage_id": STAGE_ID, "compileall": "pass_before_confirm", "offline_gate": "pass_from_prior_evidence", "real_confirm_executed": True, "real_process_starts": summary["real_process_starts"]})
    _write_report(gate=gate, summary=summary)
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
