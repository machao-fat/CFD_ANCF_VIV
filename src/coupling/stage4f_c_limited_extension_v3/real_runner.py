from __future__ import annotations

import json
from pathlib import Path

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from ..stage4f_c_restart_extended_v1 import real_runner as base
from ..stage4f_c_restart_identity_v1.compare import RestartIdentityTolerances, compare_checkpoint_files
from ..stage4f_c_limited_extension_v1.lineage import build_ledger, validate_ledger
from ..stage4f_c_limited_extension_v1.terminal_force import CandidateIterationEngine
from .contract import BLOCKS, PARENT_SHA256, build_contract, validate_contract

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PARENT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_c_limited_extension_v1_attempt1" / "continuous_block2" / "step_19" / "iteration_03" / "checkpoints" / "checkpoint_step00000019_4a851ae08ee5.json"
CASE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_c_limited_extension_v2_attempt1"
RESULT_ROOT = PROJECT_ROOT / "results" / "18_stage4f_c_limited_extension_v2_attempt1"


def _segment(**kwargs):
    old = base.CandidateIterationEngine; base.CandidateIterationEngine = CandidateIterationEngine
    try: return base._run_segment(**kwargs)
    finally: base.CandidateIterationEngine = old


def run():
    if sha256_file(PARENT) != PARENT_SHA256: raise RuntimeError("accepted step19 parent hash mismatch")
    if CASE_ROOT.exists() or (RESULT_ROOT.exists() and any(RESULT_ROOT.iterdir())): raise FileExistsError("v2 roots must be new")
    RESULT_ROOT.mkdir(parents=True); contract = build_contract(); validate_contract(contract)
    atomic_write_json(RESULT_ROOT / "limited_extension_v2_contract.json", contract)
    blocks = []; parent = PARENT
    for index, (start, end) in enumerate(BLOCKS, 1):
        if blocks and (blocks[-1]["status"] != "passed" or blocks[-1]["processes"]["residual"] != 0): break
        row = _segment(name=f"continuous_block{index}", parent=parent, start_step=start, end_step=end, case_root=CASE_ROOT / f"continuous_block{index}", result_root=RESULT_ROOT)
        blocks.append(row); parent = Path(row["final_checkpoint"])
    continuous_passed = len(blocks) == 4 and all(x["status"] == "passed" and x["processes"]["residual"] == 0 for x in blocks)
    restart = None; comparisons = []; identity = False
    if continuous_passed:
        restart_parent = Path(blocks[2]["final_checkpoint"])
        restart = _segment(name="final_window_restart", parent=restart_parent, start_step=35, end_step=40, case_root=CASE_ROOT / "final_window_restart", result_root=RESULT_ROOT)
        if restart["status"] == "passed":
            tol = RestartIdentityTolerances(structure_relative_linf=1e-11, previous_force_relative_linf=1e-11, time_absolute_s=1e-12)
            comparisons = [compare_checkpoint_files(Path(ref["checkpoint"]), Path(cand["checkpoint"]), tolerances=tol) for ref, cand in zip(blocks[3]["steps"], restart["steps"])]
        identity = restart["status"] == "passed" and restart["processes"]["residual"] == 0 and len(comparisons) == 5 and all(x["passed"] for x in comparisons)
    atomic_write_json(RESULT_ROOT / "final_window_restart_identity.json", {"passed": identity, "comparisons": comparisons})
    ledgers = {}; continuous_entries = []
    for index, block in enumerate(blocks, 1):
        if block["status"] == "passed":
            rows = build_ledger(block["steps"], block_id=f"continuous_block{index}", contract_sha256=contract["contract_sha256"])
            ledgers[f"continuous_block{index}"] = rows; continuous_entries.extend(rows)
    if continuous_passed: validate_ledger(continuous_entries, contract_sha256=contract["contract_sha256"], expected_initial_parent_sha256=PARENT_SHA256)
    if restart is not None and restart["status"] == "passed":
        rows = build_ledger(restart["steps"], block_id="final_window_restart", contract_sha256=contract["contract_sha256"])
        validate_ledger(rows, contract_sha256=contract["contract_sha256"], expected_initial_parent_sha256=blocks[2]["final_checkpoint_sha256"])
        ledgers["final_window_restart"] = rows
    atomic_write_json(RESULT_ROOT / "external_lineage_ledgers.json", ledgers)
    passed = continuous_passed and identity and len(continuous_entries) == 20 and len(ledgers.get("final_window_restart", [])) == 5
    summary = {"schema": "stage4f-c-limited-extension-v2-result-1.0.0", "status": "passed" if passed else "failed", "contract_sha256": contract["contract_sha256"], "parent_checkpoint_sha256": PARENT_SHA256, "continuous_blocks": blocks, "continuous_passed": continuous_passed, "final_window_restart": restart, "restart_identity_passed": identity, "restart_comparisons": comparisons, "lineage_counts": {k: len(v) for k,v in ledgers.items()}}
    atomic_write_json(RESULT_ROOT / "real_execution_summary.json", summary); return summary


if __name__ == "__main__": print(json.dumps(run(), ensure_ascii=False, indent=2))
