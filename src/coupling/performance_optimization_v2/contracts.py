from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "cfd_ancf_viv_performance_optimization_v2.0"
FORMAL_PROTOCOL_VERSION = "0.2.1"
FACTORS = ("M", "O", "P", "I", "A", "T", "D")


class ContractError(ValueError):
    """Fail-closed benchmark contract error."""


class Factor:
    MATLAB_PERSISTENT = "M"
    OPENFOAM_PERSISTENT = "O"
    THREE_SLICE_PARALLEL = "P"
    PERSISTENT_IPC = "I"
    AUDIT_BATCHING = "A"
    LIFECYCLE = "T"
    DIAGNOSTICS = "D"


def canonical_bytes(value: Any) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                           separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError(f"non-canonical JSON: {exc}") from exc


def contract_hash(contract: Mapping[str, Any]) -> str:
    payload = {k: v for k, v in contract.items() if k not in {"contract_sha256", "contract_hash"}}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _finite(value: Any, name: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _finite(item, f"{name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _finite(item, f"{name}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ContractError(f"{name} contains NaN/Inf")


@dataclass(frozen=True)
class BenchmarkContract:
    stage_id: str
    run_id: str
    case_id: str
    runtime: Path
    source_checkpoint: Path
    source_global_step: int
    source_time_s: float
    source_tick: int
    source_checkpoint_sha256: str | None = None
    steps: int = 40
    segment_duration_s: float = 0.05
    global_dt_s: float = 0.00125
    slice_count: int = 3
    factors: tuple[str, ...] = ()
    expected_session_id: int = 1
    expected_username: str = "Administrator"
    no_retry: bool = True
    matlab_executable: str = r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe"
    matlab_batch_command: str | None = None
    coordinator_command: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": SCHEMA_VERSION,
            "formal_protocol_version": FORMAL_PROTOCOL_VERSION,
            "stage_id": self.stage_id, "run_id": self.run_id, "case_id": self.case_id,
            "runtime": str(self.runtime), "source_checkpoint": str(self.source_checkpoint),
            "source_global_step": self.source_global_step, "source_time_s": self.source_time_s,
            "source_tick": self.source_tick, "steps": self.steps,
            "segment_duration_s": self.segment_duration_s, "global_dt_s": self.global_dt_s,
            "slice_count": self.slice_count, "factors": list(self.factors),
            "expected_session_id": self.expected_session_id,
            "expected_username": self.expected_username, "no_retry": self.no_retry,
            "matlab_executable": self.matlab_executable, "matlab_batch_command": self.matlab_batch_command,
            "coordinator_command": self.coordinator_command,
            "scope": {"no_statistics": True, "no_e5c": True, "no_five_slice": True,
                      "no_nine_slice": True, "no_long_time_viv": True,
                      "no_lock_in": True, "no_experiment": True},
        }
        if self.source_checkpoint_sha256:
            value["source_checkpoint_sha256"] = str(self.source_checkpoint_sha256)
        value["contract_sha256"] = contract_hash(value)
        return value

    def validate(self, project_root: Path) -> None:
        if not self.stage_id or not self.run_id or not self.case_id:
            raise ContractError("stage/run/case identity is required")
        if self.steps != 40 or self.segment_duration_s != 0.05 or self.global_dt_s != 0.00125:
            raise ContractError("benchmark scope must remain 40 steps, 0.05 s, dt=0.00125 s")
        if self.slice_count != 3:
            raise ContractError("benchmark requires exactly three slices")
        if self.expected_session_id != 1 or self.expected_username != "Administrator":
            raise ContractError("benchmark requires Administrator Console SessionId=1")
        if not self.matlab_executable.lower().endswith("matlab.exe"):
            raise ContractError("MATLAB executable identity is invalid")
        if self.coordinator_command is not None and (not isinstance(self.coordinator_command, list) or not self.coordinator_command):
            raise ContractError("coordinator command must be a non-empty argv list")
        if not self.no_retry:
            raise ContractError("same-runtime retry is forbidden")
        if any(item not in FACTORS for item in self.factors) or len(set(self.factors)) != len(self.factors):
            raise ContractError("unknown or duplicate optimization factor")
        if self.source_global_step < 0 or self.source_tick < 0 or not math.isfinite(self.source_time_s):
            raise ContractError("invalid source identity")
        root = project_root.resolve()
        for label, path in (("runtime", self.runtime), ("source_checkpoint", self.source_checkpoint)):
            resolved = Path(path).resolve()
            if resolved.drive.upper() != "D:":
                raise ContractError(f"{label} must be on D:")
            if root not in resolved.parents and resolved != root:
                raise ContractError(f"{label} outside project")
        if self.source_checkpoint_sha256 is not None:
            digest = hashlib.sha256(self.source_checkpoint.read_bytes()).hexdigest()
            if digest != str(self.source_checkpoint_sha256):
                raise ContractError("source checkpoint SHA-256 mismatch")


def validate_serialized_contract(value: Mapping[str, Any], project_root: Path) -> None:
    required = {"schema_version", "formal_protocol_version", "contract_sha256", "stage_id", "run_id", "case_id",
                "runtime", "source_checkpoint", "source_global_step", "source_time_s", "source_tick", "steps",
                "segment_duration_s", "global_dt_s", "slice_count", "factors", "expected_session_id",
                "expected_username", "no_retry", "scope"}
    missing = sorted(required - value.keys())
    if missing:
        raise ContractError("missing contract fields: " + ",".join(missing))
    if value["schema_version"] != SCHEMA_VERSION or value["formal_protocol_version"] != FORMAL_PROTOCOL_VERSION:
        raise ContractError("unsupported contract version")
    if value["contract_sha256"] != contract_hash(value):
        raise ContractError("contract hash mismatch")
    _finite(value, "contract")
    expected_scope = {"no_statistics": True, "no_e5c": True, "no_five_slice": True,
                      "no_nine_slice": True, "no_long_time_viv": True,
                      "no_lock_in": True, "no_experiment": True}
    if value["scope"] != expected_scope:
        raise ContractError("benchmark scope expansion")
    contract = BenchmarkContract(stage_id=str(value["stage_id"]), run_id=str(value["run_id"]),
        case_id=str(value["case_id"]), runtime=Path(str(value["runtime"])),
        source_checkpoint=Path(str(value["source_checkpoint"])), source_global_step=int(value["source_global_step"]),
        source_time_s=float(value["source_time_s"]), source_tick=int(value["source_tick"]),
        source_checkpoint_sha256=value.get("source_checkpoint_sha256"), steps=int(value["steps"]),
        segment_duration_s=float(value["segment_duration_s"]), global_dt_s=float(value["global_dt_s"]),
        slice_count=int(value["slice_count"]), factors=tuple(value["factors"]),
        expected_session_id=int(value["expected_session_id"]), expected_username=str(value["expected_username"]),
        no_retry=bool(value["no_retry"]), matlab_executable=str(value.get("matlab_executable", "")),
        matlab_batch_command=value.get("matlab_batch_command"), coordinator_command=value.get("coordinator_command"))
    contract.validate(project_root)
