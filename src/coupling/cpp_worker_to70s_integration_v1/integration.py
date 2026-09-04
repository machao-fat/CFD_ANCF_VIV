"""Fail-closed offline integration model for the long-window campaign.

This module deliberately models the existing worker/case contracts without
launching a worker, OpenFOAM, WSL, MATLAB, or CFD process.  It is an adapter
test for identity, barrier, checkpoint, and retention sequencing only.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from coupling.cpp_worker_to70s_rollover_v1.retention import (
    RetentionPolicy,
    RetentionError,
    RollingRetentionStore,
)


class IntegrationError(RuntimeError):
    """Raised when the simulated integration contract is violated."""


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class MappingContract:
    source_step: int = 0
    source_time_s: float = 0.0
    dt_s: float = 0.00125
    target_step: int = 56_000
    slice_count: int = 3

    def expected_time(self, global_step: int) -> float:
        return self.source_time_s + (global_step - self.source_step) * self.dt_s

    def expected_tick(self, global_step: int) -> int:
        return int(round(self.expected_time(global_step) * 1_000_000_000))

    def validate(self, *, global_step: int, bridge_step: int,
                 time_s: float, integer_tick: int) -> None:
        if global_step <= self.source_step:
            raise IntegrationError("global step is not a target step")
        if bridge_step != global_step - self.source_step or bridge_step <= 0:
            raise IntegrationError("case-local bridge step is not mapped from global step")
        expected_time = self.expected_time(global_step)
        if not math.isfinite(time_s) or abs(time_s - expected_time) > 1e-12:
            raise IntegrationError("time does not match canonical mapping")
        if integer_tick != self.expected_tick(global_step):
            raise IntegrationError("integer tick does not match canonical mapping")


class OfflineThreeSliceCampaign:
    """Simulate a bounded prefix while exercising the real retention layer."""

    def __init__(self, *, runtime: Path, results: Path, run_id: str, case_id: str,
                 mapping: MappingContract | None = None) -> None:
        self.mapping = mapping or MappingContract()
        if self.mapping.slice_count != 3:
            raise IntegrationError("integration scope is exactly three slices")
        self.runtime = Path(runtime).resolve()
        self.results = Path(results).resolve()
        self.run_id = run_id
        self.case_id = case_id
        self.store = RollingRetentionStore(
            runtime=self.runtime, results=self.results, run_id=run_id, case_id=case_id,
            policy=RetentionPolicy(source_step=self.mapping.source_step,
                                   source_time_s=self.mapping.source_time_s,
                                   dt_s=self.mapping.dt_s, keep_full_steps=40,
                                   keep_restart_checkpoints=2, min_free_bytes=0),
        )
        self.last_global_step = self.mapping.source_step
        self.last_bridge_step = 0
        self.commit_count = 0
        self.barrier_count = 0
        self.ack_count = 0
        self.worker_start_count = 1
        self.slice_start_count = [1, 1, 1]
        self.process_registry = [
            {"component": "cpp_worker", "pid": 90001, "parent_pid": os.getpid(),
             "command_line": ["mock-cpp-worker"], "owned": True,
             "return_code": 0, "cleanup_result": "closed"},
            *[{"component": "openfoam_slice", "slice_id": sid, "pid": 90100 + sid,
               "parent_pid": os.getpid(), "command_line": ["mock-openfoam", str(sid)],
               "owned": True, "return_code": 0, "cleanup_result": "closed"}
              for sid in range(3)],
        ]

    def _materialize_source(self) -> None:
        for sid in range(self.mapping.slice_count):
            source = self.runtime / "cases" / f"slice_{sid:04d}" / "0"
            source.mkdir(parents=True, exist_ok=True)
            (source / "U").write_text("offline-source\n", encoding="utf-8")

    def _state(self, step: int) -> dict[str, Any]:
        state = {"q": [float(step), 0.0], "qdot": [0.0, 0.0], "qddot": [0.0, 0.0]}
        return {"global_step": step, "time_s": self.mapping.expected_time(step),
                "integer_tick": self.mapping.expected_tick(step), "state": state,
                "state_sha256": _sha(state)}

    def _slice_exchange(self, *, step: int, bridge: int, time_s: float) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for sid in range(self.mapping.slice_count):
            root = self.runtime / "exchange" / f"slice_{sid:04d}"
            motion = root / "motion" / f"motion_step{step:08d}.json"
            consumed = root / "consumed" / f"motion_step{step:08d}.ack.json"
            load = root / "load" / f"load_step{step:08d}.json"
            load_ack = root / "load_consumed" / f"load_step{step:08d}.ack.json"
            payload = {"run_id": self.run_id, "case_id": self.case_id, "slice_id": sid,
                       "global_step": step, "case_local_bridge_step": bridge,
                       "time_s": time_s, "integer_tick": self.mapping.expected_tick(step),
                       "sequence": bridge, "producer": "offline_scheduler",
                       "consumer": f"offline_slice_{sid}", "payload_sha256": _sha([sid, step, time_s])}
            for path in (motion, consumed, load, load_ack):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(_canonical(payload))
            rows.append({"slice_id": sid, "motion_consumed": True, "load_ready": True,
                         "load_consumed": True, "identity": payload})
        return rows

    def commit_one(self, global_step: int) -> None:
        bridge = global_step - self.mapping.source_step
        time_s = self.mapping.expected_time(global_step)
        tick = self.mapping.expected_tick(global_step)
        self.mapping.validate(global_step=global_step, bridge_step=bridge,
                              time_s=time_s, integer_tick=tick)
        if global_step != self.last_global_step + 1 or bridge != self.last_bridge_step + 1:
            raise IntegrationError("step lineage is not monotonic")
        slices = self._slice_exchange(step=global_step, bridge=bridge, time_s=time_s)
        if len(slices) != 3 or not all(row["motion_consumed"] and row["load_ready"] and row["load_consumed"] for row in slices):
            raise IntegrationError("three-slice barrier did not complete")
        self.barrier_count += 1
        self.ack_count += 3
        for sid in range(3):
            case_time = self.runtime / "cases" / f"slice_{sid:04d}" / format(time_s, ".12g")
            case_time.mkdir(parents=True, exist_ok=True)
            (case_time / "U").write_text(f"offline-step={global_step}\n", encoding="utf-8")
        commit = self.runtime / "commit_journal" / f"commit_{global_step:08d}.json"
        commit.parent.mkdir(parents=True, exist_ok=True)
        commit.write_bytes(_canonical({"run_id": self.run_id, "case_id": self.case_id,
                                       "global_step": global_step, "committed": True,
                                       "barrier_passed": True}))
        artifact = self.runtime / "exchange" / "slice_0000" / "force_artifacts" / f"force_step{global_step:08d}.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(_canonical({"run_id": self.run_id, "case_id": self.case_id,
                                         "global_step": global_step, "integer_tick": tick}))
        state = self._state(global_step)
        checkpoint = {"run_id": self.run_id, "case_id": self.case_id,
                      "global_step": global_step, "time_s": time_s,
                      "integer_tick": tick, "committed": True,
                      "slice_ids": [0, 1, 2], "barrier_passed": True,
                      "checkpoint_metadata": {"ancf_restart_state": state}}
        row = {"run_id": self.run_id, "case_id": self.case_id,
               "global_step": global_step, "case_local_bridge_step": bridge,
               "time_s": time_s, "integer_tick": tick, "slice_ids": [0, 1, 2],
               "barrier_passed": True, "committed": True,
               "restart_state_sha256": state["state_sha256"]}
        self.store.commit_step(step=global_step, time_s=time_s, integer_tick=tick,
                               checkpoint=checkpoint, compact_row=row)
        self.last_global_step = global_step
        self.last_bridge_step = bridge
        self.commit_count += 1

    def run(self, simulated_steps: int = 120) -> dict[str, Any]:
        if simulated_steps < 1:
            raise IntegrationError("simulated_steps must be positive")
        self._materialize_source()
        for step in range(self.mapping.source_step + 1,
                          self.mapping.source_step + simulated_steps + 1):
            self.commit_one(step)
        restart = self.store.recoverable_restart()
        case_entries = []
        for sid in range(3):
            case_entries.append(sorted(item.name for item in
                                        (self.runtime / "cases" / f"slice_{sid:04d}").iterdir()))
        return {
            "simulated_steps": simulated_steps,
            "source": {"global_step": self.mapping.source_step,
                        "time_s": self.mapping.source_time_s},
            "target": {"global_step": self.mapping.target_step,
                        "time_s": self.mapping.expected_time(self.mapping.target_step),
                        "integer_tick": self.mapping.expected_tick(self.mapping.target_step)},
            "last_committed": {"global_step": self.last_global_step,
                                "case_local_bridge_step": self.last_bridge_step,
                                "time_s": self.mapping.expected_time(self.last_global_step),
                                "integer_tick": self.mapping.expected_tick(self.last_global_step)},
            "commit_count": self.commit_count, "barrier_count": self.barrier_count,
            "slice_ack_count": self.ack_count, "case_entries_per_slice": [len(row) for row in case_entries],
            "checkpoint_count": len(list((self.runtime / "checkpoint").glob("checkpoint_*.json"))),
            "exchange_artifact_count": len(list((self.runtime / "exchange").rglob("force_step*.json"))),
            "restart": restart, "process_registry": self.process_registry,
            "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
            "owned_residual": 0,
        }
