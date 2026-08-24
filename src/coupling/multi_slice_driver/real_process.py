"""Freshness and motion-bridge primitives for the bounded real-process smoke.

The formal scheduler transaction stays 0.2.1.  This module only handles the
explicit compatibility view consumed by the unchanged stage-three
``ancfFileMotion`` library and the observation of process-owned force output.
It intentionally does not alter the production OpenFOAM library.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class RealProcessFreshnessError(RuntimeError):
    """Raised when a real-process artifact cannot be proven current."""


@dataclass(frozen=True)
class BridgeSnapshot:
    """The old-reader view corresponding to one formal 0.2.1 motion record."""

    bridge_step: int
    bridge_time_s: float
    payload_path: Path
    ready_path: Path
    published_ns: int


@dataclass(frozen=True)
class FileFingerprint:
    path: Path
    exists: bool
    size: int
    mtime_ns: int
    sha256: str | None = None


@dataclass(frozen=True)
class ExactForce:
    time_s: float
    force_N: tuple[float, float, float]
    size: int
    mtime_ns: int


_FORCE_RE = re.compile(r"^\s*([^\s]+)\s+\(\(([^)]*)\)\s+\(([^)]*)\)")
_MOTION_FIELDS = (
    "schema_version", "step", "coupling_iteration", "time_s", "slice_id",
    "s_ref_m", "x_m", "y_m", "z_m", "vx_mps", "vy_mps", "vz_mps",
    "ax_mps2", "ay_mps2", "az_mps2",
)

_EPHEMERAL_BRIDGE_ROOTS: tuple[Path, ...] = ()


def set_ephemeral_bridge_roots(roots: Sequence[str | Path]) -> tuple[Path, ...]:
    """Set the exact case roots eligible for flush+atomic bridge publication."""
    global _EPHEMERAL_BRIDGE_ROOTS
    previous = _EPHEMERAL_BRIDGE_ROOTS
    _EPHEMERAL_BRIDGE_ROOTS = tuple(Path(root).resolve() for root in roots)
    return previous


def _ephemeral_bridge_path(path: str | Path) -> bool:
    candidate = Path(path).resolve()
    for root in _EPHEMERAL_BRIDGE_ROOTS:
        try:
            if os.path.commonpath([str(candidate), str(root)]) == str(root):
                return True
        except ValueError:
            continue
    return False


def time_close(actual: float, expected: float, tolerance: float = 1.0e-12) -> bool:
    return abs(float(actual) - float(expected)) <= tolerance * max(1.0, abs(float(expected)))


def bridge_seed(*, start_time_s: float, step_offset: int = 0) -> tuple[int, float]:
    """Return the initial CFD snapshot consumed at the OpenFOAM start time."""

    if not math.isfinite(start_time_s) or start_time_s < 0.0:
        raise RealProcessFreshnessError("start_time_s must be finite and non-negative")
    if int(step_offset) < 0:
        raise RealProcessFreshnessError("step_offset must be non-negative")
    return int(step_offset), float(start_time_s)


def bridge_for_global_step(*, global_step: int, target_time_s: float, step_offset: int = 1,
                           bridge_step: int | None = None) -> tuple[int, float]:
    """Map global step g to the CFD reader's step g+1 at the target time.

    ``ancfFileMotion`` computes its expected step from the CFD clock.  The
    formal scheduler's step 0 is the first *target* interval, so its
    compatibility snapshot is step 1; no ``target_time-dt`` substitution is
    valid here.
    """

    if int(global_step) < 0 or not math.isfinite(target_time_s) or target_time_s < 0.0:
        raise RealProcessFreshnessError("invalid global step/target time")
    if int(step_offset) < 0:
        raise RealProcessFreshnessError("step_offset must be non-negative")
    if bridge_step is not None:
        if isinstance(bridge_step, bool) or int(bridge_step) < 0:
            raise RealProcessFreshnessError("bridge_step must be a non-negative integer")
        return int(bridge_step), float(target_time_s)
    return int(global_step) + int(step_offset), float(target_time_s)


def atomic_text(path: str | Path, text: str) -> int:
    """Write text atomically and return the publication mtime in ns."""

    target = Path(path)
    fast_exchange = _ephemeral_bridge_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            if not fast_exchange:
                os.fsync(stream.fileno())
        replaced = False
        last_error: OSError | None = None
        # DrvFs can briefly retain a reader handle while the C++ compatibility
        # library is polling motion_ready.  Retry the atomic replace without
        # weakening the publication ordering or falling back to an in-place
        # write.
        for _ in range(100):
            try:
                os.replace(temporary, target)
                replaced = True
                break
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.01)
        if not replaced:
            raise last_error or OSError(f"cannot atomically replace {target}")
        if not fast_exchange:
            try:
                directory_fd = os.open(str(target.parent), os.O_RDONLY)
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        return target.stat().st_mtime_ns
    finally:
        temporary.unlink(missing_ok=True)


def materialize_legacy_motion_bridge(
    *,
    record: Mapping[str, Any],
    case: str | Path,
    exchange_dir: str | Path,
    seed: bool = False,
    seed_time_s: float | None = None,
    bridge_step_offset: int = 1,
    seed_step_offset: int | None = None,
    target_bridge_step: int | None = None,
) -> BridgeSnapshot:
    """Materialize one explicit 0.1.0 snapshot for ``ancfFileMotion``."""

    global_step = int(record["step"])
    target_time = float(record["time_s"])
    if seed:
        if seed_time_s is None or not time_close(target_time, seed_time_s):
            raise RealProcessFreshnessError("seed time must equal OpenFOAM start time")
        bridge_step, bridge_time = bridge_seed(
            start_time_s=seed_time_s,
            step_offset=bridge_step_offset if seed_step_offset is None else seed_step_offset,
        )
    else:
        bridge_step, bridge_time = bridge_for_global_step(
            global_step=global_step, target_time_s=target_time,
            step_offset=bridge_step_offset, bridge_step=target_bridge_step,
        )
    if not time_close(bridge_time, target_time):
        raise RealProcessFreshnessError("bridge time is not the formal target time")
    case_path = Path(case)
    payload_path = case_path / "coupling" / "motion.csv"
    ready_path = case_path / "coupling" / "motion_ready"
    # Keep the bridge fields deliberately identical to the already validated
    # formal position/velocity/acceleration values.  The C++ reader consumes
    # only the old positional view and keeps z fixed in the 2-D case.
    row = {
        "schema_version": "0.1.0", "step": bridge_step,
        "coupling_iteration": 0, "time_s": bridge_time,
        "slice_id": int(record["slice_id"]), "s_ref_m": float(record["s_ref_m"]),
        "x_m": float(record["x_m"]), "y_m": float(record["y_m"]),
        "z_m": float(record["z_m"]), "vx_mps": float(record["vx_mps"]),
        "vy_mps": float(record["vy_mps"]), "vz_mps": float(record["vz_mps"]),
        "ax_mps2": float(record["ax_mps2"]), "ay_mps2": float(record["ay_mps2"]),
        "az_mps2": float(record["az_mps2"]),
    }
    values = [row[field] for field in _MOTION_FIELDS]
    if any(isinstance(value, float) and not math.isfinite(value) for value in values):
        raise RealProcessFreshnessError("motion bridge contains NaN/Inf")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=_MOTION_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerow(row)
    payload_mtime = atomic_text(payload_path, stream.getvalue())
    ready = {
        "kind": "motion_ready", "payload": payload_path.name,
        "step": bridge_step, "time_s": bridge_time,
        "slice_id": int(record["slice_id"]),
        "case_id": str(record["case_id"]),
        "payload_sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
    }
    ready_mtime = atomic_text(ready_path, json.dumps(ready, sort_keys=True) + "\n")
    return BridgeSnapshot(
        bridge_step=bridge_step, bridge_time_s=bridge_time,
        payload_path=payload_path, ready_path=ready_path,
        published_ns=max(payload_mtime, ready_mtime),
    )


def validate_bridge_ack(
    *,
    ack_path: str | Path,
    snapshot: BridgeSnapshot,
    record: Mapping[str, Any],
    published_ns: int | None = None,
) -> Mapping[str, Any]:
    """Validate the old reader acknowledgement, including freshness."""

    path = Path(ack_path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RealProcessFreshnessError(f"invalid motion consumed marker: {path}") from exc
    if not isinstance(value, Mapping):
        raise RealProcessFreshnessError("motion consumed marker is not an object")
    if int(value.get("step", -1)) != snapshot.bridge_step:
        raise RealProcessFreshnessError("motion consumed bridge step mismatch")
    if not time_close(float(value.get("time_s", float("nan"))), snapshot.bridge_time_s):
        raise RealProcessFreshnessError("motion consumed bridge time mismatch")
    if "slice_id" in value and int(value["slice_id"]) != int(record["slice_id"]):
        raise RealProcessFreshnessError("motion consumed slice_id mismatch")
    if "case_id" in value and str(value["case_id"]) != str(record["case_id"]):
        raise RealProcessFreshnessError("motion consumed case_id mismatch")
    required_ns = max(snapshot.published_ns, int(published_ns or 0))
    if path.stat().st_mtime_ns < required_ns:
        raise RealProcessFreshnessError("motion consumed marker predates current publication")
    return value


def fingerprint(path: str | Path, *, include_hash: bool = False) -> FileFingerprint:
    target = Path(path)
    if not target.is_file():
        return FileFingerprint(target, False, 0, 0, None)
    return FileFingerprint(
        target, True, target.stat().st_size, target.stat().st_mtime_ns,
        sha256_file(target) if include_hash else None,
    )


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_fresh_case(case: str | Path, *, target_time_name: str) -> dict[str, Any]:
    """Check that a generated case has no pre-existing run artifacts."""

    root = Path(case)
    if not root.is_dir():
        raise RealProcessFreshnessError(f"case does not exist: {root}")
    forbidden: list[str] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        parts = relative.parts
        if any(part.startswith("processor") for part in parts):
            forbidden.append(str(relative))
        if path.name in {"forces.dat", "forceCoeffs.dat", "motion_ready", "load_ready"}:
            forbidden.append(str(relative))
        if path.name.startswith("motion_consumed_"):
            forbidden.append(str(relative))
        if path.name.startswith("log.") or path.name.endswith(".log"):
            forbidden.append(str(relative))
        if "postProcessing" in parts and path.is_file():
            forbidden.append(str(relative))
        if "coupling" in parts and path.is_file():
            forbidden.append(str(relative))
        if "checkpoints" in parts:
            forbidden.append(str(relative))
    target = root / target_time_name
    if target.is_dir() and target_time_name != "0":
        forbidden.append(str(target.relative_to(root)))
    if forbidden:
        raise RealProcessFreshnessError("case freshness check failed: " + ", ".join(sorted(set(forbidden))))
    return {
        "case": str(root.resolve()),
        "target_time_name": target_time_name,
        "checked_utc": time.time(),
        "forbidden_artifacts": [],
    }


def parse_force_exact(
    path: str | Path,
    *,
    target_time_s: float,
    time_tolerance: float = 1.0e-12,
    minimum_mtime_ns: int = 0,
    previous: FileFingerprint | None = None,
) -> ExactForce | None:
    """Return only a complete force row at exactly the requested time."""

    target = Path(path)
    if not target.is_file():
        return None
    current = fingerprint(target)
    if current.mtime_ns < int(minimum_mtime_ns):
        return None
    if previous is not None and previous.exists and (current.mtime_ns, current.size) <= (previous.mtime_ns, previous.size):
        return None
    try:
        text = target.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError):
        # A function object may still be flushing the last line.  The caller
        # will re-read, but it must never accept a partial row.
        return None
    matches: list[tuple[float, tuple[float, float, float]]] = []
    for line in text.splitlines():
        match = _FORCE_RE.match(line)
        if not match:
            continue
        try:
            current_time = float(match.group(1))
            pressure = [float(value) for value in match.group(2).split()]
            viscous = [float(value) for value in match.group(3).split()]
        except ValueError:
            continue
        if len(pressure) != 3 or len(viscous) != 3:
            continue
        if not all(math.isfinite(value) for value in (current_time, *pressure, *viscous)):
            raise RealProcessFreshnessError("forces.dat contains NaN/Inf")
        if time_close(current_time, target_time_s, time_tolerance):
            matches.append((current_time, tuple(pressure[i] + viscous[i] for i in range(3))))
    if len(matches) != 1:
        return None
    return ExactForce(matches[0][0], matches[0][1], current.size, current.mtime_ns)


def force_file_audit(path: str | Path, *, expected: ExactForce) -> dict[str, Any]:
    """Re-read and hash a consumed force file for post-run auditing."""

    current = parse_force_exact(path, target_time_s=expected.time_s)
    if current is None or current.size != expected.size or current.mtime_ns != expected.mtime_ns:
        raise RealProcessFreshnessError("consumed force file changed after checkpoint")
    digest = sha256_file(path)
    return {
        "path": str(Path(path).resolve()), "time_s": expected.time_s,
        "size": current.size, "mtime_ns": current.mtime_ns, "sha256": digest,
        "force_N": list(expected.force_N),
    }


def validate_initial_state(
    *,
    reference_positions: Mapping[int, Sequence[float]],
    seed_records: Iterable[Mapping[str, Any]],
    tolerance: float = 1.0e-12,
) -> dict[str, Any]:
    """Prove that the seed is zero in the CFD x/y displacement view."""

    checked = []
    for record in seed_records:
        sid = int(record["slice_id"])
        ref = tuple(float(value) for value in reference_positions[sid])
        position = (float(record["x_m"]), float(record["y_m"]), float(record["z_m"]))
        displacement = tuple(position[index] - ref[index] for index in range(3))
        if abs(displacement[0]) > tolerance or abs(displacement[1]) > tolerance:
            raise RealProcessFreshnessError(f"seed CFD displacement is not zero for slice {sid}")
        if not all(math.isfinite(value) for value in (*position, *displacement)):
            raise RealProcessFreshnessError(f"seed contains NaN/Inf for slice {sid}")
        checked.append({"slice_id": sid, "displacement_m": list(displacement)})
    return {"slices": checked, "tolerance_m": tolerance}
