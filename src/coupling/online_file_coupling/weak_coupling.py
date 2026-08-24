"""One-pass Dirichlet--Neumann file-coupling orchestration.

The structural solvers remain the source of the predictor/corrector states;
this module owns the ordering and audit fields at the file boundary.  A CFD
runner and a structural corrector are injected so the same protocol can drive
the MATLAB ANCF or Euler--Bernoulli branches without duplicating mechanics.
"""

from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .protocol import publish_ready, wait_for_ready


class WeakCouplingError(RuntimeError):
    """Raised when a one-pass exchange cannot produce a finite audit record."""


def _float(row: Mapping[str, str], key: str) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise WeakCouplingError(f"missing/non-numeric field {key}") from exc
    if not math.isfinite(value):
        raise WeakCouplingError(f"field {key} is NaN/Inf")
    return value


def _vector(row: Mapping[str, str], keys: Sequence[str]) -> tuple[float, ...]:
    return tuple(_float(row, key) for key in keys)


def _norm(values: Sequence[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def _read_single_snapshot(path: Path, *, expected_step: int, expected_time_s: float) -> dict[str, str]:
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise WeakCouplingError("single-slice audit requires exactly one load row")
    row = rows[0]
    if int(float(row["step"])) != expected_step or abs(_float(row, "time_s") - expected_time_s) > 1.0e-12 * max(1.0, abs(expected_time_s)):
        raise WeakCouplingError("load row step/time does not match the requested exchange")
    return row


@dataclass(frozen=True)
class WeakCouplingStep:
    step: int
    time_s: float
    force_x_N: float
    force_y_N: float
    force_z_N: float
    predicted_position_residual_m: float
    predicted_velocity_residual_mps: float
    force_change_N: float
    power_cfd_predicted_W: float
    power_structure_corrected_W: float
    power_coupling_defect_W: float
    instantaneous_power_W: float
    cfd_completed: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class OnePassWeakCoupling:
    """Enforce one Dirichlet--Neumann step with no inner iterations.

    ``motion_builder`` writes a complete predicted motion CSV and returns the
    predicted row.  ``cfd_runner`` must return only after OpenFOAM has written
    and committed the corresponding load CSV.  ``corrector`` receives that
    validated load row and returns the corrected motion row from ANCF or FEM.
    """

    def __init__(
        self,
        *,
        motion_csv: str | Path,
        motion_ready: str | Path,
        load_csv: str | Path,
        load_ready: str | Path,
        s_ref_m: Sequence[float],
        timeout_s: float = 30.0,
    ) -> None:
        if len(s_ref_m) != 1:
            raise WeakCouplingError("the Stage-three driver is intentionally single-slice")
        self.motion_csv = Path(motion_csv)
        self.motion_ready = Path(motion_ready)
        self.load_csv = Path(load_csv)
        self.load_ready = Path(load_ready)
        self.s_ref_m = tuple(float(value) for value in s_ref_m)
        self.timeout_s = float(timeout_s)
        self.previous_force = (0.0, 0.0, 0.0)

    def exchange_step(
        self,
        *,
        step: int,
        time_s: float,
        motion_builder: Callable[[Path, Path, int, float], Mapping[str, object]],
        cfd_runner: Callable[[int, float], None],
        corrector: Callable[[Mapping[str, str]], Mapping[str, object]],
    ) -> WeakCouplingStep:
        predicted = dict(motion_builder(self.motion_csv, self.motion_ready, step, time_s))
        publish_ready(self.motion_csv, self.motion_ready, kind="motion", expected_s_ref_m=self.s_ref_m)
        cfd_runner(step, time_s)
        wait_for_ready(
            self.load_csv,
            self.load_ready,
            kind="load",
            expected_step=step,
            expected_time_s=time_s,
            expected_s_ref_m=self.s_ref_m,
            timeout_s=self.timeout_s,
        )
        load = _read_single_snapshot(self.load_csv, expected_step=step, expected_time_s=time_s)
        corrected = dict(corrector(load))
        predicted_position = _vector(predicted, ("x_m", "y_m", "z_m"))
        corrected_position = _vector(corrected, ("x_m", "y_m", "z_m"))
        predicted_velocity = _vector(predicted, ("vx_mps", "vy_mps", "vz_mps"))
        corrected_velocity = _vector(corrected, ("vx_mps", "vy_mps", "vz_mps"))
        force = _vector(load, ("force_x_N", "force_y_N", "force_z_N"))
        power_cfd = sum(f * v for f, v in zip(force, predicted_velocity))
        power_structure = sum(f * v for f, v in zip(force, corrected_velocity))
        record = WeakCouplingStep(
            step=step,
            time_s=float(time_s),
            force_x_N=force[0],
            force_y_N=force[1],
            force_z_N=force[2],
            predicted_position_residual_m=_norm(tuple(a - b for a, b in zip(corrected_position, predicted_position))),
            predicted_velocity_residual_mps=_norm(tuple(a - b for a, b in zip(corrected_velocity, predicted_velocity))),
            force_change_N=_norm(tuple(a - b for a, b in zip(force, self.previous_force))),
            power_cfd_predicted_W=power_cfd,
            power_structure_corrected_W=power_structure,
            power_coupling_defect_W=power_cfd-power_structure,
            instantaneous_power_W=power_structure,
        )
        self.previous_force = force
        return record
