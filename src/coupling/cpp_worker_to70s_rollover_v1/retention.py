"""Crash-safe rolling retention for long persistent OpenFOAM runs.

The store is deliberately independent from the CFD coordinator.  A caller
must commit its immutable checkpoint and compact journal row before this
module is allowed to remove any old field directory.  Only artifacts inside
the exact fresh runtime are eligible for removal.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class RetentionError(RuntimeError):
    """Raised when retention cannot prove a safe, identity-matched cleanup."""


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _is_reparse(path: Path) -> bool:
    try:
        attrs = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError as exc:
        raise RetentionError(f"cannot inspect retention target: {path}") from exc
    return path.is_symlink() or bool(attrs & 0x400)


def _assert_child(path: Path, root: Path) -> None:
    root_resolved = root.resolve()
    candidate = path.resolve()
    try:
        inside = os.path.commonpath((str(candidate), str(root_resolved))) == str(root_resolved)
    except ValueError:
        inside = False
    if not inside or candidate == root_resolved or _is_reparse(path):
        raise RetentionError(f"retention target is outside owned runtime: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(_canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class RetentionPolicy:
    source_step: int = 0
    source_time_s: float = 0.0
    dt_s: float = 0.00125
    keep_full_steps: int = 40
    keep_restart_checkpoints: int = 2
    min_free_bytes: int = 50 * 1024 ** 3

    def validate(self) -> None:
        if isinstance(self.source_step, bool) or self.source_step < 0:
            raise RetentionError("source_step must be a non-negative integer")
        if not math.isfinite(self.source_time_s) or self.source_time_s < 0:
            raise RetentionError("source_time_s must be finite and non-negative")
        if not math.isfinite(self.dt_s) or self.dt_s <= 0:
            raise RetentionError("dt_s must be positive and finite")
        if self.keep_full_steps < 1 or self.keep_restart_checkpoints < 2:
            raise RetentionError("retention windows are too small for recovery")
        if self.min_free_bytes < 0:
            raise RetentionError("min_free_bytes must be non-negative")


class RollingRetentionStore:
    """Manage exact-step retention for one fresh runtime and result tree."""

    def __init__(self, *, runtime: Path, results: Path, run_id: str, case_id: str,
                 policy: RetentionPolicy) -> None:
        policy.validate()
        self.runtime = Path(runtime).resolve()
        self.results = Path(results).resolve()
        self.run_id = str(run_id)
        self.case_id = str(case_id)
        self.policy = policy
        self.journal = self.results / "compact_step_journal.jsonl"
        self.index = self.runtime / "checkpoint" / "latest_restart.json"
        self.previous_index = self.runtime / "checkpoint" / "previous_restart.json"
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.results.mkdir(parents=True, exist_ok=True)

    def _free_bytes(self) -> int:
        return int(shutil.disk_usage(self.runtime.drive or self.runtime.anchor).free)

    def assert_disk_headroom(self) -> None:
        free = self._free_bytes()
        if free < self.policy.min_free_bytes:
            raise RetentionError(
                f"disk headroom below fail-closed threshold: {free} < {self.policy.min_free_bytes}"
            )

    def _expected_time(self, step: int) -> float:
        return self.policy.source_time_s + (step - self.policy.source_step) * self.policy.dt_s

    def _expected_tick(self, step: int) -> int:
        return int(round(self._expected_time(step) * 1_000_000_000))

    def _validate_identity(self, *, step: int, time_s: float, integer_tick: int) -> None:
        if isinstance(step, bool) or step <= self.policy.source_step:
            raise RetentionError("retention step is not a target step")
        if not math.isfinite(float(time_s)) or abs(float(time_s) - self._expected_time(step)) > 1e-12:
            raise RetentionError("retention time does not match global step")
        if int(integer_tick) != self._expected_tick(step):
            raise RetentionError("retention tick does not match global step")

    def append_journal(self, row: Mapping[str, Any]) -> None:
        """Durably append one compact identity row before any deletion."""
        required = {"run_id", "case_id", "global_step", "time_s", "integer_tick", "committed"}
        if required - row.keys():
            raise RetentionError("compact journal row is incomplete")
        if row["run_id"] != self.run_id or row["case_id"] != self.case_id:
            raise RetentionError("compact journal identity mismatch")
        self._validate_identity(step=int(row["global_step"]), time_s=float(row["time_s"]),
                                integer_tick=int(row["integer_tick"]))
        if row["committed"] is not True:
            raise RetentionError("only committed rows may enter the retention journal")
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with self.journal.open("ab") as stream:
            stream.write(_canonical(dict(row)))
            stream.flush()
            os.fsync(stream.fileno())

    def _checkpoint(self, step: int) -> Path:
        return self.runtime / "checkpoint" / f"checkpoint_{step:08d}.json"

    def _verify_checkpoint(self, *, step: int, time_s: float, integer_tick: int) -> Path:
        path = self._checkpoint(step)
        if not path.is_file() or _is_reparse(path):
            raise RetentionError(f"latest checkpoint is missing: {path}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RetentionError(f"latest checkpoint is unreadable: {path}") from exc
        if (value.get("run_id") != self.run_id or value.get("case_id") != self.case_id or
                value.get("global_step") != step or value.get("committed") is not True):
            raise RetentionError("latest checkpoint identity/commit mismatch")
        if abs(float(value.get("time_s", float("nan"))) - time_s) > 1e-12:
            raise RetentionError("latest checkpoint time mismatch")
        if int(value.get("integer_tick", -1)) != integer_tick:
            raise RetentionError("latest checkpoint tick mismatch")
        return path

    def _time_name(self, time_s: float) -> str:
        return format(float(time_s), ".12g")

    def _remove_path(self, path: Path, *, root: Path, removed: list[str]) -> None:
        if not path.exists():
            return
        _assert_child(path, root)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        if path.exists():
            raise RetentionError(f"retention target survived deletion: {path}")
        removed.append(str(path))

    def _prune_exact_step(self, *, step: int, time_s: float, removed: list[str]) -> None:
        checkpoint = self._checkpoint(step)
        self._remove_path(checkpoint, root=self.runtime / "checkpoint", removed=removed)
        commit = self.runtime / "commit_journal" / f"commit_{step:08d}.json"
        self._remove_path(commit, root=self.runtime / "commit_journal", removed=removed)
        time_name = self._time_name(time_s)
        for sid in range(3):
            case_root = self.runtime / "cases" / f"slice_{sid:04d}"
            if not case_root.is_dir() or _is_reparse(case_root):
                continue
            candidate = case_root / time_name
            self._remove_path(candidate, root=case_root, removed=removed)
        for path in self.runtime.glob("exchange/**/*"):
            if path.is_file() and f"step{step:08d}" in path.name:
                self._remove_path(path, root=self.runtime / "exchange", removed=removed)

    def _prune_numeric_case_times(self, *, latest_step: int, removed: list[str]) -> None:
        cutoff = latest_step - self.policy.keep_full_steps
        for sid in range(3):
            case_root = self.runtime / "cases" / f"slice_{sid:04d}"
            if not case_root.is_dir() or _is_reparse(case_root):
                continue
            for candidate in list(case_root.iterdir()):
                try:
                    value = float(candidate.name)
                except ValueError:
                    continue
                step = self.policy.source_step + int(round((value - self.policy.source_time_s) / self.policy.dt_s))
                if candidate.name == "0" or step <= self.policy.source_step or step > cutoff:
                    continue
                expected = self._expected_time(step)
                if abs(value - expected) > 1e-12:
                    raise RetentionError(f"case time directory has ambiguous step identity: {candidate}")
                self._remove_path(candidate, root=case_root, removed=removed)

    def _prune_postprocessing_times(self, *, latest_step: int, removed: list[str]) -> None:
        """Remove old numeric postProcessing time directories after journaling."""
        cutoff = latest_step - self.policy.keep_full_steps
        for sid in range(3):
            post_root = self.runtime / "cases" / f"slice_{sid:04d}" / "postProcessing"
            if not post_root.is_dir() or _is_reparse(post_root):
                continue
            for candidate in list(post_root.rglob("*")):
                if not candidate.is_dir() or _is_reparse(candidate):
                    continue
                try:
                    value = float(candidate.name)
                except ValueError:
                    continue
                step = self.policy.source_step + int(round((value - self.policy.source_time_s) / self.policy.dt_s))
                if step <= self.policy.source_step or step > cutoff:
                    continue
                if abs(value - self._expected_time(step)) > 1e-12:
                    raise RetentionError(f"postProcessing time directory has ambiguous identity: {candidate}")
                self._remove_path(candidate, root=self.runtime / "cases" / f"slice_{sid:04d}", removed=removed)

    def recoverable_restart(self) -> dict[str, Any]:
        """Return the newest verified restart pointer, falling back once."""
        for pointer in (self.index, self.previous_index):
            if not pointer.is_file() or _is_reparse(pointer):
                continue
            try:
                value = json.loads(pointer.read_text(encoding="utf-8"))
                checkpoint = Path(str(value["checkpoint"]))
                if (value.get("run_id") != self.run_id or value.get("case_id") != self.case_id or
                        int(value["global_step"]) <= self.policy.source_step):
                    continue
                if checkpoint.resolve().parent != (self.runtime / "checkpoint").resolve():
                    continue
                if not checkpoint.is_file() or _is_reparse(checkpoint):
                    continue
                if _sha256(checkpoint) != value.get("checkpoint_sha256"):
                    continue
                self._verify_checkpoint(
                    step=int(value["global_step"]), time_s=float(value["time_s"]),
                    integer_tick=int(value["integer_tick"]),
                )
                return {**value, "pointer": str(pointer), "recovered": pointer != self.index}
            except (KeyError, TypeError, ValueError, OSError, RetentionError):
                continue
        raise RetentionError("no verified latest or previous restart pointer is available")

    def commit_step(self, *, step: int, time_s: float, integer_tick: int,
                    checkpoint: Mapping[str, Any], compact_row: Mapping[str, Any]) -> dict[str, Any]:
        """Commit a step, publish restart pointers, then evict old artifacts."""
        self.assert_disk_headroom()
        self._validate_identity(step=step, time_s=time_s, integer_tick=integer_tick)
        if checkpoint.get("run_id") != self.run_id or checkpoint.get("case_id") != self.case_id:
            raise RetentionError("checkpoint identity mismatch")
        checkpoint_path = self._checkpoint(step)
        _write_atomic(checkpoint_path, checkpoint)
        self._verify_checkpoint(step=step, time_s=time_s, integer_tick=integer_tick)
        self.append_journal(compact_row)
        previous = self.index
        if previous.is_file():
            _write_atomic(self.previous_index, json.loads(previous.read_text(encoding="utf-8")))
        latest = {"run_id": self.run_id, "case_id": self.case_id, "global_step": step,
                  "time_s": time_s, "integer_tick": integer_tick,
                  "checkpoint": str(checkpoint_path), "checkpoint_sha256": _sha256(checkpoint_path),
                  "published_ns": time.time_ns()}
        _write_atomic(self.index, latest)
        removed: list[str] = []
        evict_step = step - self.policy.keep_full_steps
        if evict_step > self.policy.source_step:
            self._prune_exact_step(step=evict_step, time_s=self._expected_time(evict_step), removed=removed)
        self._prune_numeric_case_times(latest_step=step, removed=removed)
        self._prune_postprocessing_times(latest_step=step, removed=removed)
        self.assert_disk_headroom()
        return {"global_step": step, "time_s": time_s, "integer_tick": integer_tick,
                "retained_full_steps": self.policy.keep_full_steps,
                "latest_restart": str(self.index), "previous_restart": str(self.previous_index),
                "removed": removed, "free_bytes_after": self._free_bytes()}
