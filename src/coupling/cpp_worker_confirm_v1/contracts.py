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
        if self.steps != 40 or self.segment_duration_s != 0.05 or self.global_dt_s != 0.00125:
            raise ContractError("scope must be 40 steps, 0.05 s and dt=0.00125 s")
        if self.slice_count != 3:
            raise ContractError("exactly three slices are required")
        if self.source_global_step != 559 or abs(self.source_time_s - 2.2075) > 1e-12 or self.source_tick != 2_207_500_000:
            raise ContractError("only the accepted source step 559 may be used")
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
        if source.get("status") != "committed" or int(source.get("step", -1)) != self.source_global_step:
            raise ContractError("source checkpoint is not the accepted committed step")
        if abs(float(source.get("time_s", float("nan"))) - self.source_time_s) > 1e-12:
            raise ContractError("source checkpoint time mismatch")
        if int(source.get("time_tick", -1)) != self.source_tick:
            raise ContractError("source checkpoint tick mismatch")
        structure = source.get("structure")
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
