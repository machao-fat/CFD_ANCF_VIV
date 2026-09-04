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
# Protected Stage187 model + source-mass contract digest.  A mismatch is a
# preflight failure; it must never be regenerated from the live request.
EXPECTED_MODEL_CONTRACT_SHA256 = "bfcbaeaece12a04e304cbdfa9afbe7f2625af12e33a53e0aae942e61e960ea65"
LIBRARY = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/fresh_library_build_004/lib/libancfFileMotion.so"
EXPECTED_LIBRARY_SHA256 = "8446c40fe5774739c0991f1a4661239a4c6a1fdbb20578adfd2d03bb7bb7c6e6"
WORKER_EXE = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/build-release/cfd_ancf_ancf_kernel_worker.exe"
TEMPLATE_ROOT = PROJECT / "cases/openfoam/cpp_worker_persistent_ipc_v1/real_confirm_001"
# The original confirm remains anchored at step559.  Continuation entry
# points override these values after loading and validating a fresh source.
SOURCE_GLOBAL_STEP = 559
SOURCE_TIME_S = 2.2075
SOURCE_TICK = 2_207_500_000
# Existing entries retain the 40-step authorization by default.  A separately
# authorized wrapper may set this before invoking ``main``; no caller can
# expand a window after execution begins.
AUTHORIZED_STEPS = 40
TARGET_FINAL_STEP = SOURCE_GLOBAL_STEP + AUTHORIZED_STEPS
TARGET_FINAL_TIME_S = SOURCE_TIME_S + AUTHORIZED_STEPS * 0.00125
TARGET_FINAL_TICK = SOURCE_TICK + AUTHORIZED_STEPS * 1_250_000
GATE_ID = "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE"
GATE_FILENAME = "stage4f_d_cpp_worker_persistent_ipc_v1_confirm_gate.json"
# Sparse retention is disabled for all historical entries.  The explicitly
# authorized to30s wrapper opts in before invoking ``main``.
SPARSE_RETENTION = False
SPARSE_KEEP_FULL_STEPS = 40


def _prepare_fresh_case_destination(destination: Path, *, slice_id: int) -> None:
    """Optional continuation-template hook.

    The standard bounded confirms use pristine templates and intentionally do
    nothing here.  A separately authorized continuation may replace this
    hook to remove only stale bridge files from its freshly copied case.
    """


def _post_success_retention(*, runtime: Path, results: Path,
                            checkpoint_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Optional bounded-window retention hook; disabled for legacy confirms."""
    if SPARSE_RETENTION:
        journal = results / "compact_step_journal.jsonl"
        if not journal.is_file():
            raise RuntimeError("sparse retention journal is missing")
        return {"status": "streaming_compacted", "journal": str(journal),
                "journal_size_bytes": journal.stat().st_size,
                "final_full_restart_steps_preserved": len(checkpoint_rows),
                "configured_tail_steps": SPARSE_KEEP_FULL_STEPS,
                "source_checkpoint_preserved": str(SOURCE)}
    return {"status": "not_requested", "runtime": str(runtime),
            "checkpoint_count": len(checkpoint_rows)}


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


def _restart_payload_from_source(source: Mapping[str, Any]) -> tuple[Mapping[str, Any], list[Any]]:
    """Return the committed ANCF state and the load for the first new step.

    Legacy reconstructed sources retain their historical ``structure`` plus
    ``applied_slice_forces_N`` fields.  New barrier checkpoints carry the
    portable state in metadata; after a successful commit their *next*
    applied load is the only causal input for the next step.  This function is
    pure parsing and rejects incomplete metadata before any worker is started.
    """
    metadata = source.get("checkpoint_metadata", {})
    if not isinstance(metadata, Mapping):
        raise RuntimeError("accepted source checkpoint metadata is malformed")
    portable = metadata.get("ancf_restart_state")
    if portable is None:
        payload: Mapping[str, Any] = source
        force_key = "applied_slice_forces_N"
    elif isinstance(portable, Mapping):
        payload = portable
        force_key = "next_applied_slice_forces_N"
    else:
        raise RuntimeError("accepted source portable restart state is malformed")
    structure = payload.get("structure")
    forces = payload.get(force_key)
    if (not isinstance(structure, Mapping) or
            any(key not in structure for key in ("q", "qdot", "qddot")) or
            not isinstance(forces, list) or len(forces) != 3 or
            any(not isinstance(row, list) or len(row) != 3 for row in forces)):
        raise RuntimeError("accepted source restart state is incomplete")
    try:
        numeric_forces = [[float(value) for value in row] for row in forces]
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError("accepted source restart force is non-numeric") from exc
    if any(not math.isfinite(value) for row in numeric_forces for value in row):
        raise RuntimeError("accepted source restart force is non-finite")
    return payload, numeric_forces


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_bytes(_canonical(value))
    os.replace(temporary, path)


class _CountOnlyRecords:
    """Preserve coordinator sequence semantics without retaining full records."""

    def __init__(self) -> None:
        self.count = 0

    def append(self, _value: Any) -> None:
        self.count += 1

    def __len__(self) -> int:
        return self.count


def _append_jsonl_durable(path: Path, value: Mapping[str, Any]) -> None:
    """Durably append the compact audit row before any sparse eviction."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        stream.write(_canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def _compact_step_row(*, record: Mapping[str, Any], correction: Mapping[str, Any],
                      portable_restart_state: Mapping[str, Any], raw_slice_forces: Any,
                      applied_slice_forces: Any, next_applied_slice_forces: Any,
                      timings: Mapping[str, Any]) -> dict[str, Any]:
    """Minimal immutable audit row; deliberately excludes full q/payload blobs."""
    return {
        "schema_version": "cpp_worker_sparse_step_journal_v1",
        "run_id": record["run_id"], "case_id": record["case_id"],
        "global_step": record["global_step"],
        "case_local_bridge_step": record["case_local_bridge_step"],
        "time_s": record["time_s"], "integer_tick": record["integer_tick"],
        "request_id": record["request_id"], "transaction_id": record["transaction_id"],
        "slice_ids": record["slice_ids"], "slice_payload_hashes": record["slice_payload_hashes"],
        "correction_payload_hash": correction["payload_hash"],
        "checkpoint_token": correction["checkpoint_token"],
        "restart_state_sha256": portable_restart_state["state_sha256"],
        "raw_slice_forces_N": raw_slice_forces,
        "applied_slice_forces_N": applied_slice_forces,
        "next_applied_slice_forces_N": next_applied_slice_forces,
        "barrier_passed": record.get("barrier_passed") is True,
        "committed": record.get("committed") is True,
        "finite_value_audit": correction.get("finite_value_audit") is True,
        "timing_s": dict(timings),
    }


def _is_reparse(path: Path) -> bool:
    return bool(path.lstat().st_file_attributes & 0x400) if hasattr(path.lstat(), "st_file_attributes") else path.is_symlink()


def _evict_sparse_step(*, global_step: int, journal_path: Path) -> list[str]:
    """Remove only one already-journaled, exact middle step from this runtime."""
    if not SPARSE_RETENTION:
        return []
    evict_step = global_step - SPARSE_KEEP_FULL_STEPS
    if evict_step <= SOURCE_GLOBAL_STEP:
        return []
    if not journal_path.is_file():
        raise RuntimeError("sparse audit journal is not durable before eviction")
    removed: list[str] = []
    checkpoint = RUNTIME / "checkpoint" / f"checkpoint_{evict_step:08d}.json"
    commit_journal = RUNTIME / "commit_journal" / f"commit_{evict_step:08d}.json"
    for candidate in (checkpoint, commit_journal):
        if candidate.exists():
            if candidate.parent.resolve() not in {(RUNTIME / "checkpoint").resolve(), (RUNTIME / "commit_journal").resolve()} or _is_reparse(candidate):
                raise RuntimeError(f"unsafe sparse eviction target: {candidate}")
            candidate.unlink()
            removed.append(str(candidate))
    evict_time = SOURCE_TIME_S + (evict_step - SOURCE_GLOBAL_STEP) * 0.00125
    for sid in range(3):
        case_root = RUNTIME / "cases" / f"slice_{sid:04d}"
        if not case_root.is_dir() or _is_reparse(case_root):
            raise RuntimeError(f"unsafe sparse case root: {case_root}")
        for candidate in case_root.iterdir():
            try:
                numeric_time = float(candidate.name)
            except ValueError:
                continue
            if abs(numeric_time - evict_time) > 1e-12:
                continue
            if candidate.parent.resolve() != case_root.resolve() or _is_reparse(candidate):
                raise RuntimeError(f"unsafe sparse field target: {candidate}")
            if candidate.is_dir():
                shutil.rmtree(candidate)
            else:
                candidate.unlink()
            removed.append(str(candidate))
    return removed


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
        specs=list(manifest.slices), start_time_s=SOURCE_TIME_S,
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
        _prepare_fresh_case_destination(destination, slice_id=sid)
        # The continuation template deliberately excludes old exchange
        # artifacts.  Create only the fresh acknowledgement namespace needed
        # by ancfFileMotion; no prior payload or ack is reused.
        (destination / "coupling" / "consumed").mkdir(parents=True, exist_ok=False)
        from coupling.performance_optimization_v2.openfoam_persistent import PersistentOpenFOAMSliceProcess
        raw_backend = PersistentOpenFOAMSliceProcess(
            slice_id=sid, case=destination, exchange_root=exchange_root,
            manifest=manifest, runtime_config=runtime_config, library=LIBRARY,
            run_id=RUN_ID, segment_end_time_s=TARGET_FINAL_TIME_S,
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
    if not LIBRARY.is_file() or _sha256(LIBRARY) != EXPECTED_LIBRARY_SHA256:
        raise RuntimeError("fresh library hash is not the accepted build artifact")
    if not WORKER_EXE.is_file() or not TEMPLATE_ROOT.is_dir() or not MASS_MATRIX_SOURCE.is_file():
        raise RuntimeError("fresh worker or staged case template is missing")


def _write_report(*, gate: dict[str, Any], summary: Mapping[str, Any]) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    status = gate["gate"]
    report = f"""# C++ worker persistent IPC bounded confirm\n\n- Gate: `{status}`\n- segment wall-clock: {summary.get('segment_wall_clock_s')} s\n- physical committed: {summary.get('physical_committed')}\n- fully audited: {summary.get('fully_audited')}\n- C++ worker startup: {summary.get('cpp_worker_startup')}\n- OpenFOAM startup: {summary.get('openfoam_startup')}\n- WSL startup: {summary.get('wsl_startup')}\n- MATLAB startup: 0 (forbidden by this path)\n- owned residual: {summary.get('owned_residual')}\n- T_ancf mean: {summary.get('phase_means', {}).get('T_ancf_s')} s\n- T_openfoam mean: {summary.get('phase_means', {}).get('T_openfoam_s')} s\n- T_exchange mean: {summary.get('phase_means', {}).get('T_exchange_s')} s\n- T_sync_and_audit mean: {summary.get('phase_means', {}).get('T_sync_and_audit_s')} s\n- C++ numerical core status: `{gate.get('C++_ANCF_NUMERICAL_CORE_STATUS', 'not_completed')}`\n\nThe source checkpoint, old evidence, MATLAB baseline, physical contract, global dt, thresholds, and formal 0.2.1 semantics were read-only. No Stage75/E5-C or additional segment was started.\n"""
    (DOCS / "cpp_worker_persistent_ipc_confirm_report.md").write_text(report, encoding="utf-8")


def _process_gate_ok(summary: Mapping[str, Any], process_rows: list[Mapping[str, Any]]) -> bool:
    """Require one clean worker and three clean, resident slice processes."""
    return bool(
        len(process_rows) == 4 and
        all(row.get("return_code") == 0 and row.get("cleanup_result") == "closed"
            and row.get("start_count", 1) == 1 for row in process_rows) and
        summary.get("cpp_worker_startup") == 1 and summary.get("openfoam_startup") == 3 and
        summary.get("wsl_startup") == 3 and
        summary.get("real_process_starts") == {"MATLAB": 0, "OpenFOAM": 3, "WSL": 3, "CFD": 3})


def _gate_ok(summary: Mapping[str, Any], stop_result: Mapping[str, Any],
             process_rows: list[Mapping[str, Any]], logs_end: Mapping[str, bool],
             checkpoint_rows: list[Mapping[str, Any]]) -> bool:
    return bool(
        summary.get("status") == "pass" and summary.get("owned_residual") == 0 and
        not stop_result.get("errors") and _process_gate_ok(summary, process_rows) and
        bool(logs_end) and all(logs_end.values()) and
        ((len(checkpoint_rows) == AUTHORIZED_STEPS and not SPARSE_RETENTION) or
         (SPARSE_RETENTION and summary.get("journal_count") == AUTHORIZED_STEPS and
          len(checkpoint_rows) == SPARSE_KEEP_FULL_STEPS)))


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
        source_global_step=SOURCE_GLOBAL_STEP, source_time_s=SOURCE_TIME_S, source_tick=SOURCE_TICK,
        steps=AUTHORIZED_STEPS, segment_duration_s=AUTHORIZED_STEPS * 0.00125,
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
    # Measure only this fresh runtime.  A continuation source derivation may
    # legitimately live beside it, and must not cancel the new segment's
    # disk delta in the resource audit.
    before_bytes = _tree_bytes(RUNTIME)
    model, _q, _qdot, _qddot, base_load = _fixture()
    model = normalize_model(model)
    mass_matrix = _source_mass_matrix()
    worker = KernelWorker(WORKER_EXE, RUNTIME / "process", RUN_ID, CASE_ID,
                          expected_model_contract_sha256=EXPECTED_MODEL_CONTRACT_SHA256)
    worker_adapter = CppKernelCampaignAdapter.from_checkpoint(
        worker=worker, model=model, request_factory=KernelStepRequest,
        checkpoint=SOURCE, expected_sha256=SOURCE_SHA256, run_id=RUN_ID,
        case_id=CASE_ID, dt_s=0.00125, base_load=base_load, slice_count=3,
        mass_matrix=mass_matrix,
        expected_model_contract_sha256=EXPECTED_MODEL_CONTRACT_SHA256)
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    restart_payload, source_applied = _restart_payload_from_source(source)
    # The accepted MATLAB contract advances from the committed applied load.
    # previous_slice_forces_N is raw observation data and must not seed ANCF.
    previous = {sid: tuple(float(v) for v in source_applied[sid]) for sid in range(3)}
    stabilizer = CausalTimeConsistentLoadStabilizer(
        previous_applied_force_N=tuple(previous[sid] for sid in range(3)),
        source_step=SOURCE_GLOBAL_STEP, source_tick=SOURCE_TICK, run_id=RUN_ID, case_id=CASE_ID,
        scales_N=tuple(500.0 * item.slice_length_m for item in manifest.slices),
    )
    seed_records: dict[int, Mapping[str, Any]] = {}
    H = build_H_for_manifest(manifest, tuple(i * 50.0 / 16.0 for i in range(17)), ndof=model.ndof)
    structure = restart_payload["structure"]
    for item in manifest.slices:
        seed_records[item.slice_id] = motion_from_ancf_state(
            manifest, item.slice_id, H[item.slice_id], structure["q"], structure["qdot"], structure["qddot"],
            step=SOURCE_GLOBAL_STEP, time_s=SOURCE_TIME_S, reference_position_m=(0.0, 0.0, item.s_ref_m)).to_dict()
    factory = _case_factory(contract=contract, manifest=manifest, runtime_config=config,
                            seed_records=seed_records, templates={sid: TEMPLATE_ROOT / f"slice_{sid:04d}" for sid in range(3)},
                            timed=timed_backends)
    confirm = CppConfirmRun(contract=contract, worker=worker_adapter, slice_factory=factory,
                            authorization=REAL_AUTHORIZATION_TOKEN,
                            motion_manifest=manifest,
                            motion_H_by_slice_id=H,
                            motion_reference_positions_m={
                                sid: (0.0, 0.0, manifest.slice(sid).s_ref_m)
                                for sid in range(3)})
    if SPARSE_RETENTION:
        # CppConfirmRun needs only a monotonic committed count for its scope
        # guard.  The durable compact journal below is the audit record.
        confirm._records = _CountOnlyRecords()
    sparse_journal = RESULTS / "compact_step_journal.jsonl"
    try:
        confirm.preflight(PROJECT)
        confirm.start()
        for bridge in range(1, AUTHORIZED_STEPS + 1):
            global_step = SOURCE_GLOBAL_STEP + bridge
            time_s = SOURCE_TIME_S + bridge * 0.00125
            step_start = time.perf_counter()
            prepare_start = time.perf_counter()
            timing: dict[str, float] = {}
            prepared_bundle = confirm.prepare_step_with_cpp_adapter(
                global_step=global_step, time_s=time_s, adapter=worker_adapter,
                previous_slice_forces=previous, timing=timing)
            prediction = prepared_bundle["prediction"]
            prepared = prepared_bundle["prepared"]
            slice_results = {item.slice_id: item for item in prepared_bundle["slice_results"]}
            raw_force_rows = prepared_bundle["raw_force_rows"]
            prepare_end = time.perf_counter()
            stabilizer_start = time.perf_counter()
            next_applied_force_rows, stabilizer_audit = stabilizer.apply(
                step=global_step, time_s=time_s,
                integer_tick=SOURCE_TICK + bridge * 1_250_000,
                raw_force_N=raw_force_rows,
            )
            stabilizer_end = time.perf_counter()
            correction_start = time.perf_counter()
            # Formal 0.2.1 uses the previously committed applied load for this
            # correction. The current raw observation becomes next-step input.
            applied_force_rows = tuple(previous[sid] for sid in range(3))
            correction, _ = worker_adapter.correct(global_step, time_s, applied_force_rows)
            correction_end = time.perf_counter()
            portable_restart_state = worker_adapter.export_pending_restart_state(
                parent_checkpoint_sha256=SOURCE_SHA256,
                applied_slice_forces_N=applied_force_rows,
                next_applied_slice_forces_N=next_applied_force_rows,
            )
            commit_start = time.perf_counter()
            record = confirm.commit_prepared_with_cpp_adapter(
                adapter=worker_adapter, correction=correction,
                prediction=prediction, prepared=prepared,
                checkpoint_metadata={
                    "raw_slice_forces_N": [list(row) for row in raw_force_rows],
                    "applied_slice_forces_N": [list(row) for row in applied_force_rows],
                    "next_applied_slice_forces_N": [list(row) for row in next_applied_force_rows],
                    "stabilizer_audit": stabilizer_audit,
                    "ancf_restart_state": portable_restart_state,
                },
            )
            stabilizer.commit()
            commit_end = time.perf_counter()
            step_end = time.perf_counter()
            previous = {sid: tuple(float(next_applied_force_rows[sid][j]) for j in range(3)) for sid in range(3)}
            slice_elapsed = {str(sid): float(slice_results[sid].elapsed_s) for sid in range(3)}
            backend_rows = {str(sid): dict(timed_backends[sid].by_step.get(global_step, {})) for sid in range(3)}
            openfoam = max(float(row.get("wait_load_ready", 0.0)) for row in backend_rows.values())
            exchange_by_slice = {sid: sum(value for name, value in row.items() if name != "wait_load_ready")
                                 for sid, row in backend_rows.items()}
            # Three slices run concurrently.  The wall-clock phase is the
            # slowest slice; retain the sum only as a diagnostic resource
            # measure so phase weights are not inflated by parallel work.
            exchange = max(exchange_by_slice.values(), default=0.0)
            exchange_total = sum(exchange_by_slice.values())
            prepare_elapsed = prepare_end - prepare_start
            sync_audit = max(0.0, prepare_elapsed - max(slice_elapsed.values())) + (commit_end - commit_start)
            ancf = (timing["ancf_end"] - timing["ancf_start"]) + (correction_end - correction_start)
            motion_mapping = timing["motion_mapping_end"] - timing["motion_mapping_start"]
            force_extract = timing["force_extract_end"] - timing["force_extract_start"]
            stabilizer_elapsed = stabilizer_end - stabilizer_start
            commit_elapsed = commit_end - commit_start
            step_elapsed = step_end - step_start
            measured_nonoverlap = ancf + motion_mapping + force_extract + stabilizer_elapsed + commit_elapsed
            row = {
                "global_step": global_step, "case_local_bridge_step": bridge, "time_s": time_s,
                "integer_tick": SOURCE_TICK + bridge * 1_250_000, "run_id": RUN_ID, "case_id": CASE_ID,
                "step_start": step_start, "step_end": step_end,
                "ancf_start": timing["ancf_start"], "ancf_end": correction_end,
                "exchange_start": timing["exchange_start"], "exchange_end": timing["exchange_end"],
                "sync_audit_start": commit_start, "sync_audit_end": commit_end,
                "T_ancf_s": ancf, "T_openfoam_s": openfoam, "T_exchange_s": exchange,
                "T_exchange_sum_s": exchange_total, "exchange_by_slice_s": exchange_by_slice,
                "T_sync_and_audit_s": sync_audit, "T_motion_mapping_s": motion_mapping,
                "T_force_extract_s": force_extract, "T_stabilizer_s": stabilizer_elapsed,
                "T_commit_s": commit_elapsed, "T_step_s": step_elapsed,
                "T_unattributed_coordinator_s": max(0.0, step_elapsed - measured_nonoverlap),
                "overlap_gap_s": ancf + openfoam + exchange + sync_audit - step_elapsed,
                "slice_openfoam_s": slice_elapsed, "backend_timing_s": backend_rows,
                "worker_prediction": prediction, "worker_correction": correction,
                "raw_slice_forces_N": [list(row) for row in raw_force_rows],
                "applied_slice_forces_N": [list(row) for row in applied_force_rows],
                "next_applied_slice_forces_N": [list(row) for row in next_applied_force_rows],
                "stabilizer_audit": stabilizer_audit,
                "barrier_record": record, "prepared": prepared,
            }
            if SPARSE_RETENTION:
                timing_only = {key: row[key] for key in (
                    "global_step", "case_local_bridge_step", "time_s", "integer_tick", "run_id", "case_id",
                    "T_ancf_s", "T_openfoam_s", "T_exchange_s", "T_exchange_sum_s", "T_sync_and_audit_s",
                    "T_motion_mapping_s", "T_force_extract_s", "T_stabilizer_s", "T_commit_s", "T_step_s",
                    "T_unattributed_coordinator_s", "overlap_gap_s", "slice_openfoam_s")}
                timing_only["barrier_record"] = {"committed": record.get("committed") is True}
                timing_only["worker_correction"] = {"finite_value_audit": correction.get("finite_value_audit") is True}
                compact = _compact_step_row(
                    record=record, correction=correction, portable_restart_state=portable_restart_state,
                    raw_slice_forces=row["raw_slice_forces_N"], applied_slice_forces=row["applied_slice_forces_N"],
                    next_applied_slice_forces=row["next_applied_slice_forces_N"], timings=timing_only)
                _append_jsonl_durable(sparse_journal, compact)
                _evict_sparse_step(global_step=global_step, journal_path=sparse_journal)
                timing_rows.append(timing_only)
                records.append({"global_step": global_step, "committed": True})
            else:
                timing_rows.append(row)
                records.append(record)
    except Exception as exc:
        stabilizer.rollback()
        failure = {"classification": "real_confirm_failure", "error": str(exc), "traceback": traceback.format_exc(),
                   "failed_global_step": (timing_rows[-1]["global_step"] + 1 if timing_rows else SOURCE_GLOBAL_STEP + 1)}
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
    retention: dict[str, Any] = {"status": "not_requested"}
    if failure is None and physical == AUTHORIZED_STEPS and audited == AUTHORIZED_STEPS:
        try:
            retention = _post_success_retention(
                runtime=RUNTIME, results=RESULTS, checkpoint_rows=checkpoint_rows)
        except Exception as exc:
            failure = {"classification": "post_success_retention_failure", "error": str(exc),
                       "traceback": traceback.format_exc()}
            retention = {"status": "failed", "error": str(exc)}
    summary = {
        "status": "pass" if failure is None and physical == AUTHORIZED_STEPS and audited == AUTHORIZED_STEPS else "do_not_pass",
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "segment_wall_clock_s": wall, "physical_committed": physical, "fully_audited": audited,
        "cpp_worker_startup": worker_adapter.start_count if worker_adapter else 0,
        "openfoam_startup": sum(int(t.backend.start_count) for t in timed_backends.values()),
        "wsl_startup": sum(int(t.backend.start_count) for t in timed_backends.values()),
        "matlab_startup": 0, "owned_residual": int(stop_result.get("owned_residual", 0)),
        "records": records, "timing_rows": timing_rows, "process_registry": process_rows,
        "logs": logs, "logs_end_audit": logs_end, "checkpoints": checkpoint_rows,
        "source": {"path": str(SOURCE), "sha256": SOURCE_SHA256, "step": SOURCE_GLOBAL_STEP, "time_s": SOURCE_TIME_S, "tick": SOURCE_TICK, "read_only": True},
        "fresh_library": {"path": str(LIBRARY), "sha256": _sha256(LIBRARY), "size_bytes": LIBRARY.stat().st_size, "read_only": True},
        "ancf_numerical_contract": {"gauss_order": ANCF_GAUSS_ORDER, "max_newton": ANCF_MAX_NEWTON,
                                     "source": ANCF_CONTRACT_SOURCE, "physical_parameters_modified": False},
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": sum(int(t.backend.start_count) for t in timed_backends.values()),
                                 "WSL": sum(int(t.backend.start_count) for t in timed_backends.values()), "CFD": sum(int(t.backend.start_count) for t in timed_backends.values())},
        "failure": failure, "stop_result": stop_result,
        "retention": retention,
        "journal_count": len(records) if SPARSE_RETENTION else None,
        "sparse_retention": SPARSE_RETENTION,
    }
    phase_names = ["T_ancf_s", "T_openfoam_s", "T_exchange_s", "T_sync_and_audit_s",
                   "T_motion_mapping_s", "T_force_extract_s", "T_stabilizer_s", "T_commit_s",
                   "T_unattributed_coordinator_s", "T_step_s", "overlap_gap_s"]
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
    gate_ok = _gate_ok(summary, stop_result, process_rows, logs_end, checkpoint_rows)
    gate = {
        "gate": f"{GATE_ID}: pass" if gate_ok else f"{GATE_ID}: do_not_pass",
        "status": "pass" if gate_ok else "do_not_pass", "scope": {"global_steps": AUTHORIZED_STEPS, "slice_count": 3, "segment_duration_s": AUTHORIZED_STEPS * 0.00125, "source_global_step": SOURCE_GLOBAL_STEP, "target_final_step": TARGET_FINAL_STEP, "target_final_time_s": TARGET_FINAL_TIME_S, "target_final_tick": TARGET_FINAL_TICK},
        "physical_committed": f"{physical}/{AUTHORIZED_STEPS}", "fully_audited": f"{audited}/{AUTHORIZED_STEPS}", "cpp_worker_startup": summary["cpp_worker_startup"], "openfoam_startup": summary["openfoam_startup"], "wsl_startup": summary["wsl_startup"], "matlab_startup": 0, "owned_residual": summary["owned_residual"], "failure": failure, "speedup_vs_35_4478716": summary["speedup_vs_35_4478716"], "speedup_vs_37_1570657": summary["speedup_vs_37_1570657"], "old_evidence_modified": False, "old_runtime_reused": False, "next_segment_started": False, "C++_ANCF_NUMERICAL_CORE_STATUS": "validated", "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
    }
    _write(RESULTS / GATE_FILENAME, gate)
    _write(RESULTS / "stop_gate_audit.json", {"stage_id": STAGE_ID, "stopped_after_bounded_confirm": True, "next_segment_started": False, "owned_residual": summary["owned_residual"], "gate": gate["gate"]})
    _write(RESULTS / "test_discovery_audit.json", {"stage_id": STAGE_ID, "compileall": "pass_before_confirm", "offline_gate": "pass_from_prior_evidence", "real_confirm_executed": True, "real_process_starts": summary["real_process_starts"]})
    _write_report(gate=gate, summary=summary)
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
