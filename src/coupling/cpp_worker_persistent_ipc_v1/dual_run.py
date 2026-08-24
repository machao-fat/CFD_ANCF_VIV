from __future__ import annotations

import json
import math
from numbers import Real
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .protocol import FrameError


NUMERIC_FIELDS = (
    "q", "qdot", "qddot", "internal_force", "external_force",
    "generalized_force", "predictor", "corrector", "residual",
)
IDENTITY_FIELDS = (
    "run_id", "case_id", "global_step", "case_local_bridge_step",
    "time_s", "integer_tick",
)


@dataclass(frozen=True)
class DualStepRecord:
    run_id: str
    case_id: str
    global_step: int
    case_local_bridge_step: int
    time_s: float
    integer_tick: int
    q: tuple[float, ...]
    qdot: tuple[float, ...]
    qddot: tuple[float, ...]
    internal_force: tuple[float, ...]
    external_force: tuple[float, ...]
    generalized_force: tuple[float, ...]
    predictor: tuple[float, ...]
    corrector: tuple[float, ...]
    residual: tuple[float, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "DualStepRecord":
        def vector(name: str) -> tuple[float, ...]:
            raw = value.get(name)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                result = (float(raw),)
            else:
                if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
                    raise FrameError(f"dual record missing vector {name}")
                if any(isinstance(item, bool) or not isinstance(item, Real) for item in raw):
                    raise FrameError(f"dual record {name} contains a non-numeric value")
                result = tuple(float(item) for item in raw)
            if not result or any(not math.isfinite(item) for item in result):
                raise FrameError(f"dual record {name} is empty or non-finite")
            return result

        try:
            run_id = value["run_id"]
            case_id = value["case_id"]
            global_step = value["global_step"]
            bridge_step = value["case_local_bridge_step"]
            time_s = value["time_s"]
            integer_tick = value["integer_tick"]
            if (not isinstance(run_id, str) or not run_id or
                    not isinstance(case_id, str) or not case_id or
                    isinstance(global_step, bool) or not isinstance(global_step, int) or global_step <= 0 or
                    isinstance(bridge_step, bool) or not isinstance(bridge_step, int) or bridge_step <= 0 or
                    isinstance(integer_tick, bool) or not isinstance(integer_tick, int) or integer_tick < 0 or
                    isinstance(time_s, bool) or not isinstance(time_s, Real)):
                raise FrameError("dual record identity is malformed")
            record = cls(
                run_id=run_id, case_id=case_id,
                global_step=global_step, case_local_bridge_step=bridge_step,
                time_s=float(time_s), integer_tick=integer_tick,
                **{name: vector(name) for name in NUMERIC_FIELDS},
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise FrameError("dual record identity or vector is malformed") from exc
        if not record.run_id or not record.case_id or not math.isfinite(record.time_s):
            raise FrameError("dual record identity is invalid")
        return record

    def to_dict(self) -> dict[str, object]:
        return {"run_id": self.run_id, "case_id": self.case_id, "global_step": self.global_step,
                "case_local_bridge_step": self.case_local_bridge_step, "time_s": self.time_s,
                "integer_tick": self.integer_tick, **{name: list(getattr(self, name)) for name in NUMERIC_FIELDS}}


def _compare_vector(name: str, reference: Sequence[float], candidate: Sequence[float], abs_tol: float, rel_tol: float) -> dict[str, object]:
    if len(reference) != len(candidate):
        raise FrameError(f"dual vector dimension mismatch: {name}")
    errors = [abs(float(a) - float(b)) for a, b in zip(reference, candidate)]
    scales = [max(1.0, abs(float(a)), abs(float(b))) for a, b in zip(reference, candidate)]
    relative = [error / scale for error, scale in zip(errors, scales)]
    max_abs = max(errors, default=0.0); max_rel = max(relative, default=0.0)
    if max_abs > abs_tol and max_rel > rel_tol:
        raise FrameError(f"dual numerical mismatch: {name} abs={max_abs:g} rel={max_rel:g}")
    return {"max_abs": max_abs, "max_relative": max_rel, "count": len(errors)}


def compare_records(reference: DualStepRecord, candidate: DualStepRecord, *, abs_tol: float = 1e-11,
                    rel_tol: float = 1e-9, field_abs_tol: Mapping[str, float] | None = None) -> dict[str, object]:
    for name in IDENTITY_FIELDS:
        left, right = getattr(reference, name), getattr(candidate, name)
        if name == "time_s":
            if not math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12):
                raise FrameError("dual identity mismatch: time_s")
        elif left != right:
            raise FrameError(f"dual identity mismatch: {name}")
    tolerances = field_abs_tol or {}
    fields = {name: _compare_vector(name, getattr(reference, name), getattr(candidate, name),
                                    float(tolerances.get(name, abs_tol)), rel_tol) for name in NUMERIC_FIELDS}
    return {"status": "pass", "identity": "exact", "fields": fields, "abs_tol": abs_tol,
            "rel_tol": rel_tol, "field_abs_tol": dict(tolerances)}


def load_record(path: str | Path) -> DualStepRecord:
    return DualStepRecord.from_mapping(json.loads(Path(path).read_text(encoding="utf-8")))
