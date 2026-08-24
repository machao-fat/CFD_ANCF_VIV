"""Fail-closed 0.2.1 multi-slice scheduler with late structure finalization."""

from __future__ import annotations

import json
import math
import os
import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from ..checkpoint import AtomicCheckpointManager, CheckpointError, CommittedPublishError, PreparedCheckpoint
from ..multi_slice_mapping.mapping import (
    LoadRecord,
    MotionRecord,
    RuntimeConfig,
    SliceDefinition,
    SliceManifest,
    SCHEMA_VERSION,
    build_H_for_manifest,
    map_integrated_slice_forces,
    validate_record_transaction,
)
from .contract import SliceExchangePaths, SliceSpec, build_config, build_slice_manifest, validate_specs
from .protocol import ProtocolError, publish_consumed, publish_payload, read_ready_payload, wait_consumed, wait_ready


class SchedulerError(RuntimeError):
    """Raised for a rejected transaction or illegal state transition."""


class SchedulerState(str, Enum):
    INITIALIZED = "INITIALIZED"
    PREDICTED = "PREDICTED"
    MOTION_PUBLISHED = "MOTION_PUBLISHED"
    MOTION_CONSUMED = "MOTION_CONSUMED"
    CFD_ADVANCED = "CFD_ADVANCED"
    LOADS_READY = "LOADS_READY"
    LOADS_CONSUMED = "LOADS_CONSUMED"
    STRUCTURE_CORRECTED = "STRUCTURE_CORRECTED"
    CHECKPOINT_PREPARED = "CHECKPOINT_PREPARED"
    COMMITTED = "COMMITTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    FAILED = "FAILED"


_NEXT_STATE = {
    SchedulerState.INITIALIZED: SchedulerState.PREDICTED,
    SchedulerState.PREDICTED: SchedulerState.MOTION_PUBLISHED,
    SchedulerState.MOTION_PUBLISHED: SchedulerState.MOTION_CONSUMED,
    SchedulerState.MOTION_CONSUMED: SchedulerState.CFD_ADVANCED,
    SchedulerState.CFD_ADVANCED: SchedulerState.LOADS_READY,
    SchedulerState.LOADS_READY: SchedulerState.LOADS_CONSUMED,
    SchedulerState.LOADS_CONSUMED: SchedulerState.STRUCTURE_CORRECTED,
    SchedulerState.STRUCTURE_CORRECTED: SchedulerState.CHECKPOINT_PREPARED,
    SchedulerState.CHECKPOINT_PREPARED: SchedulerState.COMMITTED,
}


class StructureAdapter(Protocol):
    def predict_all(self, step: int, time_s: float, previous_slice_forces: Sequence[Sequence[float]]) -> Sequence[Mapping[str, object] | MotionRecord]: ...
    def correct_all(self, step: int, time_s: float, integrated_slice_forces: Sequence[Mapping[str, object] | LoadRecord]) -> Mapping[str, object]: ...
    def export_staged_checkpoint(self) -> Mapping[str, object]: ...
    def finalize_committed(self, checkpoint_token: object | None = None) -> None: ...
    def discard_staged(self) -> None: ...
    def load_checkpoint(self, path: str | Path) -> None: ...


class SliceProcess(Protocol):
    slice_id: int
    def publish_motion(self, record: Mapping[str, object] | MotionRecord, paths: SliceExchangePaths, *, manifest: SliceManifest, runtime_config: RuntimeConfig) -> Mapping[str, object]: ...
    def wait_motion_consumed(self, step: int, time_s: float, *, paths: SliceExchangePaths, manifest: SliceManifest, runtime_config: RuntimeConfig) -> Mapping[str, object]: ...
    def advance_one_step(self, step: int, time_s: float) -> None: ...
    def wait_load_ready(self, step: int, time_s: float, *, paths: SliceExchangePaths, manifest: SliceManifest, runtime_config: RuntimeConfig) -> Mapping[str, object]: ...
    def read_load(self, step: int, time_s: float) -> Mapping[str, object] | LoadRecord: ...
    def publish_load_consumed(self, step: int, time_s: float, *, paths: SliceExchangePaths, manifest: SliceManifest, runtime_config: RuntimeConfig) -> Mapping[str, object]: ...
    def checkpoint_files(self, step: int, time_s: float) -> Mapping[str, object]: ...
    def restore_checkpoint(self, entry: Mapping[str, object]) -> None: ...


class StabilizationHook(Protocol):
    def apply(self, *, step: int, time_s: float, time_tick: int, case_id: str,
              run_id: str, raw_loads: Sequence[LoadRecord],
              previous_state: Mapping[str, object]) -> Mapping[str, object]: ...
    def commit(self, state: Mapping[str, object]) -> None: ...
    def rollback(self) -> None: ...


@dataclass(frozen=True)
class MultiSliceConfig:
    case_id: str
    dt_s: float
    timeout_s: float
    specs: tuple[SliceDefinition, ...] = field(default_factory=tuple)
    start_time_s: float = 0.0
    reference_length_m: float | None = None
    represented_length_m: float | None = None
    R_GL: tuple[tuple[float, float, float], ...] | None = None
    manifest: SliceManifest | None = None

    def __post_init__(self) -> None:
        if self.manifest is None:
            if not self.specs:
                raise SchedulerError("specs or manifest is required")
            raw = build_slice_manifest(
                self.case_id, self.specs,
                reference_length_m=self.reference_length_m,
                represented_length_m=self.represented_length_m,
                R_GL=self.R_GL or ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            )
            object.__setattr__(self, "manifest", SliceManifest.from_mapping(raw))
        else:
            self.manifest.validate()
            if self.manifest.case_id != self.case_id:
                raise SchedulerError("config case_id does not match manifest")
            object.__setattr__(self, "specs", tuple(self.manifest.slices))
        object.__setattr__(self, "specs", validate_specs(tuple(self.manifest.slices)))
        if float(self.dt_s) <= 0.0 or float(self.timeout_s) <= 0.0:
            raise SchedulerError("dt_s and timeout_s must be strictly > 0")

    @property
    def runtime_config(self) -> RuntimeConfig:
        return RuntimeConfig(
            schema_version=SCHEMA_VERSION, case_id=self.case_id,
            dt_s=self.dt_s, timeout_s=self.timeout_s, start_time_s=self.start_time_s,
            coupling_iteration=0, coupling_scheme="explicit_weak",
            slice_manifest_sha256=self.manifest.slice_manifest_sha256,
        )

    def as_json(self) -> dict[str, object]:
        return self.runtime_config.to_dict()

    @property
    def slice_manifest(self) -> dict[str, object]:
        return self.manifest.to_dict()

    @property
    def config_sha256(self) -> str:
        return self.runtime_config.config_sha256 or self.runtime_config.computed_config_sha256()

    @property
    def slice_manifest_sha256(self) -> str:
        return self.manifest.slice_manifest_sha256 or self.manifest.computed_slice_manifest_sha256()


@dataclass(frozen=True)
class StepResult:
    step: int
    time_s: float
    state: SchedulerState
    integrated_slice_forces: tuple[dict[str, object], ...]
    checkpoint_path: Path
    audit: Mapping[str, object]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite(value: object, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SchedulerError(f"{name} is not numeric") from exc
    if not math.isfinite(result):
        raise SchedulerError(f"{name} is NaN/Inf")
    return result


class MultiSliceScheduler:
    """One global barrier per step; no stale payload fallback exists."""

    def __init__(
        self, *, config: MultiSliceConfig, exchange_root: str | Path,
        structure: StructureAdapter,
        slice_processes: Sequence[SliceProcess] | Mapping[int, SliceProcess],
        checkpoint_root: str | Path | None = None,
        case_root: str | Path | None = None,
        stabilization_hook: StabilizationHook | None = None,
        run_id: str | None = None,
        committed_step: int = -1,
        committed_time_s: float | None = None,
        committed_time_tick: int | None = None,
        parallel_slices: bool = False,
        reuse_parallel_executor: bool = False,
    ) -> None:
        self.config = config
        self.exchange_root = Path(exchange_root)
        self.exchange_root.mkdir(parents=True, exist_ok=True)
        self.structure = structure
        self.stabilization_hook = stabilization_hook
        self.run_id = str(run_id or "")
        self.parallel_slices = bool(parallel_slices)
        self.reuse_parallel_executor = bool(reuse_parallel_executor)
        self._parallel_executor = None
        if stabilization_hook is not None and not self.run_id:
            raise SchedulerError("run_id is required when stabilization hook is enabled")
        if hasattr(structure, "set_case_id"):
            structure.set_case_id(config.case_id)
        self.processes = self._normalize_processes(slice_processes)
        self.paths = {spec.slice_id: SliceExchangePaths(self.exchange_root, spec) for spec in config.specs}
        for item in self.paths.values():
            item.ensure()
        self._write_or_verify_static_files()
        self.checkpoint_manager = AtomicCheckpointManager(
            checkpoint_root=checkpoint_root or self.exchange_root / "checkpoints",
            case_root=case_root or self.exchange_root / "cases",
            case_id=config.case_id, dt_s=config.dt_s,
            manifest=config.manifest, runtime_config=config.runtime_config,
        )
        for process in self.processes.values():
            if hasattr(process, "bind_protocol"):
                process.bind_protocol(config.manifest, config.runtime_config)
        self.state = SchedulerState.INITIALIZED
        if isinstance(committed_step, bool) or not isinstance(committed_step, int) or committed_step < -1:
            raise SchedulerError("committed_step is invalid")
        if committed_time_tick is not None and (isinstance(committed_time_tick, bool) or not isinstance(committed_time_tick, int) or committed_time_tick < 0):
            raise SchedulerError("committed_time_tick is invalid")
        self.last_committed_step = committed_step
        self.last_committed_time_s = float(config.start_time_s if committed_time_s is None else committed_time_s)
        if committed_time_tick is not None and abs(self.last_committed_time_s - committed_time_tick * 1.0e-9) > 5.0e-13:
            raise SchedulerError("committed time/tick mismatch")
        self.previous_slice_forces_N: list[list[float]] = [[0.0, 0.0, 0.0] for _ in config.specs]
        self.previous_raw_slice_forces_N: list[list[float]] = [[0.0, 0.0, 0.0] for _ in config.specs]
        self.previous_generalized_force: list[float] = []
        self.stabilizer_state: dict[str, object] = {}
        self._log_path = self.exchange_root / "transaction_log.jsonl"
        self._active_correction: Mapping[str, object] | None = None
        self._active_checkpoint: PreparedCheckpoint | None = None
        self._committed_checkpoint_path: Path | None = None

    def _parallel_slice_map(self, operation: Any, slice_ids: Sequence[int]) -> dict[int, Any]:
        """Run independent slice-side protocol calls concurrently when enabled.

        The returned mapping is normalized by slice id, so all downstream
        validation and checkpoint preparation retain the same deterministic
        ordering as the sequential path.  Exceptions are allowed to escape;
        ``run_step`` then poisons the transaction before commit.
        """
        ids = [int(item) for item in slice_ids]
        if not self.parallel_slices or len(ids) <= 1:
            return {sid: operation(sid) for sid in ids}
        if getattr(self, "reuse_parallel_executor", False):
            if getattr(self, "_parallel_executor", None) is None:
                self._parallel_executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(ids), thread_name_prefix="multi-slice-barrier")
            pool = self._parallel_executor
            futures = {pool.submit(operation, sid): sid for sid in ids}
            result: dict[int, Any] = {}
            for future in concurrent.futures.as_completed(futures):
                sid = futures[future]
                result[sid] = future.result()
            return {sid: result[sid] for sid in ids}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ids)) as pool:
            futures = {pool.submit(operation, sid): sid for sid in ids}
            result: dict[int, Any] = {}
            for future in concurrent.futures.as_completed(futures):
                sid = futures[future]
                result[sid] = future.result()
            return {sid: result[sid] for sid in ids}

    def close_parallel_executor(self) -> None:
        """Close the optional segment-level worker pool after the barrier."""
        pool = getattr(self, "_parallel_executor", None)
        if pool is not None:
            pool.shutdown(wait=True)
            self._parallel_executor = None

    def bind_restart_source(self, manifest_path: str | Path, *, expected_run_id: str,
            expected_next_step: int, expected_next_time_s: float) -> Mapping[str, object]:
        """Validate and bind the committed checkpoint that parents a restart."""
        path = Path(manifest_path).resolve()
        if not path.is_file():
            raise SchedulerError("restart source checkpoint is missing")
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            self.checkpoint_manager._validate_manifest(manifest, require_status="committed",
                verify_files=True, checkpoint_root=path.parent)
        except (OSError, UnicodeError, json.JSONDecodeError, CheckpointError) as exc:
            raise SchedulerError(f"restart source checkpoint identity failed: {exc}") from exc
        if manifest.get("schema_version") != "0.2.1+stabilizer.1":
            raise SchedulerError("restart source is not a stabilized checkpoint")
        if manifest.get("run_id") != expected_run_id:
            raise SchedulerError("restart source run identity mismatch")
        source_step, source_tick = int(manifest["step"]), int(manifest["time_tick"])
        expected_tick = int(round(float(expected_next_time_s) * 1.0e9))
        if source_step + 1 != int(expected_next_step):
            raise SchedulerError("restart source step is not continuous")
        if source_tick + int(round(float(self.config.dt_s) * 1.0e9)) != expected_tick:
            raise SchedulerError("restart source integer tick is not continuous")
        self._committed_checkpoint_path = path
        self.last_committed_step = source_step
        self.last_committed_time_s = float(manifest["time_s"])
        return manifest

    def _normalize_processes(self, processes: Sequence[SliceProcess] | Mapping[int, SliceProcess]) -> dict[int, SliceProcess]:
        pairs = list(processes.items()) if isinstance(processes, Mapping) else [(int(getattr(p, "slice_id", -1)), p) for p in processes]
        result: dict[int, SliceProcess] = {}
        for key, process in pairs:
            sid = int(key)
            if sid != int(getattr(process, "slice_id", -1)):
                raise SchedulerError("slice process mapping key and slice_id disagree")
            if sid in result:
                raise SchedulerError(f"duplicate slice_id process: {sid}")
            result[sid] = process
        expected = {spec.slice_id for spec in self.config.specs}
        if set(result) != expected:
            raise SchedulerError(
                f"slice process set mismatch; missing={sorted(expected-set(result))}, unexpected={sorted(set(result)-expected)}"
            )
        return result

    def _write_or_verify_static_files(self) -> None:
        for path, value, digest in (
            (self.exchange_root / "slice_manifest.json", self.config.slice_manifest, self.config.slice_manifest_sha256),
            (self.exchange_root / "config.json", self.config.as_json(), self.config.config_sha256),
        ):
            if path.is_file():
                try:
                    actual = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise SchedulerError(f"invalid existing static file: {path}") from exc
                if path.name == "slice_manifest.json":
                    parsed = SliceManifest.from_mapping(actual)
                    if parsed.slice_manifest_sha256 != digest:
                        raise SchedulerError(f"existing static file hash mismatch: {path}")
                else:
                    parsed = RuntimeConfig.from_mapping(actual)
                    if parsed.config_sha256 != digest:
                        raise SchedulerError(f"existing static file hash mismatch: {path}")
            else:
                from ..multi_slice_mapping.mapping import atomic_write_json
                atomic_write_json(path, value)

    def _append_log(self, *, step: int, time_s: float, slice_id: int | None, event: str, payload_sha256: str | None = None, status: SchedulerState | str | None = None) -> None:
        record = {
            "case_id": self.config.case_id, "step": step, "time_s": time_s,
            "slice_id": slice_id, "event": event, "timestamp": _utc_now(),
            "payload_sha256": payload_sha256,
            "status": status.value if isinstance(status, SchedulerState) else str(status or self.state.value),
        }
        with self._log_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _transition(self, new_state: SchedulerState, *, step: int, time_s: float, slice_id: int | None = None, payload_sha256: str | None = None) -> None:
        if new_state == SchedulerState.FAILED:
            self.state = new_state
        elif new_state == SchedulerState.RECOVERY_REQUIRED:
            if self.state not in {SchedulerState.CHECKPOINT_PREPARED, SchedulerState.COMMITTED}:
                raise SchedulerError(f"illegal recovery transition from {self.state.value}")
            self.state = new_state
        elif _NEXT_STATE.get(self.state) != new_state:
            raise SchedulerError(f"illegal state transition {self.state.value} -> {new_state.value}")
        else:
            self.state = new_state
        self._append_log(step=step, time_s=time_s, slice_id=slice_id, event="state_transition", payload_sha256=payload_sha256, status=self.state)

    def _write_failure(self, *, step: int, time_s: float, phase: str, slice_id: int | None, reason: str, status: str = "failed") -> None:
        from ..multi_slice_mapping.mapping import atomic_write_json
        atomic_write_json(self.exchange_root / f"failure_step{step:08d}.json", {
            "schema_version": SCHEMA_VERSION, "status": status, "case_id": self.config.case_id,
            "step": step, "time_s": time_s, "coupling_iteration": 0,
            "slice_id": slice_id, "phase": phase, "reason": reason,
            "state": self.state.value, "last_committed_step": self.last_committed_step,
            "last_committed_time_s": self.last_committed_time_s, "created_utc": _utc_now(),
        })

    def _fail_precommit(self, *, step: int, time_s: float, phase: str, exc: Exception) -> None:
        try:
            if self._active_correction is not None:
                self.structure.discard_staged()
        except Exception as discard_exc:
            exc = SchedulerError(f"{exc}; discard_staged failed: {discard_exc}")
        finally:
            self._active_correction = None
            self._active_checkpoint = None
        self.state = SchedulerState.FAILED
        self._append_log(step=step, time_s=time_s, slice_id=getattr(exc, "slice_id", None), event="failed", status=self.state)
        self._write_failure(step=step, time_s=time_s, phase=phase, slice_id=getattr(exc, "slice_id", None), reason=str(exc))

    def _h_by_slice_id(self) -> Mapping[int, Sequence[Sequence[float]]]:
        getter = getattr(self.structure, "h_by_slice_id", None)
        if getter is not None:
            return getter()
        getter = getattr(self.structure, "get_H_by_slice_id", None)
        if getter is not None:
            return getter()
        # Mock fallback: one generalized cross-flow DOF.  The production
        # adapter always supplies A-module Hermite H matrices.
        return {spec.slice_id: ((0.0,), (1.0,), (0.0,)) for spec in self.config.specs}

    def run_step(self, *, step: int, time_s: float) -> StepResult:
        if self.state not in {SchedulerState.INITIALIZED, SchedulerState.COMMITTED}:
            raise SchedulerError(f"scheduler is not ready for a new step: {self.state.value}")
        if step != self.last_committed_step + 1:
            raise SchedulerError(f"step must continue from {self.last_committed_step + 1}, got {step}")
        time_value = _finite(time_s, "time_s")
        if time_value < 0.0:
            raise SchedulerError("time_s must be non-negative")
        if self.state == SchedulerState.COMMITTED:
            self.state = SchedulerState.INITIALIZED
        correction: Mapping[str, object] | None = None
        committed_persisted = False
        try:
            predicted = list(self.structure.predict_all(step, time_value, self.previous_slice_forces_N))
            motion_records = validate_record_transaction(
                [item if isinstance(item, MotionRecord) else MotionRecord.from_mapping(item) for item in predicted],
                self.config.manifest, kind="motion", expected_step=step, expected_time_s=time_value,
            )
            self._transition(SchedulerState.PREDICTED, step=step, time_s=time_value)
            def publish_one(sid: int) -> Mapping[str, object]:
                record = motion_records[sid]
                return self.processes[sid].publish_motion(record, self.paths[sid], manifest=self.config.manifest, runtime_config=self.config.runtime_config)
            motion_markers = self._parallel_slice_map(publish_one, list(motion_records))
            for sid in motion_records:
                marker = motion_markers[sid]
                self._append_log(step=step, time_s=time_value, slice_id=sid, event="motion_ready", payload_sha256=str(marker.get("payload_sha256")), status=SchedulerState.MOTION_PUBLISHED)
            self._transition(SchedulerState.MOTION_PUBLISHED, step=step, time_s=time_value)
            def consume_motion(sid: int) -> Mapping[str, object]:
                return self.processes[sid].wait_motion_consumed(step, time_value, paths=self.paths[sid], manifest=self.config.manifest, runtime_config=self.config.runtime_config)
            consumed_motion = self._parallel_slice_map(consume_motion, [spec.slice_id for spec in self.config.specs])
            for spec in self.config.specs:
                consumed = consumed_motion[spec.slice_id]
                self._append_log(step=step, time_s=time_value, slice_id=spec.slice_id, event="motion_consumed", payload_sha256=str(consumed.get("payload_sha256")), status=SchedulerState.MOTION_CONSUMED)
            self._transition(SchedulerState.MOTION_CONSUMED, step=step, time_s=time_value)
            def advance_one(sid: int) -> None:
                self.processes[sid].advance_one_step(step, time_value)
                return None
            self._parallel_slice_map(advance_one, [spec.slice_id for spec in self.config.specs])
            for spec in self.config.specs:
                self._append_log(step=step, time_s=time_value, slice_id=spec.slice_id, event="cfd_advanced", status=SchedulerState.CFD_ADVANCED)
            self._transition(SchedulerState.CFD_ADVANCED, step=step, time_s=time_value)
            load_records: list[LoadRecord] = []
            def read_one(sid: int) -> tuple[Mapping[str, object], Mapping[str, object] | LoadRecord]:
                ready = self.processes[sid].wait_load_ready(step, time_value, paths=self.paths[sid], manifest=self.config.manifest, runtime_config=self.config.runtime_config)
                return ready, self.processes[sid].read_load(step, time_value)
            loaded = self._parallel_slice_map(read_one, [spec.slice_id for spec in self.config.specs])
            for spec in self.config.specs:
                ready, load = loaded[spec.slice_id]
                load_records.append(load if isinstance(load, LoadRecord) else LoadRecord.from_mapping(load, self.config.manifest.R_GL))
                self._append_log(step=step, time_s=time_value, slice_id=spec.slice_id, event="load_ready", payload_sha256=str(ready.get("payload_sha256")), status=SchedulerState.LOADS_READY)
            ordered_loads = validate_record_transaction(load_records, self.config.manifest, kind="load", expected_step=step, expected_time_s=time_value)
            raw_mapping = map_integrated_slice_forces(self.config.manifest, self._h_by_slice_id(), ordered_loads)
            self._transition(SchedulerState.LOADS_READY, step=step, time_s=time_value)
            def consume_load(sid: int) -> Mapping[str, object]:
                return self.processes[sid].publish_load_consumed(step, time_value, paths=self.paths[sid], manifest=self.config.manifest, runtime_config=self.config.runtime_config)
            consumed_load = self._parallel_slice_map(consume_load, [spec.slice_id for spec in self.config.specs])
            for spec in self.config.specs:
                consumed = consumed_load[spec.slice_id]
                self._append_log(step=step, time_s=time_value, slice_id=spec.slice_id, event="load_consumed", payload_sha256=str(consumed.get("payload_sha256")), status=SchedulerState.LOADS_CONSUMED)
            self._transition(SchedulerState.LOADS_CONSUMED, step=step, time_s=time_value)
            applied_loads = ordered_loads
            pending_stabilizer_state: Mapping[str, object] | None = None
            raw_force_snapshot_manifests = None
            if self.stabilization_hook is not None:
                time_tick = int(round(time_value * 1.0e9))
                if getattr(self.stabilization_hook, "requires_raw_snapshot_manifest", False):
                    raw_force_snapshot_manifests = [self.processes[spec.slice_id].consumed_force_manifest(step, time_tick) for spec in self.config.specs]
                outcome = self.stabilization_hook.apply(
                    step=step, time_s=time_value, time_tick=time_tick,
                    case_id=self.config.case_id, run_id=self.run_id,
                    raw_loads=list(ordered_loads.values()), previous_state=dict(self.stabilizer_state),
                )
                if not isinstance(outcome, Mapping) or "applied_loads" not in outcome or "state" not in outcome:
                    raise SchedulerError("stabilization hook returned an incomplete outcome")
                candidates = [item if isinstance(item, LoadRecord) else LoadRecord.from_mapping(item, self.config.manifest.R_GL) for item in outcome["applied_loads"]]
                applied_loads = validate_record_transaction(candidates, self.config.manifest, kind="load", expected_step=step, expected_time_s=time_value)
                pending_stabilizer_state = outcome["state"]
                if not isinstance(pending_stabilizer_state, Mapping):
                    raise SchedulerError("stabilization hook state is not an object")
            mapping = map_integrated_slice_forces(self.config.manifest, self._h_by_slice_id(), applied_loads)
            if hasattr(self.structure, "accept_generalized_force"):
                self.structure.accept_generalized_force(mapping.generalized_force)
            correction = self.structure.correct_all(step, time_value, list(applied_loads.values()))
            if not isinstance(correction, Mapping) or int(correction.get("step", -1)) != step:
                raise SchedulerError("structure correct returned wrong step")
            if abs(_finite(correction.get("time_s"), "structure.time_s") - time_value) > 1.0e-12 * max(1.0, abs(time_value)):
                raise SchedulerError("structure correct returned wrong time")
            generalized = correction.get("generalized_force", list(mapping.generalized_force))
            if not isinstance(generalized, (list, tuple)) or any(not math.isfinite(float(value)) for value in generalized):
                raise SchedulerError("structure generalized force is not finite")
            if self.stabilization_hook is not None:
                validator = getattr(self.stabilization_hook, "validate_correction", None)
                if validator is not None:
                    staged_exporter = getattr(self.structure, "export_staged_checkpoint", None)
                    staged_state = staged_exporter() if staged_exporter is not None else None
                    validator(correction, predicted_motion=list(motion_records.values()), staged_state=staged_state)
            self._active_correction = correction
            self._transition(SchedulerState.STRUCTURE_CORRECTED, step=step, time_s=time_value)
            prepared = self.checkpoint_manager.prepare(
                step=step, time_s=time_value, coupling_iteration=0,
                slice_processes=self.processes, structure=self.structure,
                previous_slice_forces_N=[[float(row.force_N[0]), float(row.force_N[1]), float(row.force_N[2])] for row in ordered_loads.values()],
                previous_generalized_force=[float(value) for value in generalized],
                raw_slice_forces_N=[[float(row.force_N[0]), float(row.force_N[1]), float(row.force_N[2])] for row in ordered_loads.values()] if self.stabilization_hook is not None else None,
                applied_slice_forces_N=[[float(row.force_N[0]), float(row.force_N[1]), float(row.force_N[2])] for row in applied_loads.values()] if self.stabilization_hook is not None else None,
                stabilizer_state=pending_stabilizer_state,
                run_id=self.run_id or None,
                time_tick=int(round(time_value * 1.0e9)) if self.stabilization_hook is not None else None,
                parent_checkpoint_id=(self._committed_checkpoint_path.stem if self._committed_checkpoint_path else None) if self.stabilization_hook is not None else None,
                raw_force_snapshot_manifests=raw_force_snapshot_manifests,
            )
            self._active_checkpoint = prepared
            self._transition(SchedulerState.CHECKPOINT_PREPARED, step=step, time_s=time_value)
            checkpoint_path = self.checkpoint_manager.commit(prepared)
            committed_persisted = True
            self._committed_checkpoint_path = checkpoint_path
            try:
                self.structure.finalize_committed(prepared.staged_token)
            except Exception as finalize_exc:
                self._transition(SchedulerState.RECOVERY_REQUIRED, step=step, time_s=time_value)
                self._write_failure(step=step, time_s=time_value, phase="finalize_committed", slice_id=None, reason=str(finalize_exc), status="recovery_required")
                raise SchedulerError(f"committed checkpoint requires recovery: {finalize_exc}") from finalize_exc
            self._transition(SchedulerState.COMMITTED, step=step, time_s=time_value)
            self.last_committed_step = step
            self.last_committed_time_s = time_value
            self.previous_slice_forces_N = [[float(row.force_N[0]), float(row.force_N[1]), float(row.force_N[2])] for row in ordered_loads.values()]
            if self.stabilization_hook is not None:
                self.previous_raw_slice_forces_N = [[float(row.force_N[0]), float(row.force_N[1]), float(row.force_N[2])] for row in ordered_loads.values()]
                self.previous_slice_forces_N = [[float(row.force_N[0]), float(row.force_N[1]), float(row.force_N[2])] for row in applied_loads.values()]
                self.stabilizer_state = dict(pending_stabilizer_state or {})
                self.stabilization_hook.commit(self.stabilizer_state)
            self.previous_generalized_force = [float(value) for value in generalized]
            self._active_correction = None
            self._active_checkpoint = None
            audit = correction.get("audit", {})
            if not isinstance(audit, Mapping):
                audit = {"value": audit}
            audit = dict(audit)
            audit["generalized_force_from_A_Ht"] = list(mapping.generalized_force)
            return StepResult(step, time_value, self.state, tuple(dict(row.to_dict()) for row in ordered_loads.values()), checkpoint_path, audit)
        except Exception as exc:
            if self.stabilization_hook is not None and not committed_persisted:
                self.stabilization_hook.rollback()
            if committed_persisted or self.state == SchedulerState.RECOVERY_REQUIRED:
                raise SchedulerError(str(exc)) from exc
            phase = self.state.value
            self._fail_precommit(step=step, time_s=time_value, phase=phase, exc=exc)
            if isinstance(exc, SchedulerError):
                raise
            raise SchedulerError(str(exc)) from exc

    def recover_from_checkpoint(self, manifest_path: str | Path) -> dict[str, object]:
        if self.state != SchedulerState.RECOVERY_REQUIRED:
            raise SchedulerError("recovery is only valid in RECOVERY_REQUIRED state")
        try:
            restored = self.checkpoint_manager.load_restart(manifest_path, slice_processes=self.processes, structure=self.structure)
            if hasattr(self.structure, "finalize_committed"):
                self.structure.finalize_committed(restored.get("checkpoint_id"))
        except Exception as exc:
            self._write_failure(step=self.last_committed_step + 1, time_s=self.last_committed_time_s, phase="recovery", slice_id=getattr(exc, "slice_id", None), reason=str(exc), status="recovery_required")
            raise SchedulerError(f"recovery failed: {exc}") from exc
        self.last_committed_step = int(restored["step"])
        self.last_committed_time_s = float(restored["time_s"])
        self.previous_slice_forces_N = [list(map(float, row)) for row in restored["previous_slice_forces_N"]]
        self.previous_generalized_force = list(map(float, restored["previous_generalized_force"]))
        if self.stabilization_hook is not None:
            if "stabilizer_state" not in restored:
                raise SchedulerError("stabilized restart requires an extended checkpoint")
            self.previous_raw_slice_forces_N = [list(map(float, row)) for row in restored["raw_slice_forces_N"]]
            self.previous_slice_forces_N = [list(map(float, row)) for row in restored["applied_slice_forces_N"]]
            self.stabilizer_state = dict(restored["stabilizer_state"])
            self.stabilization_hook.commit(self.stabilizer_state)
        self._active_correction = None
        self._active_checkpoint = None
        self.state = SchedulerState.INITIALIZED
        self._append_log(step=self.last_committed_step, time_s=self.last_committed_time_s, slice_id=None, event="recovered", status=self.state)
        return restored

    def restore_from_checkpoint(self, manifest_path: str | Path) -> dict[str, object]:
        if self.state != SchedulerState.INITIALIZED or self.last_committed_step != -1:
            raise SchedulerError("restart must be loaded before a transaction begins")
        try:
            restored = self.checkpoint_manager.load_restart(manifest_path, slice_processes=self.processes, structure=self.structure)
        except Exception as exc:
            raise SchedulerError(str(exc)) from exc
        self.last_committed_step = int(restored["step"])
        self.last_committed_time_s = float(restored["time_s"])
        self.previous_slice_forces_N = [list(map(float, row)) for row in restored["previous_slice_forces_N"]]
        self.previous_generalized_force = list(map(float, restored["previous_generalized_force"]))
        if self.stabilization_hook is not None:
            if "stabilizer_state" not in restored:
                initializer = getattr(self.stabilization_hook, "initialize_from_legacy", None)
                if initializer is None:
                    raise SchedulerError("stabilized legacy restart requires explicit initialization")
                state = initializer(restored)
                if not isinstance(state, Mapping):
                    raise SchedulerError("legacy stabilizer initialization returned invalid state")
                self.stabilizer_state = dict(state)
                self.previous_raw_slice_forces_N = [list(map(float, row)) for row in restored["previous_slice_forces_N"]]
            else:
                self.stabilizer_state = dict(restored["stabilizer_state"])
                self.previous_raw_slice_forces_N = [list(map(float, row)) for row in restored["raw_slice_forces_N"]]
                self.previous_slice_forces_N = [list(map(float, row)) for row in restored["applied_slice_forces_N"]]
            self.stabilization_hook.commit(self.stabilizer_state)
        return restored
