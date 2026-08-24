from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from coupling.performance_optimization_v2.contracts import BenchmarkContract, canonical_bytes, contract_hash


def make_contract(*, project_root: Path, runtime: Path, source_checkpoint: Path,
                  run_id: str, case_id: str, matlab_executable: str,
                  wsl_native_case_staging: bool = True,
                  native_checkpoint_direct: bool = True,
                  checkpoint_hash_cache: bool = False,
                  disable_force_coeffs_output: bool = False,
                  openfoam_poll_interval_s: float = 0.001,
                  compact_force_snapshot: bool = False,
                  protocol_poll_interval_s: float = 0.001,
                  field_write_format: str = "ascii",
                  direct_wsl_exec: bool = False,
                  field_write_precision: int = 16,
                  ephemeral_exchange_io: bool = False,
                  prewarm_openfoam_startup: bool = False,
                  reuse_parallel_executor: bool = False) -> dict[str, Any]:
    """Create the bounded V3 contract without changing the V2 physics scope."""
    value = BenchmarkContract(
        "stage96_performance_optimization_v3", run_id, case_id, runtime,
        source_checkpoint, 559, 2.2075, 2207500000,
        source_checkpoint_sha256=hashlib.sha256(source_checkpoint.read_bytes()).hexdigest(),
        factors=("M", "O", "P"), matlab_executable=matlab_executable,
    ).to_dict()
    value["configuration_label"] = "M+O+P"
    bridge = (project_root / "src" / "coupling" / "performance_matlab_worker_bridge_v1").resolve().as_posix()
    runtime_expr = runtime.resolve().as_posix()
    value["matlab_batch_command"] = f"addpath(genpath('{bridge}')); matlab_worker_loop('{runtime_expr}')"
    value["matlab_in_memory_state"] = True
    value["incremental_strategy"] = (
        "matlab_in_memory_state_plus_prepare_hash_cache_plus_diagnostic_output_suppression"
        if checkpoint_hash_cache and not wsl_native_case_staging
        else "matlab_in_memory_state_plus_wsl_native_case_staging"
    )
    value["persistent_ipc"] = False
    value["persistent_ipc_mode"] = "legacy_file_bridge_unchanged_not_claimed"
    value["openfoam_poll_interval_s"] = float(openfoam_poll_interval_s)
    value["disable_force_coeffs_output"] = bool(disable_force_coeffs_output)
    value["compact_force_snapshot"] = bool(compact_force_snapshot)
    value["protocol_poll_interval_s"] = float(protocol_poll_interval_s)
    value["field_write_format"] = str(field_write_format)
    value["direct_wsl_exec"] = bool(direct_wsl_exec)
    value["field_write_precision"] = int(field_write_precision)
    value["ephemeral_exchange_io"] = bool(ephemeral_exchange_io)
    value["prewarm_openfoam_startup"] = bool(prewarm_openfoam_startup)
    value["reuse_parallel_executor"] = bool(reuse_parallel_executor)
    value["cache_gamg_agglomeration"] = True
    value["wsl_native_case_staging"] = bool(wsl_native_case_staging)
    value["native_checkpoint_direct"] = bool(native_checkpoint_direct)
    value["checkpoint_hash_cache"] = bool(checkpoint_hash_cache)
    value["contract_sha256"] = contract_hash(value)
    return value


def validate_v3_contract(value: Mapping[str, Any], project_root: Path) -> None:
    from coupling.performance_optimization_v2.contracts import validate_serialized_contract
    validate_serialized_contract(value, project_root)
    if value.get("stage_id") not in {
        "stage96_performance_optimization_v3",
        "stage4f_d_performance_phase_timing_confirm_v1",
    }:
        raise ValueError("V3 stage identity mismatch")
    if value.get("matlab_in_memory_state") is not True:
        raise ValueError("V3 must explicitly enable MATLAB in-memory state")
    if value.get("persistent_ipc") is not False:
        raise ValueError("unimplemented IPC cannot be claimed")
    if not isinstance(value.get("wsl_native_case_staging"), bool):
        raise ValueError("V3 must explicitly declare WSL-native staging")
    if not isinstance(value.get("native_checkpoint_direct"), bool):
        raise ValueError("V3 must explicitly declare native checkpoint mode")
    if not isinstance(value.get("checkpoint_hash_cache"), bool):
        raise ValueError("V3 must explicitly declare checkpoint hash cache mode")
    if not isinstance(value.get("compact_force_snapshot"), bool):
        raise ValueError("V3 must explicitly declare force snapshot mode")
    if value.get("field_write_format") not in {"ascii", "binary"}:
        raise ValueError("field_write_format must be ascii or binary")
    precision = value.get("field_write_precision")
    if isinstance(precision, bool) or not isinstance(precision, int) or not (8 <= precision <= 17):
        raise ValueError("field_write_precision must be an integer in [8, 17]")
    if not isinstance(value.get("ephemeral_exchange_io"), bool):
        raise ValueError("ephemeral_exchange_io must be explicit")
    if not isinstance(value.get("direct_wsl_exec"), bool):
        raise ValueError("direct_wsl_exec must be explicit")
    if not isinstance(value.get("prewarm_openfoam_startup", False), bool):
        raise ValueError("prewarm_openfoam_startup must be boolean")
    if not isinstance(value.get("reuse_parallel_executor", False), bool):
        raise ValueError("reuse_parallel_executor must be boolean")
    protocol_poll = value.get("protocol_poll_interval_s")
    if isinstance(protocol_poll, bool) or not isinstance(protocol_poll, (int, float)) or not (0.001 <= float(protocol_poll) <= 1.0):
        raise ValueError("protocol poll interval must be bounded to [0.001, 1.0] s")
    if value.get("native_checkpoint_direct") and not value.get("wsl_native_case_staging"):
        raise ValueError("native direct checkpoint mode requires WSL-native staging")
    poll = value.get("openfoam_poll_interval_s")
    if isinstance(poll, bool) or not isinstance(poll, (int, float)) or not (0.001 <= float(poll) <= 1.0):
        raise ValueError("OpenFOAM poll interval must be bounded to [0.001, 1.0] s")
