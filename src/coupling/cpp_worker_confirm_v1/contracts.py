from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "cfd_ancf_viv_cpp_confirm_v1.0"
FORMAL_PROTOCOL_VERSION = "0.2.1"
REAL_AUTHORIZATION_TOKEN = "USER_EXPLICITLY_AUTHORIZED_REAL_CFD_CONFIRM_V1"
LONG_WINDOW_STAGE_ID = "stage4f_d_cpp_worker_long_window_v1"
LONG_WINDOW_SOURCE_STEP = 639
LONG_WINDOW_STEPS = 800
LONG_WINDOW_DURATION_S = 1.0
TO6S_STAGE_ID = "stage4f_d_cpp_worker_to6s_v1"
TO6S_SOURCE_STEP = 1439
TO6S_STEPS = 2154
TO6S_DURATION_S = 2.6925
TO30S_STAGE_ID = "stage4f_d_cpp_worker_to30s_v1"
TO30S_SOURCE_STEP = 3593
TO30S_STEPS = 19_200
TO30S_DURATION_S = 24.0
TO70S_STAGE_ID = "stage4f_d_cpp_worker_to70s_v1"
TO70S_SOURCE_STEP = 559
TO70S_STEPS = 55_441
TO70S_DURATION_S = 69.30125
FRESH_T0_STAGE_ID = "stage4f_d_cpp_worker_fresh_t0_v1"
FRESH_T0_SOURCE_STEP = 0
FRESH_T0_SOURCE_TIME_S = 0.0
FRESH_T0_SOURCE_TICK = 0
FRESH_T0_STEPS = 40
FRESH_T0_DURATION_S = 0.05
SCOPE = {
    "no_statistics": True, "no_e5c": True, "no_five_slice": True,
    "no_nine_slice": True, "no_long_time_viv": True,
    "no_lock_in": True, "no_experiment": True,
}


class ContractError(ValueError):
    """A confirm contract is malformed, stale, or expands the scope."""


def load_source_checkpoint(path: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    """Read the accepted source checkpoint with an explicit UTF-8 boundary.

    Windows' process locale is not part of the checkpoint contract.  The
    source is immutable, so hash it before parsing and reject any mismatch or
    malformed/non-UTF-8 JSON fail-closed.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"source checkpoint cannot be read: {path}") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and actual != expected_sha256:
        raise ContractError("source checkpoint SHA-256 mismatch")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("source checkpoint is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("source checkpoint root must be an object")
    return value


def canonical_bytes(value: Any) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                           separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError(f"non-canonical contract JSON: {exc}") from exc


def contract_hash(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key not in {"contract_sha256", "contract_hash"}}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _finite(value: Any, name: str = "contract") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items(): _finite(item, f"{name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value): _finite(item, f"{name}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ContractError(f"{name} contains NaN/Inf")


@dataclass(frozen=True)
class CppConfirmContract:
    stage_id: str
    run_id: str
    case_id: str
    runtime: Path
    results: Path
    source_checkpoint: Path
    source_checkpoint_sha256: str
    source_global_step: int = 559
    source_time_s: float = 2.2075
    source_tick: int = 2_207_500_000
    steps: int = 40
    segment_duration_s: float = 0.05
    global_dt_s: float = 0.00125
    slice_count: int = 3
    allow_real_external_processes: bool = False
    authorization: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "formal_protocol_version": FORMAL_PROTOCOL_VERSION,
            "stage_id": self.stage_id, "run_id": self.run_id, "case_id": self.case_id,
            "runtime": str(self.runtime), "results": str(self.results),
            "source_checkpoint": str(self.source_checkpoint),
            "source_checkpoint_sha256": self.source_checkpoint_sha256,
            "source_global_step": self.source_global_step, "source_time_s": self.source_time_s,
            "source_tick": self.source_tick, "steps": self.steps,
            "segment_duration_s": self.segment_duration_s, "global_dt_s": self.global_dt_s,
            "slice_count": self.slice_count,
            "allow_real_external_processes": self.allow_real_external_processes,
            "authorization": self.authorization, "scope": dict(SCOPE),
        }
        value["contract_sha256"] = contract_hash(value)
        return value

    def validate(self, project_root: Path) -> None:
        if not self.stage_id or not self.run_id or not self.case_id:
            raise ContractError("stage/run/case identity is required")
        standard_window = self.steps == 40 and self.segment_duration_s == 0.05
        # The sole non-default physical authorization is an exact one-second
        # continuation from the accepted Stage204 endpoint.  Keeping this
        # identity-bound instead of allowing arbitrary larger windows means
        # later calls cannot silently broaden the research scope.
        long_window = (
            self.stage_id == LONG_WINDOW_STAGE_ID
            and self.source_global_step == LONG_WINDOW_SOURCE_STEP
            and self.steps == LONG_WINDOW_STEPS
            and self.segment_duration_s == LONG_WINDOW_DURATION_S
        )
        to6s_window = (
            self.stage_id == TO6S_STAGE_ID
            and self.source_global_step == TO6S_SOURCE_STEP
            and self.steps == TO6S_STEPS
            and self.segment_duration_s == TO6S_DURATION_S
        )
        # This is the sole direct long continuation authorized from the
        # immutable Stage214 6.0 s portable checkpoint.  It is identity-bound
        # so no later caller can turn the generic coordinator into an
        # unbounded production runner.
        to30s_window = (
            self.stage_id == TO30S_STAGE_ID
            and self.source_global_step == TO30S_SOURCE_STEP
            and self.steps == TO30S_STEPS
            and self.segment_duration_s == TO30S_DURATION_S
        )
        # The one explicitly authorized cumulative 0->70 s continuation.
        # The immutable accepted source is step 559 (2.2075 s); the target
        # endpoint is global step 56000 (70 s).  No arbitrary long window is
        # admitted by this branch.
        to70s_window = (
            self.stage_id == TO70S_STAGE_ID
            and self.source_global_step == TO70S_SOURCE_STEP
            and self.steps == TO70S_STEPS
            and self.segment_duration_s == TO70S_DURATION_S
        )
        fresh_t0_window = (
            self.stage_id == FRESH_T0_STAGE_ID
            and self.source_global_step == FRESH_T0_SOURCE_STEP
            and self.source_time_s == FRESH_T0_SOURCE_TIME_S
            and self.source_tick == FRESH_T0_SOURCE_TICK
            and self.steps == FRESH_T0_STEPS
            and self.segment_duration_s == FRESH_T0_DURATION_S
        )
        if not (standard_window or long_window or to6s_window or to30s_window or to70s_window or fresh_t0_window) or self.global_dt_s != 0.00125:
            raise ContractError("scope is not an explicitly authorized bounded window")
        if self.slice_count != 3:
            raise ContractError("exactly three slices are required")
        if (not fresh_t0_window and
                (isinstance(self.source_global_step, bool) or not isinstance(self.source_global_step, int) or self.source_global_step < 559)):
            raise ContractError("source step must be the accepted step 559 or a verified continuation")
        if fresh_t0_window:
            expected_source_time = 0.0
            expected_source_tick = 0
        else:
            expected_source_time = 2.2075 + (self.source_global_step - 559) * self.global_dt_s
            expected_source_tick = 2_207_500_000 + (self.source_global_step - 559) * 1_250_000
        if abs(self.source_time_s - expected_source_time) > 1e-12 or self.source_tick != expected_source_tick:
            raise ContractError("source step/time/tick mapping is inconsistent")
        if self.runtime.drive.upper() != "D:" or self.results.drive.upper() != "D:" or self.source_checkpoint.drive.upper() != "D:":
            raise ContractError("runtime, results and source must be on D:")
        root = project_root.resolve()
        for label, path in (("runtime", self.runtime), ("results", self.results), ("source_checkpoint", self.source_checkpoint)):
            resolved = Path(path).resolve()
            if root not in resolved.parents and resolved != root:
                raise ContractError(f"{label} is outside the project")
        if self.runtime.resolve() == self.results.resolve():
            raise ContractError("runtime and results must be independent")
        if not self.source_checkpoint.is_file():
            raise ContractError("source checkpoint is missing")
        source = load_source_checkpoint(self.source_checkpoint, self.source_checkpoint_sha256)
        source_committed = source.get("status") == "committed" or source.get("committed") is True
        fresh_state = source.get("state_kind") == "cpp_reference_state" and source.get("schema_version") == "ancf-t0-cpp-v2"
        if fresh_t0_window:
            if not fresh_state or source.get("equilibrated") is not True or source.get("finite_value_audit") is not True:
                raise ContractError("fresh source is not an audited static-equilibrium state")
            source_committed = True
        source_step = source.get("step", source.get("global_step", -1))
        if not source_committed or int(source_step) != self.source_global_step:
            raise ContractError("source checkpoint is not the accepted committed step")
        if abs(float(source.get("time_s", float("nan"))) - self.source_time_s) > 1e-12:
            raise ContractError("source checkpoint time mismatch")
        source_tick = source.get("time_tick", source.get("integer_tick", -1))
        if int(source_tick) != self.source_tick:
            raise ContractError("source checkpoint tick mismatch")
        portable = source.get("checkpoint_metadata", {}).get("ancf_restart_state")
        structure = (portable.get("structure") if isinstance(portable, Mapping)
                     else (source if fresh_t0_window else source.get("structure")))
        if not isinstance(structure, Mapping) or any(key not in structure for key in ("q", "qdot", "qddot")):
            raise ContractError("source checkpoint structure state is incomplete")
        if not isinstance(self.allow_real_external_processes, bool):
            raise ContractError("real process flag must be boolean")
        if self.allow_real_external_processes and self.authorization != REAL_AUTHORIZATION_TOKEN:
            raise ContractError("real process authorization token is missing")


def validate_serialized_contract(value: Mapping[str, Any], project_root: Path) -> CppConfirmContract:
    required = {"schema_version", "formal_protocol_version", "contract_sha256", "stage_id", "run_id", "case_id",
                "runtime", "results", "source_checkpoint", "source_checkpoint_sha256", "source_global_step",
                "source_time_s", "source_tick", "steps", "segment_duration_s", "global_dt_s", "slice_count",
                "allow_real_external_processes", "authorization", "scope"}
    missing = sorted(required - value.keys())
    if missing: raise ContractError("missing fields: " + ",".join(missing))
    if value["schema_version"] != SCHEMA_VERSION or value["formal_protocol_version"] != FORMAL_PROTOCOL_VERSION:
        raise ContractError("unsupported contract version")
    if value["contract_sha256"] != contract_hash(value):
        raise ContractError("contract hash mismatch")
    if value["scope"] != SCOPE: raise ContractError("scope expansion")
    _finite(value)
    contract = CppConfirmContract(
        stage_id=str(value["stage_id"]), run_id=str(value["run_id"]), case_id=str(value["case_id"]),
        runtime=Path(str(value["runtime"])), results=Path(str(value["results"])),
        source_checkpoint=Path(str(value["source_checkpoint"])), source_checkpoint_sha256=str(value["source_checkpoint_sha256"]),
        source_global_step=int(value["source_global_step"]), source_time_s=float(value["source_time_s"]),
        source_tick=int(value["source_tick"]), steps=int(value["steps"]),
        segment_duration_s=float(value["segment_duration_s"]), global_dt_s=float(value["global_dt_s"]),
        slice_count=int(value["slice_count"]), allow_real_external_processes=bool(value["allow_real_external_processes"]),
        authorization=value.get("authorization"),
    )
    contract.validate(project_root)
    return contract
