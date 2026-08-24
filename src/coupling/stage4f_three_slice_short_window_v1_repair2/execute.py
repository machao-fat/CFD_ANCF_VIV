"""Command-line orchestration for the isolated Stage 4F-C-v1 campaign."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from .analysis import dt_half_audit, restart_audit
from .contract import CASE_ROOT, PARENT_CASE_ROOT, PARENT_CHECKPOINT, PROJECT_ROOT, RESULTS_ROOT, RUNTIME_ROOT, validate_frozen_contract, write_frozen_contract
from .evidence import compare_parent_audits, parent_protection_audit
from .runner import combine_branch, run_segment
from ..stage4f_c_applicationservice_repair_v2.probe import RESULTS_ROOT as PROBE_RESULTS_ROOT


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def freeze() -> dict[str, Any]:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    before = parent_protection_audit()
    atomic_write_json(RESULTS_ROOT / "parent_evidence_hash_before.json", before)
    contract = write_frozen_contract(RESULTS_ROOT / "frozen_comparison_contract.json", before)
    return {"parent": before, "contract": contract}


def _require_contract() -> dict[str, Any]:
    path = RESULTS_ROOT / "frozen_comparison_contract.json"
    value = _read(path)
    validate_frozen_contract(value)
    if sha256_file(PARENT_CHECKPOINT) != value["parent_checkpoint_sha256"]:
        raise RuntimeError("parent checkpoint changed after contract freeze")
    current_parent = parent_protection_audit()
    if current_parent["combined_sha256"] != value["parent_protection_combo_sha256"]:
        raise RuntimeError("parent protection set changed after contract freeze")
    return value


def execute_real() -> dict[str, Any]:
    contract = _require_contract()
    if CASE_ROOT.exists():
        raise FileExistsError(f"isolated v1 case root already exists: {CASE_ROOT}")
    CASE_ROOT.mkdir(parents=True)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    registry: list[dict[str, Any]] = []
    start = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result: dict[str, Any] = {"status": "blocked", "started_utc": start, "contract_sha256": contract["contract_sha256"], "branches": {}}
    try:
        probe_path = PROBE_RESULTS_ROOT / "applicationservice_probe_result.json"
        if not probe_path.is_file():
            result["stop_condition"] = "applicationservice_probe_missing"
            return result
        probe = _read(probe_path)
        result["applicationservice_probe"] = {"path": str(probe_path), "status": probe.get("status"), "run_id": probe.get("run_id"), "log": probe.get("log_path")}
        if probe.get("status") != "passed":
            result["stop_condition"] = "applicationservice_probe_failed"
            return result
        a_root = CASE_ROOT / "branch_A" / "segment_20"
        a_segment = run_segment(root=a_root, branch="A", dt_s=.0025, first_step=0, step_count=20,
            source_checkpoint=PARENT_CHECKPOINT, source_case_root=PARENT_CASE_ROOT, restore_scheduler=False, process_registry=registry)
        branch_a = combine_branch(CASE_ROOT / "branch_A", "A", [a_segment])
        result["branches"]["A"] = branch_a
        if branch_a["status"] != "passed":
            result["stop_condition"] = "branch_A_failed"
            return result

        b1_root = CASE_ROOT / "branch_B" / "segment_5"
        b1 = run_segment(root=b1_root, branch="B", dt_s=.0025, first_step=0, step_count=5,
            source_checkpoint=PARENT_CHECKPOINT, source_case_root=PARENT_CASE_ROOT, restore_scheduler=False, process_registry=registry)
        if b1["status"] != "passed":
            result["branches"]["B"] = combine_branch(CASE_ROOT / "branch_B", "B", [b1])
            result["stop_condition"] = "branch_B_first_segment_failed"
            return result
        if any(not row.get("closed") for row in registry):
            result["stop_condition"] = "owned_process_not_closed_before_restart"
            result["branches"]["B"] = combine_branch(CASE_ROOT / "branch_B", "B", [b1])
            return result
        b_source = Path(b1["steps"][-1]["checkpoint"])
        b2_root = CASE_ROOT / "branch_B" / "segment_15_restart"
        b2 = run_segment(root=b2_root, branch="B", dt_s=.0025, first_step=5, step_count=15,
            source_checkpoint=b_source, source_case_root=b1_root / "cases", restore_scheduler=True, process_registry=registry)
        branch_b = combine_branch(CASE_ROOT / "branch_B", "B", [b1, b2])
        result["branches"]["B"] = branch_b
        if branch_b["status"] != "passed":
            result["stop_condition"] = "branch_B_restart_segment_failed"
            return result
        restart = restart_audit(branch_a, branch_b, RESULTS_ROOT / "restart_identity_audit.json")
        result["restart_identity"] = restart
        if restart["status"] != "passed":
            result["stop_condition"] = "restart_identity_failed"
            return result

        c_root = CASE_ROOT / "branch_C" / "segment_40_dt_half"
        c_segment = run_segment(root=c_root, branch="C", dt_s=.00125, first_step=0, step_count=40,
            source_checkpoint=PARENT_CHECKPOINT, source_case_root=PARENT_CASE_ROOT, restore_scheduler=False, process_registry=registry)
        branch_c = combine_branch(CASE_ROOT / "branch_C", "C", [c_segment])
        result["branches"]["C"] = branch_c
        if branch_c["status"] != "passed":
            result["stop_condition"] = "branch_C_failed"
            return result
        dt_half = dt_half_audit(branch_a, branch_c, PARENT_CHECKPOINT, RESULTS_ROOT / "dt_half_sensitivity_audit.json")
        result["dt_half"] = dt_half
        if dt_half["status"] != "passed":
            result["stop_condition"] = "dt_half_comparison_failed"
            return result
        result["status"] = "passed"
        result["stop_condition"] = None
        return result
    finally:
        for row in registry:
            row.setdefault("closed", False)
        process_audit = {"started": len(registry), "closed": sum(bool(row.get("closed")) for row in registry),
            "residual": sum(not bool(row.get("closed")) for row in registry), "records": registry}
        atomic_write_json(RESULTS_ROOT / "owned_process_registry.json", process_audit)
        result["process_audit"] = {key: process_audit[key] for key in ("started", "closed", "residual")}
        result["finished_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        atomic_write_json(RESULTS_ROOT / "real_execution_summary.json", result)


def closeout() -> dict[str, Any]:
    execution = _read(RESULTS_ROOT / "real_execution_summary.json")
    before = _read(RESULTS_ROOT / "parent_evidence_hash_before.json")
    after = parent_protection_audit()
    atomic_write_json(RESULTS_ROOT / "parent_evidence_hash_after.json", after)
    unchanged = compare_parent_audits(before, after)
    atomic_write_json(RESULTS_ROOT / "parent_evidence_unchanged.json", unchanged)
    return {"execution": execution, "parent_unchanged": unchanged}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "run", "closeout"))
    args = parser.parse_args()
    value = freeze() if args.action == "freeze" else execute_real() if args.action == "run" else closeout()
    print(json.dumps(value, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
