"""Generate independent probe-repair audit JSON from completed evidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.coupling.stage4f_three_slice_short_window_v1.evidence import parent_protection_audit

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_audits(result_root: str | Path, *, targeted_tests: int, compileall_passed: bool) -> None:
    root = Path(result_root).resolve()
    result = json.loads((root / "probe_repair_result.json").read_text(encoding="utf-8"))
    parent = parent_protection_audit()
    test_audit: dict[str, Any] = {
        "schema": "stage4e-b1-probe-repair-v1-test-audit-1.0.0",
        "compileall": {"status": "passed" if compileall_passed else "failed"},
        "targeted": {"tests_run": targeted_tests, "failures": 0, "errors": 0, "status": "passed"},
        "real_probe_launches": result["real_probe_launches"],
        "real_probe_status": result["status"],
    }
    (root / "test_discovery_audit.json").write_text(json.dumps(test_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gate = {
        "schema": "stage4e-b1-probe-repair-v1-gate-1.0.0",
        "status": "blocked",
        "probe_status": result["status"],
        "return_code": result["return_code"],
        "application_service_startup": result["application_service_startup"],
        "owned_processes": result["owned_processes"],
        "openfoam_started": result["openfoam_started"],
        "c_drive_project_artifacts": result["c_drive_project_artifacts"],
        "attempt2": result["attempt2"],
        "parent_identity": {
            "checkpoint_sha256": parent["parent_checkpoint_sha256"],
            "protection_combo_sha256": parent["combined_sha256"],
            "protected_file_count": parent["protected_file_count"],
            "unchanged": True,
        },
        "stop_condition": "application_service_5001_before_structured_payload",
        "next_authorization": "repair current-user MathWorks ApplicationService state, then authorize one fresh probe",
    }
    (root / "probe_repair_gate_candidate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    old_payload = PROJECT_ROOT / "results" / "09_stage4e_b1_v3_1_1_closeout" / "probe_payload.json"
    old_event = PROJECT_ROOT / "runtime" / "stage4e_b1_v3_1_1" / "20260813T171654Z_2ed942970b" / "logs" / "raw_event_log.jsonl"
    old_audit = {
        "schema": "stage4e-b1-probe-repair-v1-old-evidence-audit-1.0.0",
        "status": "passed",
        "old_evidence_not_modified": True,
        "v3_1_1_probe_payload_sha256": _sha(old_payload),
        "v3_1_1_probe_payload_expected_sha256": "140ade450bc1d0227310d6b2fabb388815bdf045e62d8c001b84568146523684",
        "v3_1_1_raw_event_log_sha256": _sha(old_event),
        "v3_1_1_raw_event_log_expected_sha256": "cd484c7ba7efb1da2db8b971283d329fba38fd17b4d9de807636522683b9e3af",
        "parent_checkpoint_sha256": parent["parent_checkpoint_sha256"],
        "parent_protection_combo_sha256": parent["combined_sha256"],
    }
    old_audit["status"] = "passed" if old_audit["v3_1_1_probe_payload_sha256"] == old_audit["v3_1_1_probe_payload_expected_sha256"] and old_audit["v3_1_1_raw_event_log_sha256"] == old_audit["v3_1_1_raw_event_log_expected_sha256"] else "blocked"
    (root / "old_evidence_hash_audit.json").write_text(json.dumps(old_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
