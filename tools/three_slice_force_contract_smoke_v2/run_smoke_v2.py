"""Fresh V2 launcher: preserve V1 raw artifacts, gate only frozen V2 quality."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.openfoam_numerical_quality_contract_v2 import audit_log, evaluate_quality

STAGE = "stage_force_contract_smoke_v2"
RUNTIME = ROOT / "runtime" / f"{STAGE}_run_001"
RESULTS = ROOT / "results" / "three_slice_force_contract_smoke_v2_run_001"
CONTRACT = Path(__file__).with_name("three_slice_force_contract_smoke_v2_run_001.json")
QUALITY_CONTRACT = ROOT / "tools" / "numerical_quality_evidence_closure_v1" / "openfoam_numerical_quality_contract_v2.json"
V1_LAUNCHER = ROOT / "tools" / "three_slice_force_contract_smoke_v1" / "run_smoke.py"


def _load_v1():
    spec = importlib.util.spec_from_file_location("three_slice_force_contract_smoke_v1_launcher", V1_LAUNCHER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen V1 launcher implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RUNTIME, module.RESULTS, module.CONTRACT = RUNTIME, RESULTS, CONTRACT
    return module


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def audit_v2(return_code: int, launcher) -> dict[str, object]:
    # Reuse only the immutable force/mapping/displacement reconciliation logic;
    # its V1 residual outcome is retained below as a diagnostic, not a V2 gate.
    legacy = launcher.audit(return_code)
    quality_contract = json.loads(QUALITY_CONTRACT.read_text(encoding="utf-8"))
    quality: dict[str, object] = {}
    for sid in range(3):
        log = RUNTIME / "logs" / f"fluid_{sid:04d}.stdout"
        fvs = RUNTIME / "cases" / f"slice_{sid:04d}" / "system" / "fvSolution"
        parsed = audit_log(log, fvs)
        quality[str(sid)] = {"audit": parsed, "evaluation": evaluate_quality(parsed, quality_contract)}
    _write(RESULTS / "openfoam_quality_v2.json", quality)
    summary = legacy.get("structure_summary", {})
    evidence_file = RUNTIME / "newton_evidence.jsonl"
    newton_count = len(evidence_file.read_text(encoding="utf-8").splitlines()) if evidence_file.is_file() else 0
    checks = dict(legacy["checks"])
    checks.pop("quality", None)
    checks["openfoam_quality_v2"] = all(item["evaluation"]["status"] == "pass" for item in quality.values())
    checks["ancf_newton_evidence"] = summary.get("newton_evidence", {}).get("status") == "pass" and newton_count == 400
    result = {
        "THREE_SLICE_FORCE_CONTRACT_SMOKE_V2": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "legacy_v1_quality_diagnostic": legacy.get("quality"),
        "openfoam_quality_v2": {sid: item["evaluation"] for sid, item in quality.items()},
        "max_force_error_N": legacy["max_force_error_N"],
        "max_force_function_reconciliation_error_N": legacy["max_force_function_reconciliation_error_N"],
        "max_absolute_moment_error_Nm": legacy["max_absolute_moment_error_Nm"],
        "max_v2_moment_error": legacy["max_v2_moment_error"],
        "max_virtual_work_error": legacy["max_virtual_work_error"],
        "structure_summary": summary,
        "newton_evidence_record_count": newton_count,
        "quality_contract_sha256": hashlib.sha256(QUALITY_CONTRACT.read_bytes()).hexdigest(),
        "formal_status": json.loads(CONTRACT.read_text(encoding="utf-8"))["formal_status"],
        "next_stage_10_to_20s_physical_test": "CONDITIONAL" if all(checks.values()) else "NOT_AUTHORIZED",
    }
    _write(RESULTS / "three_slice_force_contract_smoke_v2_gate.json", result)
    return result


def main() -> int:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to reuse V2 versioned runtime or result paths")
    if not CONTRACT.is_file() or not QUALITY_CONTRACT.is_file():
        raise RuntimeError("fresh V2 contract or frozen quality contract is missing")
    launcher = _load_v1()
    cases = launcher.prepare()
    result = audit_v2(launcher.launch(cases), launcher)
    print(json.dumps({"gate": result["THREE_SLICE_FORCE_CONTRACT_SMOKE_V2"], "results": str(RESULTS)}))
    return 0 if result["THREE_SLICE_FORCE_CONTRACT_SMOKE_V2"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
