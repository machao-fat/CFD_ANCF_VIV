from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..multi_slice_mapping.mapping import sha256_file
from ..stage4f_three_slice_timestep_diagnostic_v2.contract import validate_contract
from ..stage4f_three_slice_timestep_diagnostic_v2.execute import branch_plan


def preflight(*, contract_path: Path, branch: str, case_root: Path, runtime_root: Path,
              results_root: Path, parent_checkpoint: Path) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    validate_contract(contract)
    errors = []
    if branch != "D2":
        errors.append("v3_only_authorizes_D2")
    if not parent_checkpoint.is_file() or sha256_file(parent_checkpoint) != contract["parent_checkpoint_sha256"]:
        errors.append("parent_checkpoint_identity")
    roots = (case_root.resolve(), runtime_root.resolve(), results_root.resolve())
    if len({str(path).lower() for path in roots}) != 3:
        errors.append("roots_not_isolated")
    if any("stage4f_three_slice_timestep_diagnostic_v3" not in str(path) for path in roots):
        errors.append("non_v3_root")
    plan = branch_plan(branch, case_root, parent_checkpoint)
    plan["case_root"] = str((case_root / f"branch_{branch}").resolve())
    plan["runtime_root"] = str(runtime_root.resolve())
    plan["results_root"] = str(results_root.resolve())
    return {"status": "passed" if not errors else "blocked", "branch": branch, "errors": errors, "plan": plan}

