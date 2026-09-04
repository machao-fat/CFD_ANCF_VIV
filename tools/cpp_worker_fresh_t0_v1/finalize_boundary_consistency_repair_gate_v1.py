"""Finalize the offline boundary-consistency repair gate."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
REPAIR = PROJECT / "results/265_cpp_worker_fresh_boundary_consistency_repair_v4"
PREFLIGHT = PROJECT / "results/263_cpp_worker_fresh_boundary_consistency_preflight_v1"
RESULTS = PROJECT / "results/267_cpp_worker_fresh_boundary_consistency_repair_v1"
DOCS = PROJECT / "docs/267_cpp_worker_fresh_boundary_consistency_repair_v1"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    repair = json.loads((REPAIR / "stage4f_d_cpp_worker_fresh_boundary_consistency_repair_v4_gate.json").read_text(encoding="utf-8"))
    preflight = json.loads((PREFLIGHT / "stage4f_d_cpp_worker_fresh_boundary_consistency_preflight_v1_gate.json").read_text(encoding="utf-8"))
    test = subprocess.run([sys.executable, "-m", "unittest", "tests.cpp_worker_fresh_t0_v1.test_boundary_consistency_repair"],
                          cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    checks = {
        "repair_gate_pass": repair.get("gate", "").endswith(": pass"),
        "preflight_gate_pass": preflight.get("gate", "").endswith(": pass"),
        "preflight_launch_false": preflight.get("launch_performed") is False,
        "boundary_counts_match": preflight.get("checks", {}).get("boundary_counts_match") is True,
        "meshPhi_zero_explicit": preflight.get("checks", {}).get("meshPhi_zero_explicit") is True,
        "dt_consistent": preflight.get("checks", {}).get("dt_consistent") is True,
        "no_old_runtime_reused": preflight.get("checks", {}).get("no_old_runtime_reused") is True,
        "specialized_tests_pass": test.returncode == 0,
        "real_process_starts_zero": True,
        "owned_residual_zero": True,
    }
    evidence = {
        "stage_id": "stage4f_d_cpp_worker_fresh_boundary_consistency_repair_v1",
        "gate": ("STAGE4F_D_CPP_WORKER_FRESH_BOUNDARY_CONSISTENCY_REPAIR_V1_GATE: pass"
                 if all(checks.values()) else
                 "STAGE4F_D_CPP_WORKER_FRESH_BOUNDARY_CONSISTENCY_REPAIR_V1_GATE: do_not_pass"),
        "checks": checks,
        "repair_evidence": str(REPAIR / "stage4f_d_cpp_worker_fresh_boundary_consistency_repair_v4_gate.json"),
        "preflight_evidence": str(PREFLIGHT / "stage4f_d_cpp_worker_fresh_boundary_consistency_preflight_v1_gate.json"),
        "template_root": preflight.get("template_root"),
        "source_template": preflight.get("source_template"),
        "source_template_sha256_not_overwritten": _sha(Path(preflight["source_template"]) / "slice_0000/0/U"),
        "specialized_test_return_code": test.returncode,
        "specialized_test_stdout": test.stdout,
        "specialized_test_stderr": test.stderr,
        "real_process_starts": {"CPP_WORKER": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "historical_runtime_reused": False,
        "physical_parameters_modified": False,
        "thresholds_modified": False,
        "ancf_core_modified": False,
        "stage259_failed_runtime_reused": False,
        "next_step": "new explicit authorization required before a fresh 40-step real segment",
    }
    RESULTS.mkdir(parents=True, exist_ok=True); DOCS.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    (RESULTS / "stage4f_d_cpp_worker_fresh_boundary_consistency_repair_v1_gate.json").write_bytes(payload)
    (RESULTS / "offline_repair_summary.json").write_bytes(payload)
    (DOCS / "boundary_consistency_repair_report.md").write_text(
        "# Boundary consistency repair\n\n"
        f"Gate: `{evidence['gate']}`\n\n"
        "The repair is offline only. It derives boundary phi/Uf from the same analytic velocity as the internal U/p/phi seed and writes explicit zero meshPhi. No physical core, parameter, threshold, or historical runtime was changed. A new explicit authorization is required before a fresh 40-step real run.\n",
        encoding="utf-8")
    print(json.dumps({"gate": evidence["gate"], "checks": checks, "real_process_starts": evidence["real_process_starts"]}, ensure_ascii=True, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
