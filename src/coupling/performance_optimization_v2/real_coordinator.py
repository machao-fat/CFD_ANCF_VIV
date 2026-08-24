"""User-session owned coordinator for bounded performance measurements.

This module is intentionally the only real benchmark entry point for Stage95+.
It reuses the accepted Stage75 formal engine and stabilizer, while selecting
process-lifecycle and scheduling optimizations through an explicit contract.
The coordinator is launched by the user's SessionId=1 runner; it is never
started directly by Codex and never expands the contract scope.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import concurrent.futures
from pathlib import Path
from typing import Any, Callable, Mapping

from .audit import BatchAuditWriter, resource_snapshot
from .contracts import FACTORS, ContractError, contract_hash, validate_serialized_contract
from .matlab_persistent import PersistentMatlabRunner


class RealCoordinatorError(RuntimeError):
    """A bounded benchmark failed and the runtime is terminal."""


_APPLICATIONSERVICE_5001_PATTERNS = (
    re.compile(r"application\s*service[^\r\n]{0,160}\b5001\b", re.IGNORECASE),
    re.compile(r"\b5001\b[^\r\n]{0,160}application\s*service", re.IGNORECASE),
    re.compile(r"(?:matlab|mathworks)[^\r\n]{0,160}\b5001\b", re.IGNORECASE),
    re.compile(r"\b5001\b[^\r\n]{0,160}(?:matlab|mathworks)", re.IGNORECASE),
)


def detect_applicationservice_5001(texts: list[str] | tuple[str, ...]) -> bool:
    """Return true only for explicit MATLAB/ApplicationService 5001 evidence."""
    return any(pattern.search(text) for text in texts for pattern in _APPLICATIONSERVICE_5001_PATTERNS)


def _failure_evidence_texts(runtime: Path, error: str) -> list[str]:
    texts = [str(error)]
    log_root = runtime / "logs"
    if not log_root.is_dir():
        return texts
    for path in log_root.rglob("*"):
        if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            continue
        if path.suffix.lower() not in {".log", ".txt", ".stdout", ".stderr", ".json"}:
            continue
        try:
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return texts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class _PersistentMatlabAdapter(PersistentMatlabRunner):
    """Adapter with the legacy campaign runner's interface."""

    def __init__(self, *, work_dir: Path, runtime: Path, manifest: Any, run_id: str, case_id: str,
                 source_global_step: int, source_time_s: float, source_tick: int,
                 native_resume: Path, dt_s: float, process_registry: list[dict[str, Any]],
                 in_memory_state: bool = False, start_hook: Callable[[], None] | None = None) -> None:
        super().__init__(work_dir=work_dir, runtime=runtime, manifest=manifest, run_id=run_id,
                         case_id=case_id, source_global_step=source_global_step,
                         source_time_s=source_time_s, source_tick=source_tick,
                         native_resume=native_resume, dt_s=dt_s, in_memory_state=in_memory_state)
        self.process_registry = process_registry
        self._start_hook = start_hook

    def start(self) -> None:
        if self._start_hook is not None:
            self._start_hook()
            self._start_hook = None
        super().start()


class _TimedEngine:
    """Proxy that records per-step phase timings without changing engine data."""

    def __init__(self, engine: Any, *, phase: dict[int, dict[str, float]], lock: threading.Lock,
                 phase_recorder: Any | None = None) -> None:
        self._engine = engine
        self._phase = phase
        self._lock = lock
        self._phase_recorder = phase_recorder

    def __getattr__(self, name: str) -> Any:
        return getattr(self._engine, name)

    def __call__(self, step: int, target_time_s: float) -> Mapping[str, Any]:
        if self._phase_recorder is not None:
            self._phase_recorder.begin_step(int(step), float(target_time_s))
        started = time.perf_counter()
        completed = False
        try:
            row = self._engine(step, target_time_s)
            completed = True
            if self._phase_recorder is not None:
                self._phase_recorder.sync_audit_end(int(step))
            return row
        finally:
            elapsed = time.perf_counter() - started
            with self._lock:
                record = self._phase.setdefault(int(step), {})
                record["total"] = elapsed
            if self._phase_recorder is not None:
                self._phase_recorder.end_step(int(step))


def _timed_method(obj: Any, method_name: str, phase_name: str, phase: dict[int, dict[str, float]], lock: threading.Lock) -> None:
    original = getattr(obj, method_name, None)
    if original is None or getattr(original, "_stage95_timed", False):
        return

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        step_value: int | None = kwargs.get("step")
        if step_value is None and args:
            candidate = args[0]
            step_value = int(getattr(candidate, "step", candidate)) if isinstance(candidate, (int,)) or hasattr(candidate, "step") else None
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            if step_value is not None:
                with lock:
                    row = phase.setdefault(int(step_value), {})
                    row[phase_name] = row.get(phase_name, 0.0) + (time.perf_counter() - started)

    wrapped._stage95_timed = True  # type: ignore[attr-defined]
    setattr(obj, method_name, wrapped)


def _instrument_engine(engine: Any, phase: dict[int, dict[str, float]], lock: threading.Lock) -> None:
    _timed_method(engine.runner, "predict", "matlab", phase, lock)
    _timed_method(engine.runner, "correct", "matlab", phase, lock)
    for process in engine.processes:
        _timed_method(process, "publish_motion", "wsl", phase, lock)
        _timed_method(process, "wait_motion_consumed", "ipc", phase, lock)
        _timed_method(process, "advance_one_step", "openfoam", phase, lock)
        _timed_method(process, "wait_load_ready", "openfoam", phase, lock)
        _timed_method(process, "read_load", "openfoam", phase, lock)
        _timed_method(process, "publish_load_consumed", "ipc", phase, lock)


def _method_step(args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> int | None:
    candidate = kwargs.get("step")
    if candidate is None and args:
        candidate = args[0]
    if isinstance(candidate, Mapping):
        candidate = candidate.get("step")
    elif hasattr(candidate, "step"):
        candidate = getattr(candidate, "step")
    if candidate is None:
        return None
    try:
        return int(candidate)
    except (TypeError, ValueError):
        return None


def _instrument_phase_engine(engine: Any, recorder: Any) -> None:
    """Attach the independent phase-timing adapter to one fresh engine.

    The adapter observes existing method boundaries only.  It does not alter
    solver inputs, scheduler state transitions, or checkpoint semantics.
    """
    def wrap(obj: Any, name: str, event: str) -> None:
        original = getattr(obj, name, None)
        if original is None or getattr(original, "_phase_timed", False):
            return
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            step = _method_step(args, kwargs)
            sid = getattr(obj, "slice_id", None)
            if step is not None:
                if event == "ancf_start": recorder.ancf_start(step)
                elif event == "exchange_start": recorder.exchange_start(step)
                elif event == "openfoam_start": recorder.openfoam_start(step, int(sid))
            try:
                return original(*args, **kwargs)
            finally:
                if step is not None:
                    if event == "ancf_end": recorder.ancf_end(step)
                    elif event == "exchange_end": recorder.exchange_end(step)
                    elif event == "openfoam_end": recorder.openfoam_end(step, int(sid))
        wrapped._phase_timed = True  # type: ignore[attr-defined]
        setattr(obj, name, wrapped)

    wrap(engine.runner, "predict", "ancf_start")
    wrap(engine.runner, "correct", "ancf_end")
    for process in engine.processes:
        wrap(process, "publish_motion", "exchange_start")
        wrap(process, "advance_one_step", "openfoam_start")
        wrap(process, "read_load", "openfoam_end")
        wrap(process, "publish_load_consumed", "exchange_end")


def _start_matlab(contract: Mapping[str, Any], runtime: Path) -> tuple[subprocess.Popen[Any], dict[str, Any], Any]:
    executable = Path(str(contract["matlab_executable"])).resolve()
    if not executable.is_file():
        raise RealCoordinatorError(f"MATLAB executable missing: {executable}")
    batch = contract.get("matlab_batch_command")
    if not batch:
        raise RealCoordinatorError("persistent MATLAB requires matlab_batch_command")
    log_path = runtime / "logs" / "matlab_persistent.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = log_path.open("w", encoding="utf-8")
    env = dict(os.environ)
    for name in ("TEMP", "TMP", "TMPDIR", "PREFDIR"):
        env[name] = str(runtime / name.lower())
    started_ns = time.time_ns()
    process = subprocess.Popen([str(executable), "-batch", str(batch)], cwd=str(runtime), env=env,
                               stdout=stream, stderr=subprocess.STDOUT)
    audit = {"component": "matlab_persistent_worker", "pid": int(process.pid),
             "creation_time_ns": started_ns, "parent_pid": os.getpid(),
             "command_line": [str(executable), "-batch", str(batch)], "cwd": str(runtime),
             "executable": str(executable), "start_time_ns": started_ns,
             "owned": True, "cleanup_result": "open", "log": str(log_path)}
    probe_path = runtime / "worker_environment_probe.json"
    deadline = time.monotonic() + 90.0
    probe: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        if probe_path.is_file():
            try:
                candidate = json.loads(probe_path.read_text(encoding="utf-8"))
                if isinstance(candidate, dict):
                    probe = candidate
                    break
            except (OSError, UnicodeError, ValueError, TypeError):
                pass
        if process.poll() is not None:
            break
        time.sleep(0.05)
    if probe is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=15)
        stream.close()
        raise RealCoordinatorError("MATLAB worker environment probe is missing")
    if (str(probe.get("release")) != "2021b" or str(probe.get("architecture")) != "win64"
            or int(probe.get("license", 0)) != 1):
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=15)
        stream.close()
        raise RealCoordinatorError(f"MATLAB worker environment probe failed: {probe}")
    runtime_drive = runtime.drive.upper()
    for name in ("TEMP", "TMP", "TMPDIR", "PREFDIR"):
        value = str(probe.get(name, ""))
        if not value or not Path(value).resolve().drive.upper() == runtime_drive:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=15)
            stream.close()
            raise RealCoordinatorError(f"MATLAB {name} is outside benchmark runtime: {value}")
    audit["environment_probe"] = probe
    return process, audit, stream


def submit_matlab_start(contract: Mapping[str, Any], runtime: Path) -> tuple[
    concurrent.futures.ThreadPoolExecutor, concurrent.futures.Future[Any]
]:
    """Submit the one owned MATLAB startup without blocking case preparation.

    The caller must resolve the future before the worker's initialize
    transaction.  Keeping submission in a small testable helper makes the
    overlap explicit and prevents accidental per-step worker creation.
    """
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="stage96-matlab-start"
    )
    return executor, executor.submit(_start_matlab, contract, runtime)


def _close_matlab(process: subprocess.Popen[Any], audit: dict[str, Any], stream: Any, runtime: Path, run_id: str) -> None:
    stop_path = runtime / "stop.request"
    _json(stop_path, {"run_id": run_id, "request_id": f"stop_{time.time_ns()}"})
    try:
        process.wait(timeout=45)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
    finally:
        code = process.returncode
        audit.update({"end_time_ns": time.time_ns(), "return_code": code,
                      "cleanup_result": "closed" if code == 0 else "closed_nonzero"})
        stream.close()


def _contract_source(contract: Mapping[str, Any]) -> tuple[Path, dict[str, Any], Path]:
    source = Path(str(contract["source_checkpoint"])).resolve()
    if not source.is_file():
        raise RealCoordinatorError(f"source checkpoint missing: {source}")
    expected_sha = str(contract.get("source_checkpoint_sha256") or "")
    if not expected_sha or _sha256(source) != expected_sha:
        raise RealCoordinatorError("source checkpoint SHA-256 is missing or mismatched")
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    required = ("step", "time_s", "time_tick", "status", "structure")
    if any(item not in payload for item in required) or payload["status"] != "committed":
        raise RealCoordinatorError("source checkpoint is not an accepted committed checkpoint")
    if int(payload["step"]) != int(contract["source_global_step"]):
        raise RealCoordinatorError("source step mismatch")
    if int(payload["time_tick"]) != int(contract["source_tick"]):
        raise RealCoordinatorError("source tick mismatch")
    if abs(float(payload["time_s"]) - float(contract["source_time_s"])) > 1e-12:
        raise RealCoordinatorError("source time mismatch")
    source_case_root = source.parent.parent / "cases"
    native = source.parent / str(payload["structure"].get("runner_checkpoint_relative_path", ""))
    if not native.is_file():
        raise RealCoordinatorError(f"native ANCF source missing: {native}")
    native_sha = str(payload["structure"].get("runner_checkpoint_sha256", ""))
    if not native_sha or _sha256(native) != native_sha:
        raise RealCoordinatorError("native ANCF source hash mismatch")
    return source, payload, native


def run_contract(contract_path: Path) -> dict[str, Any]:
    project_root = Path(__file__).resolve().parents[3]
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    validate_serialized_contract(contract, project_root)
    label = str(contract.get("configuration_label", ""))
    launch_mode = str(os.environ.get("CFD_ANCF_LAUNCH_MODE", "codex_direct"))
    if launch_mode not in {"codex_direct", "user_session_runner"}:
        raise RealCoordinatorError(f"unsupported launch mode: {launch_mode}")
    factors = set(str(item) for item in contract.get("factors", []))
    if label == "FINAL":
        factors = set(FACTORS)
    if label not in {"B", "M", "O", "P", "I", "A", "T", "D", "M+O", "M+P", "M+O+P", "M+O+P+A", "M+O+P+I", "M+O+P+I+A", "FINAL"}:
        raise RealCoordinatorError(f"unsupported benchmark label: {label}")
    # The current ancfFileMotion production bridge is still file-based.  Do
    # not run an I-labelled benchmark through that bridge and call it
    # persistent IPC: an unimplemented optimization factor must fail closed
    # before any MATLAB, WSL, or OpenFOAM process is started.
    if "I" in factors:
        raise RealCoordinatorError(
            "persistent IPC factor is unavailable: legacy file bridge is unchanged; "
            "no I benchmark may start until an independent compatible IPC backend is integrated"
        )
    source, parent_payload, native_resume = _contract_source(contract)
    runtime = Path(str(contract["runtime"])).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ("logs", "process", "results", "temp", "tmp", "tmpdir", "prefdir"):
        (runtime / name).mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    phase: dict[int, dict[str, float]] = {}
    phase_recorder = None
    if bool(contract.get("phase_timing_confirm", False)):
        from coupling.performance_phase_timing_confirm_v1 import PhaseTimingRecorder
        phase_recorder = PhaseTimingRecorder(
            run_id=str(contract["run_id"]), case_id=str(contract["case_id"]),
            source_global_step=int(contract["source_global_step"]),
            source_time_s=float(contract["source_time_s"]), source_tick=int(contract["source_tick"]),
            dt_s=float(contract["global_dt_s"]),
            slice_ids=tuple(range(int(contract["slice_count"]))),
        )
    lock = threading.Lock()
    process_audit: list[dict[str, Any]] = []
    matlab_process = matlab_stream = None
    matlab_audit = None
    matlab_start_executor: concurrent.futures.ThreadPoolExecutor | None = None
    matlab_start_future: concurrent.futures.Future[Any] | None = None
    matlab_start_overlapped_case_setup = False
    previous_factory = previous_build = None
    previous_log_audit = None
    previous_base_gate = None
    raw_engine = timed_engine = None
    shutdown = None
    result: dict[str, Any]
    failed = False
    previous_protocol_poll: float | None = None
    previous_mapping_atomic_roots = None
    previous_bridge_atomic_roots = None
    try:
        from coupling.stage4f_c_formal_abc_time_consistent_v1 import runner as formal
        from coupling.stage4f_three_slice_timestep_diagnostic_v3 import engine_impl
        from coupling.stage4f_three_slice_short_window_v1_repair2 import runner as short_runner
        from coupling.multi_slice_driver.scheduler import MultiSliceScheduler
        from coupling.multi_slice_driver import protocol as protocol_module
        from .openfoam_persistent import PersistentOpenFOAMSliceProcess

        short_runner.MATLAB_CORE = Path(str(contract["matlab_executable"])).resolve()
        previous_protocol_poll = float(protocol_module.POLL_INTERVAL_S)
        protocol_module.POLL_INTERVAL_S = float(contract.get("protocol_poll_interval_s", previous_protocol_poll))
        if "M" in factors:
            # Start the single owned MATLAB worker while the formal engine
            # prepares fresh case skeletons and restart artifacts.  The
            # worker is resolved before VariableStepRunner.start() sends its
            # initialize transaction, so this only overlaps independent
            # startup work and cannot reorder any physical barrier.
            matlab_start_executor, matlab_start_future = submit_matlab_start(contract, runtime)
            matlab_start_overlapped_case_setup = True

        def resolve_matlab_start() -> None:
            nonlocal matlab_process, matlab_audit, matlab_stream
            if matlab_process is not None or matlab_start_future is None:
                return
            matlab_process, matlab_audit, matlab_stream = matlab_start_future.result()
            process_audit.append(matlab_audit)

        original_engine_factory = formal.factory
        original_engine_class = engine_impl.OpenFOAMSliceProcess
        original_scheduler_class = engine_impl.MultiSliceScheduler
        original_runner_class = short_runner.VariableStepRunner
        # A persistent pimpleFoam process intentionally has no ``End`` line
        # at an intermediate coupling step: it is alive and waiting for the
        # next motion payload.  The legacy audit treats that normal state as
        # a failure.  Keep all existing fatal/non-finite/nonzero checks, but
        # allow an owned persistent process to be audited as ``waiting`` until
        # the segment-level closeout, where ``End`` and return_code=0 remain
        # mandatory.
        previous_log_audit = short_runner._log_audit
        previous_base_gate = formal.base.gate

        def benchmark_gate(row: Mapping[str, Any]) -> bool:
            passed = bool(previous_base_gate(row))
            if not passed:
                reasons = []
                checks = (
                    ("log_passed", bool(row.get("log_passed"))),
                    ("max_cfl", row.get("max_cfl") is not None and float(row["max_cfl"]) < 0.8),
                    ("max_abs_Cd", row.get("max_abs_Cd") is not None and float(row["max_abs_Cd"]) <= 10.0),
                    ("velocity_difference_over_U", row.get("velocity_difference_over_U") is not None and float(row["velocity_difference_over_U"]) <= 0.01),
                    ("virtual_work_relative_error", row.get("virtual_work_relative_error") is not None and float(row["virtual_work_relative_error"]) <= 1.0e-12),
                    ("force_conversion_relative_error", row.get("force_conversion_relative_error") is not None and float(row["force_conversion_relative_error"]) <= 1.0e-10),
                    ("mesh_center_motion_error_m", row.get("mesh_center_motion_error_m") is not None and float(row["mesh_center_motion_error_m"]) <= 1.0e-12),
                )
                reasons = [name for name, ok in checks if not ok]
                try:
                    failure_path = runtime / f"gate_failure_step{int(row.get('step', -1)):08d}.json"
                    failure_path.write_text(json.dumps({"reasons": reasons, "row": dict(row)}, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
                except Exception:
                    pass
            return passed

        formal.base.gate = benchmark_gate

        def benchmark_log_audit(paths: Any, return_codes: Any = None) -> dict[str, Any]:
            audit = previous_log_audit(paths, return_codes)
            if raw_engine is None:
                return audit
            persistent_by_log = {
                str(Path(log).resolve()): process
                for process in getattr(raw_engine, "processes", [])
                if getattr(process, "_persistent_started", False)
                for log in getattr(process, "log_paths", [])
            }
            persistent_by_basename = {
                Path(str(log)).name: process
                for process in getattr(raw_engine, "processes", [])
                if getattr(process, "_persistent_started", False)
                for log in getattr(process, "log_paths", [])
            }
            for row in audit.get("logs", []):
                log_value = str(row.get("path", ""))
                process = persistent_by_log.get(str(Path(log_value).resolve()))
                if process is None:
                    process = persistent_by_basename.get(Path(log_value).name)
                if process is None or process.process is None:
                    continue
                if process.process.poll() is None and not row.get("failure_reasons"):
                    row["persistent_waiting"] = True
                    row["passed"] = bool(row.get("max_cfl") is not None and row["max_cfl"] < 0.8)
            audit["passed"] = bool(audit.get("logs")) and all(bool(item.get("passed")) for item in audit["logs"])
            return audit

        short_runner._log_audit = benchmark_log_audit  # type: ignore[assignment]

        def runner_factory(work_dir: Path, manifest: Any, *, native_resume: Path, dt_s: float, process_registry: list[dict[str, Any]]) -> Any:
            if "M" not in factors:
                return original_runner_class(work_dir, manifest, native_resume=native_resume, dt_s=dt_s, process_registry=process_registry)
            return _PersistentMatlabAdapter(work_dir=work_dir, runtime=runtime, manifest=manifest,
                run_id=str(contract["run_id"]), case_id=str(contract["case_id"]),
                source_global_step=int(contract["source_global_step"]), source_time_s=float(contract["source_time_s"]),
                source_tick=int(contract["source_tick"]), native_resume=native_resume, dt_s=float(contract["global_dt_s"]),
                process_registry=process_registry,
                in_memory_state=bool(contract.get("matlab_in_memory_state", False)),
                start_hook=resolve_matlab_start)

        def process_factory(*args: Any, **kwargs: Any) -> Any:
            if "O" not in factors:
                return original_engine_class(*args, **kwargs)
            end_time = float(contract["source_time_s"]) + int(contract["steps"]) * float(contract["global_dt_s"])
            return PersistentOpenFOAMSliceProcess(
                *args, segment_end_time_s=end_time,
                poll_interval_s=float(contract.get("openfoam_poll_interval_s", 0.02)),
                disable_force_coeffs=bool(contract.get("disable_force_coeffs_output", False)),
                 cache_gamg_agglomeration=bool(contract.get("cache_gamg_agglomeration", False)),
                 wsl_native_case_staging=bool(contract.get("wsl_native_case_staging", False)),
                 native_checkpoint_direct=bool(contract.get("native_checkpoint_direct", False)),
                 compact_force_snapshot=bool(contract.get("compact_force_snapshot", False)),
                 field_write_format=str(contract.get("field_write_format", "ascii")),
                 field_write_precision=int(contract.get("field_write_precision", 16)),
                 direct_wsl_exec=bool(contract.get("direct_wsl_exec", False)),
                 prewarm_openfoam_startup=bool(contract.get("prewarm_openfoam_startup", False)),
                 **kwargs)

        class BoundScheduler(MultiSliceScheduler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                kwargs["parallel_slices"] = "P" in factors
                kwargs["reuse_parallel_executor"] = bool(contract.get("reuse_parallel_executor", False))
                super().__init__(*args, **kwargs)

        short_runner.VariableStepRunner = runner_factory  # type: ignore[assignment]
        engine_impl.OpenFOAMSliceProcess = process_factory  # type: ignore[assignment]
        engine_impl.MultiSliceScheduler = BoundScheduler  # type: ignore[assignment]

        previous_factory = formal.factory
        formal.factory = original_engine_factory
        previous_build = formal.build

        def timed_build(*args: Any, **kwargs: Any) -> tuple[Any, Callable[[], None]]:
            nonlocal raw_engine, timed_engine, shutdown
            raw_engine, raw_shutdown = previous_build(*args, **kwargs)
            checkpoint_manager = getattr(getattr(raw_engine, "scheduler", None), "checkpoint_manager", None)
            if checkpoint_manager is not None:
                # V3 may reuse hashes already computed during prepare().  The
                # manager still checks file existence, size and mtime at
                # commit; restart and legacy audit paths remain uncached.
                checkpoint_manager.reuse_prepare_hashes = bool(
                    contract.get("checkpoint_hash_cache", False)
                )
                for process in getattr(raw_engine, "processes", []):
                    binder = getattr(process, "set_checkpoint_root_callback", None)
                    if binder is not None:
                        binder(lambda root, manager=checkpoint_manager: setattr(manager, "case_root", Path(root).resolve()))
            _instrument_engine(raw_engine, phase, lock)
            if phase_recorder is not None:
                _instrument_phase_engine(raw_engine, phase_recorder)
            timed_engine = _TimedEngine(raw_engine, phase=phase, lock=lock, phase_recorder=phase_recorder)

            def close() -> None:
                raw_shutdown()

            shutdown = close
            return timed_engine, close

        formal.build = timed_build  # type: ignore[assignment]
        start_step = int(contract["source_global_step"]) + 1
        count = int(contract["steps"])
        case_root = runtime / "benchmark_case"
        runtime_root = runtime / "engine_runtime"
        if bool(contract.get("ephemeral_exchange_io", False)):
            # Only transient case exchange and formal exchange directories
            # may use flush+atomic-rename publication.  Checkpoint manifests,
            # field hashes, and restart artifacts remain on the durable path.
            from coupling.multi_slice_mapping import mapping as mapping_module
            from coupling.multi_slice_driver import real_process as real_process_module
            previous_mapping_atomic_roots = mapping_module.set_ephemeral_atomic_roots(
                (case_root / "exchange",)
            )
            previous_bridge_atomic_roots = real_process_module.set_ephemeral_bridge_roots(
                (case_root / "cases",)
            )
        # The formal engine stages only the manifest-listed source checkpoint
        # files into these fresh roots; old runtime/case directories remain
        # read-only inputs.
        output = formal.segment(str(label), str(contract["run_id"]), float(contract["global_dt_s"]),
                                start_step, count, float(contract["source_time_s"]), case_root,
                                runtime_root, source)
        if int(output.get("fully_audited_steps", 0)) != count or output.get("status") != "completed":
            raise RealCoordinatorError(str(output.get("error") or "formal segment did not complete"))
        if "O" in factors and raw_engine is not None:
            # The persistent process is allowed to be alive during interior
            # steps, but final closeout must be a normal OpenFOAM End with a
            # zero return code for every slice.
            for process in getattr(raw_engine, "processes", []):
                code = process.return_code()
                if code != 0:
                    raise RealCoordinatorError(f"persistent OpenFOAM slice {process.slice_id} closed with return code {code}")
                logs = [Path(item) for item in getattr(process, "log_paths", [])]
                if not logs or not any("End" in log.read_text(encoding="utf-8", errors="replace") for log in logs if log.is_file()):
                    raise RealCoordinatorError(f"persistent OpenFOAM slice {process.slice_id} has no final End audit")
        if "A" in factors:
            audit_writer = BatchAuditWriter(runtime / "audit", batch_size=16)
            for row in output.get("steps", []):
                audit_writer.append({"global_step": int(row["step"]), "run_id": str(contract["run_id"]), "case_id": str(contract["case_id"]), "committed": True})
            audit_writer.finalize(checkpoint={"committed": True, "last_step": start_step + count - 1},
                                  raw_snapshot={"committed": True, "steps": count},
                                  gate={"committed": True, "gate": "benchmark_completed"})
        else:
            audit_writer = None
        for row in output.get("steps", []):
            step = int(row["step"])
            values = dict(phase.get(step, {}))
            total = float(values.get("total", 0.0))
            known = sum(float(values.get(name, 0.0)) for name in ("matlab", "wsl", "openfoam", "ipc"))
            values["checkpoint_audit"] = max(0.0, total - known)
            values["total"] = total
            phase[step] = values
        # The formal segment has already closed owned children.  Capture the
        # process audit after closeout, then make telemetry self-contained.
        native_staging_audit: list[dict[str, Any]] = []
        if raw_engine is not None:
            process_audit.extend(list(getattr(raw_engine, "registry", [])))
            native_staging_audit = [dict(getattr(process, "native_staging_audit", {}))
                                for process in getattr(raw_engine, "processes", [])]
        step_records = []
        phase_timing_records: list[dict[str, Any]] = []
        for row in output["steps"]:
            step = int(row["step"]); times = phase.get(step, {})
            if phase_recorder is not None:
                phase_timing_records.append(phase_recorder.finalize(
                    step=step, expected_time_s=float(row["time_s"]),
                    slice_ids=tuple(range(int(contract["slice_count"])))))
            process_rows = process_audit
            matlab_pids = [int(item["pid"]) for item in process_rows if item.get("kind") == "matlab" and item.get("pid")]
            if matlab_process is not None:
                matlab_pids.append(int(matlab_process.pid))
            openfoam_pids = {str(item.get("slice_id")): int(item["pid"]) for item in process_rows if item.get("kind") == "openfoam_wsl_launcher" and item.get("pid")}
            step_records.append({"run_id": str(contract["run_id"]), "case_id": str(contract["case_id"]),
                "global_step": step, "case_local_bridge_step": step - int(contract["source_global_step"]),
                "time_s": float(row["time_s"]), "integer_tick": int(row["time_tick"]),
                "request_id": f"stage95_motion_{step:08d}", "transaction_id": f"stage95_tx_{step:08d}",
                "phases_s": {"matlab": float(times.get("matlab", 0.0)), "wsl": float(times.get("wsl", 0.0)),
                             "openfoam": float(times.get("openfoam", 0.0)), "ipc": float(times.get("ipc", 0.0)),
                             "checkpoint_audit": float(times.get("checkpoint_audit", 0.0)), "total": float(times.get("total", 0.0))},
                "matlab_pid": (matlab_pids[-1] if matlab_pids else None), "openfoam_pids": openfoam_pids,
                "wsl_pids": openfoam_pids, "return_codes": {"formal": 0}, "owned_residual": 0,
                "row_audit": {"max_cfl": row.get("max_cfl"), "max_abs_Cd": row.get("max_abs_Cd"),
                               "virtual_work_relative_error": row.get("virtual_work_relative_error")}})
        wall = time.perf_counter() - started
        result = {"status": "completed", "gate": "benchmark_completed", "configuration_label": label,
            "run_id": str(contract["run_id"]), "case_id": str(contract["case_id"]), "factors": sorted(factors),
            "real_measurement": True, "steps": count, "segment_wall_clock_s": wall,
            "wall_clock_s": wall, "step_records": step_records, "formal_output": output,
            "process_audit": process_audit, "audit_batching": bool(audit_writer),
            "native_staging_audit": native_staging_audit,
            "persistent_ipc": False, "persistent_ipc_requested": bool("I" in factors),
            "persistent_ipc_mode": "legacy_file_bridge_unchanged",
            "parallel_slices": bool("P" in factors),
            "matlab_persistent": bool("M" in factors), "openfoam_persistent": bool("O" in factors),
            "matlab_start_overlapped_case_setup": matlab_start_overlapped_case_setup,
            "disable_force_coeffs_output": bool(contract.get("disable_force_coeffs_output", False)),
            "compact_force_snapshot": bool(contract.get("compact_force_snapshot", False)),
            "protocol_poll_interval_s": float(contract.get("protocol_poll_interval_s", 0.005)),
            "field_write_format": str(contract.get("field_write_format", "ascii")),
            "field_write_precision": int(contract.get("field_write_precision", 16)),
            "ephemeral_exchange_io": bool(contract.get("ephemeral_exchange_io", False)),
            "prewarm_openfoam_startup": bool(contract.get("prewarm_openfoam_startup", False)),
            "reuse_parallel_executor": bool(contract.get("reuse_parallel_executor", False)),
            "direct_wsl_exec": bool(contract.get("direct_wsl_exec", False)),
            "cache_gamg_agglomeration": bool(contract.get("cache_gamg_agglomeration", False)),
            "checkpoint_hash_cache": bool(contract.get("checkpoint_hash_cache", False)),
            "ephemeral_exchange_io": bool(contract.get("ephemeral_exchange_io", False)),
            "wsl_native_case_staging": bool(contract.get("wsl_native_case_staging", False)),
            "native_checkpoint_direct": bool(contract.get("native_checkpoint_direct", False)),
            "external_process_starts_by_codex": 0, "owned_residual": 0,
            "launch_mode": launch_mode,
            "resource_start": resource_snapshot(runtime), "source_checkpoint_sha256": _sha256(source),
            "source_global_step": int(contract["source_global_step"]),
            "source_time_s": float(contract["source_time_s"]),
            "source_tick": int(contract["source_tick"]),
            "global_dt_s": float(contract["global_dt_s"])}
        if phase_recorder is not None:
            from coupling.performance_phase_timing_confirm_v1 import summarize_phase_records
            result["phase_timing_confirm"] = True
            result["phase_timing_records"] = phase_timing_records
            result["phase_timing_summary"] = summarize_phase_records(phase_timing_records)
            result["phase_timing_definition"] = {
                "clock": "time.perf_counter_ns",
                "T_ancf": "ancf_end-ancf_start; predict through correct",
                "T_openfoam": "max(slice_end-slice_start); slice sum also retained",
                "T_exchange": "exchange_end-exchange_start envelope",
                "T_sync_and_audit": "sync_audit_end-sync_audit_start",
                "T_step": "step_end-step_start",
                "overlap_gap": "T_ancf+T_openfoam+T_exchange+T_sync_and_audit-T_step",
            }
    except Exception as exc:
        failed = True
        result = {"status": "failed", "gate": "do_not_pass", "configuration_label": label,
                  "run_id": str(contract.get("run_id")), "case_id": str(contract.get("case_id")),
                  "error_type": type(exc).__name__, "error": str(exc), "real_measurement": True,
                  "external_process_starts_by_codex": 0, "owned_residual": 0,
                  "launch_mode": launch_mode}
    finally:
        # If case construction failed before the runner factory resolved the
        # future, collect it now so an owned MATLAB process cannot outlive the
        # terminal runtime.  A failed probe is already fail-closed inside
        # _start_matlab and does not return a process handle.
        if matlab_start_future is not None and matlab_process is None:
            try:
                matlab_process, matlab_audit, matlab_stream = matlab_start_future.result()
                process_audit.append(matlab_audit)
            except Exception:
                pass
        if matlab_start_executor is not None:
            matlab_start_executor.shutdown(wait=True)
        if matlab_process is not None and matlab_stream is not None:
            _close_matlab(matlab_process, process_audit[0], matlab_stream, runtime, str(contract["run_id"]))
        if previous_factory is not None:
            try:
                from coupling.stage4f_c_formal_abc_time_consistent_v1 import runner as formal_module
                formal_module.factory = previous_factory
                if previous_build is not None:
                    formal_module.build = previous_build
            except Exception:
                pass
        if previous_log_audit is not None:
            try:
                from coupling.stage4f_three_slice_short_window_v1_repair2 import runner as short_runner_module
                short_runner_module._log_audit = previous_log_audit
            except Exception:
                pass
        if previous_base_gate is not None:
            try:
                from coupling.stage4f_c_formal_abc_time_consistent_v1 import runner as formal_module
                formal_module.base.gate = previous_base_gate
            except Exception:
                pass
        if previous_mapping_atomic_roots is not None:
            try:
                from coupling.multi_slice_mapping import mapping as mapping_module
                mapping_module.set_ephemeral_atomic_roots(previous_mapping_atomic_roots)
            except Exception:
                pass
        if previous_bridge_atomic_roots is not None:
            try:
                from coupling.multi_slice_driver import real_process as real_process_module
                real_process_module.set_ephemeral_bridge_roots(previous_bridge_atomic_roots)
            except Exception:
                pass
        if previous_protocol_poll is not None:
            try:
                from coupling.multi_slice_driver import protocol as protocol_module
                protocol_module.POLL_INTERVAL_S = previous_protocol_poll
            except Exception:
                pass
    if result.get("status") == "failed":
        if detect_applicationservice_5001(_failure_evidence_texts(runtime, str(result.get("error", "")))):
            result.update({
                "error_classification": "matlab_applicationservice_5001",
                "requires_user_session_runner": True,
                "next_action": "stop_and_request_user_session_id_1_runner",
                "same_runtime_retry": False,
            })
        else:
            result.setdefault("error_classification", "unknown_non_5001_failure")
            result.setdefault("requires_user_session_runner", False)
    _json(runtime / "benchmark_result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    contract_path = Path(os.environ.get("CFD_ANCF_BENCHMARK_CONTRACT", ""))
    if not contract_path.is_file():
        raise SystemExit("CFD_ANCF_BENCHMARK_CONTRACT is missing")
    try:
        result = run_contract(contract_path)
        if result.get("status") != "completed":
            print(json.dumps(result, ensure_ascii=True))
            return 2
    except Exception as exc:
        print(json.dumps({"gate": "do_not_pass", "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=True))
        return 2
    print(json.dumps({"gate": "benchmark_completed", "result": str(Path(os.environ["CFD_ANCF_BENCHMARK_RUNTIME"]) / "benchmark_result.json")}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
