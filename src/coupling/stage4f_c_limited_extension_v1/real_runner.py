"""Run the frozen ten-step extension and authorized midpoint restart."""
from __future__ import annotations

import json
from pathlib import Path

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from ..stage4f_c_restart_extended_v1 import real_runner as base
from ..stage4f_c_restart_identity_v1.compare import RestartIdentityTolerances, compare_checkpoint_files
from .contract import PARENT_SHA256, build_contract, validate_contract
from .lineage import build_ledger, validate_ledger
from .terminal_force import CandidateIterationEngine

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PARENT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_c_restart_extended_v1_attempt3_force_terminal_repair" / "extension" / "step_09" / "iteration_05" / "checkpoints" / "checkpoint_step00000009_bfd22841c9ad.json"
CASE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_c_limited_extension_v1_attempt1"
RESULT_ROOT = PROJECT_ROOT / "results" / "17_stage4f_c_limited_extension_v1_attempt1"


def _segment(**kwargs):
    old = base.CandidateIterationEngine
    base.CandidateIterationEngine = CandidateIterationEngine
    try:
        return base._run_segment(**kwargs)
    finally:
        base.CandidateIterationEngine = old


def run():
    if sha256_file(PARENT) != PARENT_SHA256:
        raise RuntimeError("accepted step9 parent checkpoint hash mismatch")
    if CASE_ROOT.exists() or (RESULT_ROOT.exists() and any(RESULT_ROOT.iterdir())):
        raise FileExistsError("limited extension roots must be new")
    RESULT_ROOT.mkdir(parents=True)
    contract = build_contract()
    validate_contract(contract)
    atomic_write_json(RESULT_ROOT / "limited_extension_contract.json", contract)
    block1 = _segment(name="continuous_block1", parent=PARENT, start_step=10, end_step=15, case_root=CASE_ROOT / "continuous_block1", result_root=RESULT_ROOT)
    block2 = None
    if block1["status"] == "passed" and block1["processes"]["residual"] == 0:
        block2 = _segment(name="continuous_block2", parent=Path(block1["final_checkpoint"]), start_step=15, end_step=20, case_root=CASE_ROOT / "continuous_block2", result_root=RESULT_ROOT)
    continuous_passed = block2 is not None and block2["status"] == "passed" and block2["processes"]["residual"] == 0
    continuous_steps = list(block1["steps"]) + ([] if block2 is None else list(block2["steps"]))
    continuous = {"status": "passed" if continuous_passed else "failed", "steps": continuous_steps, "block1": block1, "block2": block2}
    restart = None
    comparisons = []
    identity = False
    if continuous_passed:
        midpoint = Path(block1["final_checkpoint"])
        restart = _segment(name="midpoint_restart", parent=midpoint, start_step=15, end_step=20, case_root=CASE_ROOT / "midpoint_restart", result_root=RESULT_ROOT)
        if restart["status"] == "passed":
            tolerance = RestartIdentityTolerances(structure_relative_linf=1e-11, previous_force_relative_linf=1e-11, time_absolute_s=1e-12)
            references = [Path(row["checkpoint"]) for row in block2["steps"]]
            candidates = [Path(row["checkpoint"]) for row in restart["steps"]]
            comparisons = [compare_checkpoint_files(ref, cand, tolerances=tolerance) for ref, cand in zip(references, candidates)]
        identity = restart["status"] == "passed" and len(comparisons) == 5 and all(row["passed"] for row in comparisons) and restart["processes"]["residual"] == 0
    atomic_write_json(RESULT_ROOT / "midpoint_restart_identity.json", {"passed": identity, "comparisons": comparisons})
    ledgers = {}
    if block1["status"] == "passed":
        ledgers["continuous_block1"] = build_ledger(block1["steps"], block_id="continuous_block1", contract_sha256=contract["contract_sha256"])
    if block2 is not None and block2["status"] == "passed":
        ledgers["continuous_block2"] = build_ledger(block2["steps"], block_id="continuous_block2", contract_sha256=contract["contract_sha256"])
    if restart is not None and restart["status"] == "passed":
        ledgers["midpoint_restart"] = build_ledger(restart["steps"], block_id="midpoint_restart", contract_sha256=contract["contract_sha256"])
    if "continuous_block2" in ledgers:
        validate_ledger(ledgers["continuous_block1"] + ledgers["continuous_block2"], contract_sha256=contract["contract_sha256"], expected_initial_parent_sha256=PARENT_SHA256)
    if "midpoint_restart" in ledgers:
        validate_ledger(ledgers["midpoint_restart"], contract_sha256=contract["contract_sha256"], expected_initial_parent_sha256=block1["final_checkpoint_sha256"])
    atomic_write_json(RESULT_ROOT / "external_lineage_ledgers.json", ledgers)
    passed = continuous_passed and identity and all(len(ledgers.get(key, [])) == 5 for key in ("continuous_block1", "continuous_block2", "midpoint_restart"))
    summary = {"schema": "stage4f-c-limited-extension-v1-result-1.0.0", "status": "passed" if passed else "failed", "contract_sha256": contract["contract_sha256"], "parent_checkpoint": str(PARENT), "parent_checkpoint_sha256": PARENT_SHA256, "continuous": continuous, "midpoint_restart": restart, "midpoint_restart_identity_passed": identity, "midpoint_restart_comparisons": comparisons, "external_lineage_ledgers": ledgers}
    atomic_write_json(RESULT_ROOT / "real_execution_summary.json", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
