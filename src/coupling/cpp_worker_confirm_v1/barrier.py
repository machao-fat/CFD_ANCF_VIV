"""Independent Stage100 three-slice global barrier."""

from __future__ import annotations

import concurrent.futures
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Mapping, Callable

from coupling.performance_optimization_v2.coordinator import CoordinatorError, SliceResult, StepIdentity


class Stage100SliceBarrier:
    def __init__(self, *, run_id: str, case_id: str, source_global_step: int,
                 source_time_s: float, source_tick: int, dt_s: float,
                 runtime: Path, engine_factory: Callable[[int, Path], Any],
                 parallel: bool = True) -> None:
        self.run_id, self.case_id = str(run_id), str(case_id)
        self.source_global_step, self.source_time_s = int(source_global_step), float(source_time_s)
        self.source_tick, self.dt_s = int(source_tick), float(dt_s)
        self.runtime, self.engine_factory = Path(runtime), engine_factory
        self.parallel = bool(parallel)
        self.engines: dict[int, Any] = {}
        self.records: list[dict[str, Any]] = []
        self.last_payloads: dict[int, Any] = {}
        self.last_loads: dict[int, Any] = {}
        self._prepared: tuple[StepIdentity, list[SliceResult]] | None = None
        self.started = False
        self.failed = False

    def _reject_unresolved_journals(self) -> None:
        """Reject interrupted transactions before any slice can be started."""
        journal_root = self.runtime / "commit_journal"
        if not journal_root.is_dir():
            return
        for path in sorted(journal_root.glob("commit_*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise CoordinatorError(f"commit journal is unreadable: {path.name}") from exc
            if not isinstance(value, Mapping) or value.get("schema_version") != "stage100_commit_journal_v1":
                raise CoordinatorError(f"commit journal schema is invalid: {path.name}")
            state = value.get("state")
            if state == "committed":
                identity = value.get("identity")
                if (not isinstance(identity, Mapping) or identity.get("run_id") != self.run_id or
                        identity.get("case_id") != self.case_id or
                        isinstance(identity.get("global_step"), bool) or
                        not isinstance(identity.get("global_step"), int)):
                    raise CoordinatorError(f"committed journal identity is invalid: {path.name}")
            else:
                raise CoordinatorError(f"unresolved commit journal prevents runtime reuse: {path.name}")

    def start(self) -> None:
        if self.started or self.failed:
            raise CoordinatorError("Stage100 barrier is already started or terminal")
        self._reject_unresolved_journals()
        try:
            for sid in range(3):
                engine = self.engine_factory(sid, self.runtime / f"slice_{sid}")
                engine.start()
                self.engines[sid] = engine
        except Exception as exc:
            self.failed = True
            for engine in self.engines.values():
                try:
                    engine.stop()
                except Exception:
                    pass
            raise CoordinatorError(f"Stage100 slice startup failed and was cleaned: {exc}") from exc
        self.started = True

    def _one(self, sid: int, identity: StepIdentity, motion: Any) -> SliceResult:
        started = time.perf_counter()
        try:
            result = self.engines[sid].advance(identity, motion)
        except Exception as exc:
            raise CoordinatorError(f"slice {sid} advance failed: {exc}") from exc
        if not isinstance(result, SliceResult):
            raise CoordinatorError(f"slice {sid} returned an invalid result")
        result.validate(identity)
        def finite(value: Any) -> bool:
            if isinstance(value, float):
                return math.isfinite(value)
            if isinstance(value, Mapping):
                return all(finite(item) for item in value.values())
            if isinstance(value, (list, tuple)):
                return all(finite(item) for item in value)
            return True
        if not finite(result.payload):
            raise CoordinatorError(f"slice {sid} payload contains NaN/Inf")
        return SliceResult(result.slice_id, result.identity, result.payload,
                           result.payload_hash, result.return_code, result.pid,
                           time.perf_counter() - started)

    def prepare_step(self, *, global_step: int, time_s: float,
                     motion_by_slice: Mapping[int, Any],
                     identity: StepIdentity | None = None) -> dict[str, Any]:
        if not self.started or self.failed or self._prepared is not None:
            raise CoordinatorError("Stage100 barrier is unavailable or already prepared")
        if set(motion_by_slice) != {0, 1, 2}:
            self.failed = True
            raise CoordinatorError("Stage100 requires exactly one motion payload per slice")
        if identity is None:
            identity = StepIdentity.create(run_id=self.run_id, case_id=self.case_id,
                source_global_step=self.source_global_step, source_time_s=self.source_time_s,
                source_tick=self.source_tick, global_step=global_step, time_s=time_s, dt_s=self.dt_s)
        if (identity.run_id != self.run_id or identity.case_id != self.case_id or
                identity.global_step != global_step or
                not abs(identity.time_s - float(time_s)) <= 1e-12):
            self.failed = True
            raise CoordinatorError("Stage100 supplied identity is inconsistent")
        try:
            if self.parallel:
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                    futures = {pool.submit(self._one, sid, identity, motion_by_slice[sid]): sid for sid in range(3)}
                    results = [future.result() for future in concurrent.futures.as_completed(futures)]
            else:
                results = [self._one(sid, identity, motion_by_slice[sid]) for sid in range(3)]
            if {item.slice_id for item in results} != {0, 1, 2}:
                raise CoordinatorError("Stage100 global barrier did not receive all slices")
            self._prepared = (identity, results)
            self.last_payloads = {item.slice_id: item.payload for item in results}
            self.last_loads = {item.slice_id: (item.payload.get("load") if isinstance(item.payload, Mapping) else None)
                               for item in results}
            return {"run_id": self.run_id, "case_id": self.case_id,
                    "global_step": global_step, "case_local_bridge_step": identity.case_local_bridge_step,
                    "time_s": time_s, "integer_tick": identity.integer_tick,
                    "request_id": identity.request_id, "transaction_id": identity.transaction_id,
                    "slice_ids": sorted(item.slice_id for item in results),
                    "slice_payloads": {str(item.slice_id): item.payload for item in results},
                    "slice_payload_hashes": {str(item.slice_id): item.payload_hash for item in results},
                    "payload_hashes": {str(item.slice_id): item.payload_hash for item in results},
                    "barrier_passed": True, "prepared": True, "committed": False}
        except Exception as exc:
            self.failed = True
            raise CoordinatorError(str(exc)) from exc

    def commit_prepared(self, *, worker_response: Mapping[str, Any] | None = None,
                        checkpoint_metadata: Mapping[str, Any] | None = None,
                        commit_callback: Callable[[], None] | None = None,
                        commit_prepare_callback: Callable[[], None] | None = None,
                        rollback_callback: Callable[[], None] | None = None) -> dict[str, Any]:
        if not self.started or self.failed or self._prepared is None:
            raise CoordinatorError("Stage100 barrier has no prepared step")
        identity, results = self._prepared
        try:
            record: dict[str, Any] = {
                "run_id": self.run_id, "case_id": self.case_id,
                "global_step": identity.global_step, "case_local_bridge_step": identity.case_local_bridge_step,
                "time_s": identity.time_s, "integer_tick": identity.integer_tick,
                "request_id": identity.request_id, "transaction_id": identity.transaction_id,
                "slice_ids": sorted(item.slice_id for item in results),
                "slice_payloads": {str(item.slice_id): item.payload for item in results},
                "slice_payload_hashes": {str(item.slice_id): item.payload_hash for item in results},
                "payload_hashes": {str(item.slice_id): item.payload_hash for item in results},
                "barrier_passed": True, "committed": False,
            }
            if worker_response is not None:
                record["worker_response"] = dict(worker_response)
            if checkpoint_metadata is not None:
                record["checkpoint_metadata"] = json.loads(json.dumps(dict(checkpoint_metadata), allow_nan=False))
            path = self.runtime / "checkpoint" / f"checkpoint_{identity.global_step:08d}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
            journal_path = self.runtime / "commit_journal" / f"commit_{identity.global_step:08d}.json"
            journal_path.parent.mkdir(parents=True, exist_ok=True)
            finalized: list[int] = []
            try:
                # Persist intent before callbacks or external owners.  OpenFOAM
                # may already have advanced after target-motion consumption;
                # this journal deliberately enforces terminal fail-closed
                # handling rather than claiming a rollback is possible.
                journal = {"schema_version": "stage100_commit_journal_v1", "state": "prepared",
                           "identity": {"run_id": identity.run_id, "case_id": identity.case_id,
                                        "global_step": identity.global_step,
                                        "case_local_bridge_step": identity.case_local_bridge_step,
                                        "time_s": identity.time_s, "integer_tick": identity.integer_tick,
                                        "request_id": identity.request_id, "transaction_id": identity.transaction_id},
                           "finalized_slice_ids": finalized, "checkpoint": str(path)}
                journal_path.write_text(json.dumps(journal, ensure_ascii=True, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
                with journal_path.open("r+b") as stream:
                    os.fsync(stream.fileno())
                for result in results:
                    preparer = getattr(self.engines[result.slice_id], "prepare_finalize_step", None)
                    if preparer is not None:
                        preparer(identity)
                if commit_prepare_callback is not None:
                    commit_prepare_callback()
                temporary.write_text(json.dumps(record, ensure_ascii=True, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
                with temporary.open("r+b") as stream:
                    os.fsync(stream.fileno())
                for result in results:
                    finalizer = getattr(self.engines[result.slice_id], "finalize_step", None)
                    if finalizer is not None:
                        finalizer(identity)
                    finalized.append(result.slice_id)
                if commit_callback is not None:
                    commit_callback()
                record["committed"] = True
                temporary.write_text(json.dumps(record, ensure_ascii=True, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
                with temporary.open("r+b") as stream:
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                journal["state"] = "committed"
                journal["finalized_slice_ids"] = finalized
                journal_path.write_text(json.dumps(journal, ensure_ascii=True, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
                with journal_path.open("r+b") as stream:
                    os.fsync(stream.fileno())
            finally:
                temporary.unlink(missing_ok=True)
            self.records.append(record)
            self._prepared = None
            return record
        except Exception as exc:
            if rollback_callback is not None:
                try:
                    rollback_callback()
                except Exception as rollback_exc:
                    exc = RuntimeError(f"{exc}; rollback failed: {rollback_exc}")
            # Notify every participant that the global transaction is
            # terminal.  For real persistent OpenFOAM this abandons the
            # runtime; it is not a physical rollback and the aborted journal
            # prevents any later resume from the partial state.
            for sid in reversed(locals().get("finalized", [])):
                try:
                    rollback = getattr(self.engines[sid], "rollback_step", None)
                    if callable(rollback):
                        rollback(identity)
                except Exception as rollback_exc:
                    exc = RuntimeError(f"{exc}; slice {sid} rollback failed: {rollback_exc}")
            try:
                failure = {"schema_version": "stage100_commit_journal_v1", "state": "aborted",
                           "error": str(exc), "finalized_slice_ids": locals().get("finalized", []),
                           "global_step": identity.global_step,
                           "recovery": "runtime_terminal_no_resume"}
                journal_path.write_text(json.dumps(failure, ensure_ascii=True, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
            except Exception:
                pass
            self.failed = True
            raise CoordinatorError(str(exc)) from exc

    @property
    def prepared_results(self) -> tuple[SliceResult, ...]:
        """Return the current prepared slice results without exposing state internals."""
        if self._prepared is None:
            raise CoordinatorError("Stage100 barrier has no prepared results")
        return tuple(sorted(self._prepared[1], key=lambda item: item.slice_id))

    def advance_step(self, *, global_step: int, time_s: float,
                     motion_by_slice: Mapping[int, Any]) -> dict[str, Any]:
        self.prepare_step(global_step=global_step, time_s=time_s, motion_by_slice=motion_by_slice)
        return self.commit_prepared()

    def stop(self) -> None:
        errors = []
        for engine in self.engines.values():
            try:
                engine.stop()
            except Exception as exc:
                errors.append(str(exc))
        self.started = False
        if errors:
            self.failed = True
            raise CoordinatorError("; ".join(errors))

    @property
    def owned_residual(self) -> int:
        return sum(int(getattr(engine, "owned_residual", 0)) for engine in self.engines.values())
