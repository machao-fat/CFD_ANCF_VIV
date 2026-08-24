"""Stage100 adapter for the existing persistent OpenFOAM slice protocol.

The adapter is intentionally a thin lifecycle bridge.  The authoritative
0.2.1 CSV/ready/consumed protocol, force conversion, immutable force snapshot,
and WSL/pimpleFoam process implementation remain in the existing modules.  No
process is constructed or launched while this module is imported.
"""

from __future__ import annotations

import inspect
import math
from pathlib import Path
from typing import Any, Callable, Mapping

from coupling.multi_slice_mapping.mapping import LoadRecord, MotionRecord, SliceManifest, RuntimeConfig
from coupling.multi_slice_driver.contract import SliceExchangePaths
from coupling.performance_optimization_v2.coordinator import CoordinatorError, SliceResult, StepIdentity, canonical_hash


class RealSliceAdapterError(RuntimeError):
    """Fail-closed existing OpenFOAM lifecycle adapter error."""


class PersistentOpenFOAMSliceAdapter:
    """Adapt ``PersistentOpenFOAMSliceProcess`` to the Stage100 engine API.

    ``backend`` is created by an authorized factory, but is not started by
    this constructor.  The backend's persistent process is launched only on
    the first target publication after a validated current-time seed.
    """

    def __init__(self, *, backend: Any, manifest: SliceManifest,
                 runtime_config: RuntimeConfig, paths: SliceExchangePaths,
                 initial_seed: Mapping[str, Any] | MotionRecord,
                 slice_id: int) -> None:
        self.backend = backend
        self.manifest = manifest
        self.runtime_config = runtime_config
        self.paths = paths
        self.slice_id = int(slice_id)
        if self.slice_id not in {item.slice_id for item in manifest.slices}:
            raise RealSliceAdapterError("slice_id is not present in manifest")
        self._next_seed: Mapping[str, Any] | MotionRecord = initial_seed
        self._started = False
        self._failed = False
        self._pending_step: int | None = None
        self._pending_time_s: float | None = None
        self.start_count = 0
        self.finalized_steps = 0

    def start(self) -> None:
        if self._started or self._failed:
            raise RealSliceAdapterError(f"slice {self.slice_id} adapter is unavailable")
        # PersistentOpenFOAMSliceProcess starts on its first publish_motion;
        # this adapter start is an ownership/lifecycle registration boundary.
        self._started = True
        self.start_count = 1

    def _motion(self, value: Mapping[str, Any] | MotionRecord, identity: StepIdentity) -> MotionRecord:
        try:
            record = value if isinstance(value, MotionRecord) else MotionRecord.from_mapping(value)
        except Exception as exc:
            raise RealSliceAdapterError(f"slice {self.slice_id} motion schema is invalid") from exc
        if (record.slice_id != self.slice_id or record.step != identity.global_step or
                record.case_id != self.manifest.case_id or
                not math.isclose(record.time_s, identity.time_s, rel_tol=0.0, abs_tol=1e-12)):
            raise RealSliceAdapterError(f"slice {self.slice_id} motion identity mismatch")
        return record

    def advance(self, identity: StepIdentity, motion_payload: Any = None) -> SliceResult:
        if not self._started or self._failed:
            raise RealSliceAdapterError(f"slice {self.slice_id} adapter is unavailable")
        if motion_payload is None:
            self._failed = True
            raise RealSliceAdapterError("C++ worker motion payload is required")
        try:
            seed = self._next_seed
            if hasattr(self.backend, "begin_step"):
                # The persistent OpenFOAM process stores bridge seeds as a
                # mapping because it serializes them into the legacy motion
                # bridge.  Keep MotionRecord as the typed adapter boundary,
                # but convert it explicitly before crossing that boundary.
                seed_payload = seed.to_dict() if isinstance(seed, MotionRecord) else seed
                self.backend.begin_step(seed_payload, seed_step=identity.global_step - 1)
            record = self._motion(motion_payload, identity)
            self.backend.publish_motion(record, self.paths, manifest=self.manifest,
                                        runtime_config=self.runtime_config)
            self.backend.wait_motion_consumed(identity.global_step, identity.time_s,
                                              paths=self.paths, manifest=self.manifest,
                                              runtime_config=self.runtime_config)
            self.backend.advance_one_step(identity.global_step, identity.time_s)
            self.backend.wait_load_ready(identity.global_step, identity.time_s,
                                         paths=self.paths, manifest=self.manifest,
                                         runtime_config=self.runtime_config)
            load = self.backend.read_load(identity.global_step, identity.time_s)
            if not isinstance(load, LoadRecord):
                load = LoadRecord.from_mapping(load, self.manifest.R_GL)
            if (load.slice_id != self.slice_id or load.step != identity.global_step or
                    not math.isclose(load.time_s, identity.time_s, rel_tol=0.0, abs_tol=1e-12)):
                raise RealSliceAdapterError("OpenFOAM force identity mismatch")
            self.backend.publish_load_consumed(identity.global_step, identity.time_s,
                                                paths=self.paths, manifest=self.manifest,
                                                runtime_config=self.runtime_config)
            self._pending_step, self._pending_time_s = identity.global_step, identity.time_s
            self._next_seed = record
            payload = {"slice_id": self.slice_id, "global_step": identity.global_step,
                       "case_local_bridge_step": identity.case_local_bridge_step,
                       "time_s": identity.time_s, "integer_tick": identity.integer_tick,
                       "ack": "consumed", "load": load.to_dict()}
            pid = int(getattr(getattr(self.backend, "process", None), "pid", 0) or 0)
            return SliceResult(self.slice_id, identity, payload, canonical_hash(payload), 0, pid, 0.0)
        except Exception as exc:
            self._failed = True
            raise CoordinatorError(f"slice {self.slice_id} persistent protocol failed: {exc}") from exc

    def finalize_step(self, identity: StepIdentity) -> None:
        if self._failed:
            raise RealSliceAdapterError("cannot finalize a failed slice")
        if self._pending_step != identity.global_step:
            raise RealSliceAdapterError("finalize identity does not match pending slice step")
        self.backend.finish_step(identity.global_step, identity.time_s)
        self._pending_step = self._pending_time_s = None
        self.finalized_steps += 1

    def stop(self) -> None:
        try:
            self.backend.stop()
        finally:
            self._started = False

    @property
    def owned_residual(self) -> int:
        value = getattr(self.backend, "owned_residual", None)
        if value is not None:
            return int(value)
        process = getattr(self.backend, "process", None)
        return int(process is not None and process.poll() is None)


def validate_slice_factory(factory: Callable[[int, Path], Any], *, slice_count: int = 3) -> None:
    """Validate factory shape without constructing or launching a process."""
    if slice_count != 3:
        raise RealSliceAdapterError("Stage100 requires exactly three slices")
    if not callable(factory):
        raise RealSliceAdapterError("slice factory must be callable")
    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError) as exc:
        raise RealSliceAdapterError("slice factory signature is unavailable") from exc
    if len(signature.parameters) < 2:
        raise RealSliceAdapterError("slice factory must accept slice_id and runtime path")
