from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .lifecycle import LifecycleError, OwnedProcessRegistry, ProcessIdentity, launch_owned


class CoordinatorError(RuntimeError):
    """Fail-closed persistent slice/coordinator contract error."""


def canonical_hash(value: Any) -> str:
    return hashlib.sha256((json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()).hexdigest()


@dataclass(frozen=True)
class StepIdentity:
    run_id: str
    case_id: str
    source_global_step: int
    source_time_s: float
    source_tick: int
    global_step: int
    case_local_bridge_step: int
    time_s: float
    integer_tick: int
    request_id: str
    transaction_id: str

    @classmethod
    def create(cls, *, run_id: str, case_id: str, source_global_step: int,
               source_time_s: float, source_tick: int, global_step: int,
               time_s: float, dt_s: float) -> "StepIdentity":
        bridge = int(global_step) - int(source_global_step)
        if bridge <= 0: raise CoordinatorError("target step must follow source step")
        tick = int(round(float(time_s) * 1_000_000_000))
        expected_tick = int(source_tick) + int(round((float(time_s) - float(source_time_s)) * 1_000_000_000))
        if tick != expected_tick: raise CoordinatorError("time/tick mapping mismatch")
        if not math.isclose(float(time_s), float(source_time_s) + bridge * float(dt_s), abs_tol=1e-12):
            raise CoordinatorError("source/target time mapping mismatch")
        return cls(run_id, case_id, source_global_step, source_time_s, source_tick, global_step, bridge, float(time_s), tick,
                   f"stage95_motion_{global_step:08d}_{uuid.uuid4().hex[:10]}", f"stage95_tx_{global_step:08d}_{uuid.uuid4().hex[:10]}")


@dataclass(frozen=True)
class SliceResult:
    slice_id: int
    identity: StepIdentity
    payload: Mapping[str, Any]
    payload_hash: str
    return_code: int
    pid: int
    elapsed_s: float

    def validate(self, expected: StepIdentity) -> None:
        if self.identity != expected: raise CoordinatorError(f"slice {self.slice_id} identity mismatch")
        if self.return_code != 0: raise CoordinatorError(f"slice {self.slice_id} returned {self.return_code}")
        if canonical_hash(self.payload) != self.payload_hash: raise CoordinatorError(f"slice {self.slice_id} payload hash mismatch")
        if not self.payload or any(isinstance(item, float) and not math.isfinite(item) for item in self.payload.values()):
            raise CoordinatorError(f"slice {self.slice_id} non-finite/empty payload")


class PersistentSliceCoordinator:
    """Own one persistent engine per slice and enforce a global barrier."""

    def __init__(self, *, run_id: str, case_id: str, source_global_step: int,
                 source_time_s: float, source_tick: int, dt_s: float,
                 runtime: Path, slice_count: int = 3, parallel: bool = True,
                 engine_factory: Callable[[int, Path], Any] | None = None) -> None:
        if slice_count != 3: raise CoordinatorError("Stage95 requires exactly three slices")
        self.run_id, self.case_id = run_id, case_id; self.source_global_step = int(source_global_step)
        self.source_time_s, self.source_tick, self.dt_s = float(source_time_s), int(source_tick), float(dt_s)
        self.runtime, self.parallel = Path(runtime), bool(parallel); self.runtime.mkdir(parents=True, exist_ok=True)
        self.engine_factory = engine_factory or (lambda sid, path: _UnavailableEngine(sid, path))
        self.registry = OwnedProcessRegistry(); self.engines: dict[int, Any] = {}; self.started = False; self.failed = False
        self.records: list[dict[str, Any]] = []; self.committed_steps: list[int] = []

    def start(self) -> None:
        if self.started or self.failed: raise CoordinatorError("coordinator is already started or terminal")
        for sid in range(3):
            engine = self.engine_factory(sid, self.runtime / f"slice_{sid}")
            engine.start()  # engine owns its process and exposes an audit
            self.engines[sid] = engine
        self.started = True

    def _advance_one(self, sid: int, identity: StepIdentity) -> SliceResult:
        started = time.perf_counter(); engine = self.engines[sid]
        raw = engine.advance(identity)
        if not isinstance(raw, SliceResult):
            raise CoordinatorError(f"slice {sid} did not return SliceResult")
        raw.validate(identity)
        return SliceResult(raw.slice_id, raw.identity, raw.payload, raw.payload_hash, raw.return_code, raw.pid, time.perf_counter() - started)

    def advance_step(self, *, global_step: int, time_s: float) -> dict[str, Any]:
        if not self.started or self.failed: raise CoordinatorError("coordinator unavailable")
        identity = StepIdentity.create(run_id=self.run_id, case_id=self.case_id, source_global_step=self.source_global_step,
                                       source_time_s=self.source_time_s, source_tick=self.source_tick, global_step=global_step,
                                       time_s=time_s, dt_s=self.dt_s)
        try:
            if self.parallel:
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                    futures = {pool.submit(self._advance_one, sid, identity): sid for sid in range(3)}
                    results = [future.result() for future in concurrent.futures.as_completed(futures)]
            else:
                results = [self._advance_one(sid, identity) for sid in range(3)]
            if {item.slice_id for item in results} != {0, 1, 2}: raise CoordinatorError("global barrier missing slice")
            # Commit is deliberately after all three validated results.
            record = {"run_id": self.run_id, "case_id": self.case_id, "global_step": global_step,
                      "case_local_bridge_step": identity.case_local_bridge_step, "time_s": time_s,
                      "integer_tick": identity.integer_tick, "request_id": identity.request_id,
                      "transaction_id": identity.transaction_id, "slice_ids": sorted(item.slice_id for item in results),
                      "payload_hashes": {str(item.slice_id): item.payload_hash for item in results}, "barrier_passed": True,
                      "committed": True}
            path = self.runtime / "checkpoint" / f"checkpoint_{global_step:08d}.json"; path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp"); temporary.write_text(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8"); os.replace(temporary, path)
            self.records.append(record); self.committed_steps.append(int(global_step)); return record
        except Exception as exc:
            self.failed = True
            raise CoordinatorError(str(exc)) from exc

    def stop(self) -> None:
        for engine in self.engines.values():
            try: engine.stop()
            except Exception as exc: self.failed = True; raise CoordinatorError(str(exc)) from exc
        self.started = False

    @property
    def owned_residual(self) -> int:
        return self.registry.residual + sum(int(getattr(engine, "owned_residual", 0)) for engine in self.engines.values())


class _UnavailableEngine:
    def __init__(self, sid: int, path: Path): self.slice_id, self.path = sid, path
    def start(self) -> None: raise CoordinatorError("no real OpenFOAM coordinator is installed")
    def advance(self, identity: StepIdentity) -> SliceResult: raise CoordinatorError("no real OpenFOAM coordinator is installed")
    def stop(self) -> None: return None
    @property
    def owned_residual(self) -> int: return 0


class OpenFOAMProcessEngine:
    """One-process-per-slice adapter for a user-session OpenFOAM command.

    The engine owns no physics logic. The supplied callbacks are responsible
    for the existing motion/ack/force protocol and must return the canonical
    force payload for the identity. A callback failure poisons the caller's
    coordinator; this class never retries or starts a second process.
    """

    def __init__(self, *, slice_id: int, case_dir: Path, command: Sequence[str], runtime: Path,
                 publish_motion: Callable[[StepIdentity], None], wait_consumed: Callable[[StepIdentity], None],
                 read_force: Callable[[StepIdentity], Mapping[str, Any]],
                 launcher: Callable[..., Any] | None = None, registry: OwnedProcessRegistry | None = None) -> None:
        self.slice_id, self.case_dir, self.command, self.runtime = int(slice_id), Path(case_dir), list(command), Path(runtime)
        self.publish_motion, self.wait_consumed, self.read_force = publish_motion, wait_consumed, read_force
        self.launcher = launcher; self.registry = registry or OwnedProcessRegistry(); self.process: Any = None; self.identity: ProcessIdentity | None = None
        self.failed = False; self.closed = False; self.start_count = 0; self.stop_count = 0

    def start(self) -> None:
        if self.process is not None or self.failed or self.closed: raise CoordinatorError(f"slice {self.slice_id} engine unavailable")
        self.case_dir.mkdir(parents=True, exist_ok=True); self.runtime.mkdir(parents=True, exist_ok=True)
        launch = self.launcher
        if launch is None:
            import subprocess
            launch = subprocess.Popen
        self.process, self.identity = launch_owned(registry=self.registry, component=f"openfoam_slice_{self.slice_id}",
            command=self.command, cwd=self.case_dir, launcher=launch)
        self.start_count += 1

    def advance(self, identity: StepIdentity) -> SliceResult:
        if self.process is None or self.identity is None or self.failed: raise CoordinatorError(f"slice {self.slice_id} engine unavailable")
        if getattr(self.process, "poll", lambda: None)() not in (None, 0):
            self.failed = True; raise CoordinatorError(f"slice {self.slice_id} OpenFOAM exited before advance")
        started = time.perf_counter()
        try:
            self.publish_motion(identity); self.wait_consumed(identity); payload = dict(self.read_force(identity))
            digest = canonical_hash(payload)
            return SliceResult(self.slice_id, identity, payload, digest, 0, self.identity.pid, time.perf_counter() - started)
        except Exception as exc:
            self.failed = True; raise CoordinatorError(f"slice {self.slice_id} advance failed: {exc}") from exc

    def stop(self) -> None:
        if self.process is None or self.identity is None: return
        try: self.registry.close(self.identity, self.process)
        finally: self.stop_count += 1; self.process = None; self.closed = True

    @property
    def owned_residual(self) -> int: return self.registry.residual
