"""Campaign adapter for a resident C++ ANCF worker."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import ContractError, load_source_checkpoint


class CppAdapterError(RuntimeError):
    """Fail-closed C++ worker adapter error."""


def _finite(values: Sequence[float], name: str) -> tuple[float, ...]:
    if isinstance(values, (str, bytes)):
        raise CppAdapterError(f"{name} is not a numeric sequence")
    result_values: list[float] = []
    try:
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CppAdapterError(f"{name} contains a non-numeric value")
            result_values.append(float(value))
    except TypeError as exc:
        raise CppAdapterError(f"{name} is not a numeric sequence") from exc
    result = tuple(result_values)
    if not result or any(not math.isfinite(value) for value in result):
        raise CppAdapterError(f"{name} is empty or contains NaN/Inf")
    return result


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


class CppKernelCampaignAdapter:
    """Persistent C++ worker with explicit predictor/corrector transport."""

    CHECKPOINT_SCHEMA = "cpp_kernel_campaign_checkpoint_v1"

    def __init__(self, *, worker: Any, model: Any, request_factory: Any,
                 run_id: str, case_id: str, source_global_step: int,
                 source_time_s: float, source_tick: int, dt_s: float,
                 q: Sequence[float], qdot: Sequence[float], qddot: Sequence[float],
                 base_load: Sequence[float], slice_count: int = 3,
                 mass_matrix: Sequence[float] = ()) -> None:
        if slice_count != 3:
            raise CppAdapterError("C++ confirm requires exactly three slices")
        self.worker = worker
        self.model = model
        self.request_factory = request_factory
        self.run_id, self.case_id = str(run_id), str(case_id)
        self.source_global_step, self.source_time_s = int(source_global_step), float(source_time_s)
        self.source_tick, self.dt_s = int(source_tick), float(dt_s)
        self.slice_count = int(slice_count)
        self._state = {"q": list(_finite(q, "q")), "qdot": list(_finite(qdot, "qdot")),
                       "qddot": list(_finite(qddot, "qddot"))}
        self._committed_state = json.loads(json.dumps(self._state))
        self.base_load = _finite(base_load, "base_load")
        mass = tuple(float(value) for value in mass_matrix)
        if mass and (len(mass) != model.ndof * model.ndof or
                     any(not math.isfinite(value) for value in mass)):
            raise CppAdapterError("source mass_matrix is invalid")
        self.mass_matrix = mass
        self.pending_kind: str | None = None
        self.pending_step: int | None = None
        self.pending_time_s: float | None = None
        self.pending_tick: int | None = None
        self._predictor_state: dict[str, list[float]] | None = None
        self._pending_bridge: int | None = None
        self._committed_step = self.source_global_step
        self._committed_time_s = self.source_time_s
        self._committed_tick = self.source_tick
        self.start_count = 0
        self._started = False
        self._terminal = False
        self.responses: list[dict[str, Any]] = []

    @classmethod
    def from_checkpoint(cls, *, worker: Any, model: Any, request_factory: Any,
                        checkpoint: Path, expected_sha256: str,
                        run_id: str, case_id: str, dt_s: float,
                        base_load: Sequence[float], slice_count: int = 3,
                        mass_matrix: Sequence[float] = ()) -> "CppKernelCampaignAdapter":
        value = load_source_checkpoint(checkpoint, expected_sha256)
        structure = value.get("structure")
        if not isinstance(structure, Mapping):
            raise ContractError("source checkpoint missing structure object")
        if not {"q", "qdot", "qddot"}.issubset(structure):
            raise ContractError("source checkpoint missing q/qdot/qddot")
        if int(value.get("step", -1)) != 559 or abs(float(value.get("time_s", -1.0)) - 2.2075) > 1e-12:
            raise ContractError("source checkpoint identity is not step 559 at 2.2075 s")
        return cls(worker=worker, model=model, request_factory=request_factory,
                   run_id=run_id, case_id=case_id, source_global_step=559,
                   source_time_s=2.2075, source_tick=2_207_500_000, dt_s=dt_s,
                   q=structure["q"], qdot=structure["qdot"], qddot=structure["qddot"],
                   base_load=base_load, slice_count=slice_count,
                   mass_matrix=mass_matrix)

    def _identity(self, step: int, time_s: float) -> tuple[int, int]:
        if isinstance(step, bool) or not isinstance(step, int):
            raise CppAdapterError("global step is not an integer")
        if isinstance(time_s, bool) or not isinstance(time_s, (int, float)) or not math.isfinite(float(time_s)):
            raise CppAdapterError("time_s is not finite")
        bridge = int(step) - self.source_global_step
        expected_time = self.source_time_s + bridge * self.dt_s
        expected_tick = self.source_tick + bridge * round(self.dt_s * 1e9)
        if bridge <= 0 or abs(float(time_s) - expected_time) > 1e-12:
            raise CppAdapterError("global step/time does not match source mapping")
        return bridge, expected_tick

    def start(self) -> None:
        if self._started or self._terminal:
            raise CppAdapterError("C++ worker duplicate start")
        self.worker.start()
        self.start_count = 1
        self._started = True

    def state_view(self) -> dict[str, list[float]]:
        if self._terminal:
            raise CppAdapterError("C++ worker adapter is terminal")
        return {key: list(value) for key, value in self._state.items()}

    def _flatten_forces(self, forces: Sequence[Sequence[float]]) -> tuple[float, ...]:
        if len(forces) != self.slice_count or any(len(row) != 3 for row in forces):
            raise CppAdapterError("slice force matrix must be 3x3")
        return _finite(tuple(float(value) for row in forces for value in row), "slice_force")

    def _request(self, *, sequence: int, step: int, bridge: int, tick: int,
                 time_s: float, force: tuple[float, ...],
                 state: Mapping[str, Sequence[float]]):
        request_id, transaction_id = 100000 + sequence, 200000 + sequence
        request = self.request_factory(sequence=sequence, global_step=int(step),
            case_local_bridge_step=bridge, integer_tick=tick, time_s=float(time_s),
            dt_s=self.dt_s, request_id=request_id, transaction_id=transaction_id,
            run_id=self.run_id, case_id=self.case_id, model=self.model,
            q=tuple(state["q"]), qdot=tuple(state["qdot"]), qddot=tuple(state["qddot"]),
            base_load=self.base_load, slice_force=force, mass_matrix=self.mass_matrix)
        try:
            response = self.worker.step(request)
        except Exception:
            self._terminal = True
            raise
        if getattr(response, "return_code", None) != 0 or getattr(response, "finite_value_audit", False) is not True:
            self._terminal = True
            raise CppAdapterError("C++ worker returned nonzero or non-finite result")
        for key, expected in (("global_step", step), ("case_local_bridge_step", bridge),
                              ("integer_tick", tick), ("request_id", request_id),
                              ("transaction_id", transaction_id), ("run_id", self.run_id),
                              ("case_id", self.case_id), ("sequence", sequence)):
            if getattr(response, key, None) != expected:
                self._terminal = True
                raise CppAdapterError(f"C++ worker response identity mismatch: {key}")
        if not math.isclose(float(response.time_s), float(time_s), rel_tol=0.0, abs_tol=1e-12):
            self._terminal = True
            raise CppAdapterError("C++ worker response time mismatch")
        if getattr(response, "ack", None) not in (1, "ack", "committed") or not getattr(response, "payload_hash", None):
            self._terminal = True
            raise CppAdapterError("C++ worker response acknowledgement/hash is missing")
        state_out = {"q": list(_finite(response.q, "response.q")),
                     "qdot": list(_finite(response.qdot, "response.qdot")),
                     "qddot": list(_finite(response.qddot, "response.qddot"))}
        self.responses.append({"phase": "prediction" if sequence % 2 else "correction",
                               "transport_sequence": sequence, "step": int(step),
                               "time_s": float(time_s), "integer_tick": tick,
                               "case_local_bridge_step": bridge,
                               "payload_hash": response.payload_hash.hex(),
                               "return_code": int(response.return_code),
                               "finite_value_audit": True})
        return response, state_out, request_id, transaction_id

    def predict(self, step: int, time_s: float, previous_slice_forces: Sequence[Sequence[float]]):
        if self._terminal or not self._started:
            raise CppAdapterError("C++ worker adapter is unavailable")
        bridge, tick = self._identity(step, time_s)
        if self.pending_kind is not None:
            raise CppAdapterError("prediction requested with pending state")
        force = self._flatten_forces(previous_slice_forces)
        response, predictor, request_id, transaction_id = self._request(
            sequence=2 * bridge - 1, step=int(step), bridge=bridge, tick=tick,
            time_s=float(time_s), force=force, state=self._committed_state)
        # The protected MATLAB prediction operation calls ancf_advance_step
        # with the previous-step force and exposes that complete target-time
        # state to the motion bridge.  The C++ request follows the same
        # operation, so motion must use response.q/qdot/qddot together.  The
        # response.predictor field is only the internal Newmark position guess
        # and cannot be combined with velocities from another state.
        motion_state = {
            "q": list(_finite(response.q, "response.q")),
            "qdot": list(_finite(response.qdot, "response.qdot")),
            "qddot": list(_finite(response.qddot, "response.qddot")),
        }
        self.pending_kind, self.pending_step, self.pending_time_s = "prediction", int(step), float(time_s)
        self._predictor_state, self._pending_bridge = motion_state, bridge
        self.pending_tick = tick
        return {"step": int(step), "global_step": int(step), "case_local_bridge_step": bridge,
                "time_s": float(time_s), "integer_tick": tick, "run_id": self.run_id,
                "case_id": self.case_id, "request_id": request_id, "transaction_id": transaction_id,
                "sequence": 2 * bridge - 1, "ack": int(getattr(response, "ack", 1)),
                "payload_hash": response.payload_hash.hex(), "finite_value_audit": True,
                "predictor": list(motion_state["q"]),
                "predictor_qdot": list(motion_state["qdot"]),
                "predictor_qddot": list(motion_state["qddot"]),
                "motion": list(motion_state["q"])}, []

    def correct(self, step: int, time_s: float, integrated_slice_forces: Sequence[Sequence[float]]):
        if self._terminal or not self._started:
            raise CppAdapterError("C++ worker adapter is unavailable")
        bridge, tick = self._identity(step, time_s)
        if self.pending_kind != "prediction" or self.pending_step != int(step) or abs(self.pending_time_s - float(time_s)) > 1e-12:
            raise CppAdapterError("correction does not match pending prediction")
        if self._pending_bridge != bridge or self._predictor_state is None:
            self._terminal = True
            raise CppAdapterError("prediction state is missing for correction")
        force = self._flatten_forces(integrated_slice_forces)
        response, corrected, request_id, transaction_id = self._request(
            sequence=2 * bridge, step=int(step), bridge=bridge, tick=tick,
            time_s=float(time_s), force=force, state=self._committed_state)
        self._state = corrected
        audit = {"phase": "correction", "step": int(step), "time_s": float(time_s), "integer_tick": tick,
                 "case_local_bridge_step": bridge, "payload_hash": response.payload_hash.hex(),
                 "return_code": int(response.return_code), "finite_value_audit": True,
                 "prediction_transport_sequence": 2 * bridge - 1,
                 "correction_transport_sequence": 2 * bridge}
        self.responses.append(audit)
        self.pending_kind = "correction"
        self._predictor_state = self._pending_bridge = None
        return {"step": int(step), "global_step": int(step), "case_local_bridge_step": bridge,
                "time_s": float(time_s), "integer_tick": tick, "run_id": self.run_id,
                "case_id": self.case_id, "request_id": request_id, "transaction_id": transaction_id,
                "sequence": int(getattr(response, "sequence", 2 * bridge)),
                "transport_sequence": 2 * bridge,
                "ack": int(getattr(response, "ack", 1)), "return_code": int(response.return_code),
                "payload_hash": response.payload_hash.hex(), "finite_value_audit": True,
                "generalized_force": list(response.generalized_force),
                "checkpoint_token": hashlib.sha256(_canonical(audit)).hexdigest(), "audit": audit}, []

    def save_checkpoint(self, path: str | Path) -> None:
        if self.pending_kind is not None:
            raise CppAdapterError("cannot save a checkpoint while staged state is pending")
        Path(path).write_bytes(_canonical({
            "schema_version": self.CHECKPOINT_SCHEMA,
            "state_view": self.state_view(),
            "source_global_step": self.source_global_step,
            "source_time_s": self.source_time_s,
            "source_tick": self.source_tick,
            "dt_s": self.dt_s,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "committed_global_step": self._committed_step,
            "committed_time_s": self._committed_time_s,
            "committed_tick": self._committed_tick,
        }))

    def load_checkpoint(self, path: str | Path) -> None:
        try:
            value = json.loads(Path(path).read_bytes().decode("utf-8"))
            if not isinstance(value, Mapping):
                raise CppAdapterError("C++ checkpoint root must be an object")
            if value.get("schema_version") != self.CHECKPOINT_SCHEMA:
                raise CppAdapterError("unsupported C++ checkpoint schema")
            def checkpoint_int(name: str) -> int:
                candidate = value.get(name)
                if isinstance(candidate, bool) or not isinstance(candidate, int):
                    raise CppAdapterError(f"C++ checkpoint {name} is not an integer")
                return candidate

            def checkpoint_float(name: str) -> float:
                candidate = value.get(name)
                if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
                    raise CppAdapterError(f"C++ checkpoint {name} is not numeric")
                result = float(candidate)
                if not math.isfinite(result):
                    raise CppAdapterError(f"C++ checkpoint {name} is NaN/Inf")
                return result

            if (value.get("run_id") != self.run_id or value.get("case_id") != self.case_id or
                    checkpoint_int("source_global_step") != self.source_global_step or
                    not math.isclose(checkpoint_float("source_time_s"), self.source_time_s, rel_tol=0.0, abs_tol=1e-12) or
                    checkpoint_int("source_tick") != self.source_tick or
                    not math.isclose(checkpoint_float("dt_s"), self.dt_s, rel_tol=0.0, abs_tol=1e-15)):
                raise CppAdapterError("C++ checkpoint identity or dt mismatch")
            committed_step = checkpoint_int("committed_global_step")
            committed_time = checkpoint_float("committed_time_s")
            committed_tick = checkpoint_int("committed_tick")
            bridge = committed_step - self.source_global_step
            if (committed_step < self.source_global_step or
                    not math.isfinite(committed_time) or
                    abs(committed_time - (self.source_time_s + bridge * self.dt_s)) > 1e-12 or
                    committed_tick != self.source_tick + bridge * round(self.dt_s * 1e9)):
                raise CppAdapterError("C++ checkpoint committed identity is invalid")
            state = value["state_view"]
            if not isinstance(state, Mapping) or set(state) != {"q", "qdot", "qddot"}:
                raise CppAdapterError("C++ checkpoint state schema is invalid")
            self._state = {key: list(_finite(state[key], f"checkpoint.{key}")) for key in ("q", "qdot", "qddot")}
            if len({len(values) for values in self._state.values()}) != 1:
                raise CppAdapterError("C++ checkpoint state dimensions disagree")
            expected_ndof = getattr(self.model, "ndof", None)
            if expected_ndof is not None and not callable(expected_ndof) and len(self._state["q"]) != int(expected_ndof):
                raise CppAdapterError("C++ checkpoint state dimension does not match model")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError,
                ValueError, OverflowError) as exc:
            raise CppAdapterError("invalid UTF-8 C++ checkpoint") from exc
        self._committed_state = json.loads(json.dumps(self._state))
        self._committed_step = committed_step
        self._committed_time_s = committed_time
        self._committed_tick = committed_tick
        self.pending_kind = self.pending_step = self.pending_time_s = None
        self.pending_tick = None
        self._predictor_state = self._pending_bridge = None

    def finalize_committed(self, token: object | None = None) -> None:
        if self.pending_kind != "correction":
            raise CppAdapterError("no correction is ready to commit")
        self._committed_state = json.loads(json.dumps(self._state))
        self._committed_step = int(self.pending_step)
        self._committed_time_s = float(self.pending_time_s)
        self._committed_tick = int(self.pending_tick)
        self.pending_kind = self.pending_step = self.pending_time_s = None
        self.pending_tick = None
        self._predictor_state = self._pending_bridge = None

    def discard_staged(self) -> None:
        self._state = json.loads(json.dumps(self._committed_state))
        self.pending_kind = self.pending_step = self.pending_time_s = None
        self.pending_tick = None
        self._predictor_state = self._pending_bridge = None

    def shutdown(self) -> None:
        if self._started:
            self.worker.stop()
            self._started = False
        self._terminal = True

    def stop(self) -> None:
        """Expose the coordinator lifecycle name for a resident worker.

        ``CppConfirmRun`` owns the segment lifecycle and deliberately talks to
        its worker through ``start``/``stop``.  The adapter historically used
        ``shutdown`` instead, which made the production path fail during
        cleanup after otherwise successful work.  Keep ``shutdown`` as the
        implementation and provide this idempotent alias so both direct
        adapter use and the coordinator share one cleanup contract.
        """
        self.shutdown()

    @property
    def owned_residual(self) -> int:
        return int(getattr(self.worker, "owned_residual", 0))
