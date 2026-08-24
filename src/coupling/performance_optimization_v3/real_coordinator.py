"""Bounded Stage96 coordinator.

The accepted V2 lifecycle/barrier implementation remains authoritative.  V3
selects only its compatible MATLAB in-memory worker mode and writes all
results into a fresh runtime.  No IPC factor is relabelled as implemented.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from coupling.performance_optimization_v2.real_coordinator import run_contract as run_v2_contract
from .contracts import validate_v3_contract


def run_contract(contract_path: Path) -> dict[str, Any]:
    project_root = Path(__file__).resolve().parents[3]
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    validate_v3_contract(contract, project_root)
    result = run_v2_contract(contract_path)
    result.update({
        "stage_id": str(contract.get("stage_id", "stage96_performance_optimization_v3")),
        "incremental_strategy": str(contract.get("incremental_strategy", "")),
        "matlab_in_memory_state": True,
        "persistent_ipc": False,
        "persistent_ipc_mode": "legacy_file_bridge_unchanged_not_claimed",
        "wsl_native_case_staging": bool(contract.get("wsl_native_case_staging", False)),
        "native_checkpoint_direct": bool(contract.get("native_checkpoint_direct", False)),
        "checkpoint_hash_cache": bool(contract.get("checkpoint_hash_cache", False)),
        "disable_force_coeffs_output": bool(contract.get("disable_force_coeffs_output", False)),
        "compact_force_snapshot": bool(contract.get("compact_force_snapshot", False)),
        "field_write_format": str(contract.get("field_write_format", "ascii")),
        "field_write_precision": int(contract.get("field_write_precision", 16)),
        "ephemeral_exchange_io": bool(contract.get("ephemeral_exchange_io", False)),
        "direct_wsl_exec": bool(contract.get("direct_wsl_exec", False)),
        "cache_gamg_agglomeration": bool(contract.get("cache_gamg_agglomeration", False)),
        "prewarm_openfoam_startup": bool(contract.get("prewarm_openfoam_startup", False)),
        "reuse_parallel_executor": bool(contract.get("reuse_parallel_executor", False)),
        "v2_reference_wall_clock_s": 42.8945183,
        "target_wall_clock_s": 36.5,
    })
    runtime = Path(str(contract["runtime"])).resolve()
    temporary = runtime / "benchmark_result.v3.tmp"
    temporary.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, runtime / "benchmark_result.json")
    return result


def main() -> int:
    raw = os.environ.get("CFD_ANCF_BENCHMARK_CONTRACT", "")
    if not raw:
        raise SystemExit("CFD_ANCF_BENCHMARK_CONTRACT is missing")
    result = run_contract(Path(raw))
    print(json.dumps({"status": result.get("status"), "gate": result.get("gate"),
                      "runtime": str(Path(raw).resolve().parent)}, ensure_ascii=True))
    return 0 if result.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
