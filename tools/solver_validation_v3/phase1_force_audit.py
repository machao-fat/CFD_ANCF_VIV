"""Read-only audit of the historical Stage382 force-scale evidence.

This tool does not infer a missing span or tributary length.  It reports the
historical data as not evaluable whenever those quantities are absent, while
also recording whether the future-run Draft 0.2.1 force contract is present.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LEGACY_RUNTIME = ROOT / "runtime/stage382_cpp_worker_precice_three_slice_continue270_to370_v1"
LEGACY_PARTICIPANT = ROOT / "tools/stage305_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py"
FUTURE_PROTOCOL = ROOT / "src/coupling/multi_slice_mapping/mapping.py"
RESULT = ROOT / "results/solver_validation_v3/phase1_force_scale_audit.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    diagnostic = LEGACY_RUNTIME / "logs/mapping_diagnostics.jsonl"
    first = json.loads(diagnostic.read_text(encoding="utf-8").splitlines()[0])
    participant_text = LEGACY_PARTICIPANT.read_text(encoding="utf-8")
    protocol_text = FUTURE_PROTOCOL.read_text(encoding="utf-8")
    legacy_keys = sorted(first)
    missing = [
        field for field in (
            "slice_id", "s_ref_m", "unit_span_m", "tributary_length_m",
            "force_representation", "openfoam_force_N", "force_2d_Npm",
            "integrated_slice_force_N",
        ) if field not in legacy_keys
    ]
    result = {
        "schema_version": 1,
        "scope": "read-only historical Stage382 force-scale audit",
        "legacy": {
            "runtime": str(LEGACY_RUNTIME),
            "mapping_diagnostics_sha256": sha256(diagnostic),
            "participant_sha256": sha256(LEGACY_PARTICIPANT),
            "diagnostic_fields": legacy_keys,
            "missing_required_force_contract_fields": missing,
            "participant_direct_vertex_force_sum": "def force_sum" in participant_text and "participant.read_data(\"Structure-Mesh\", \"Force\"" in participant_text,
            "participant_passes_force_sum_to_cpp_slice_force": "slice_force=tuple(forces)" in participant_text,
            "physical_force_scaling": "not_evaluable",
            "reason": "Stage382 has no explicit unit_span_m or tributary_length_m, and its participant passes preCICE vertex-force sums directly to the C++ worker.",
        },
        "future_run_contract": {
            "path": str(FUTURE_PROTOCOL),
            "sha256": sha256(FUTURE_PROTOCOL),
            "requires_unit_span_m": "unit_span_m" in protocol_text,
            "requires_integrated_slice_force_representation": "integrated_slice_force_N" in protocol_text,
            "conversion": "F_slice_N = F_openfoam_N / unit_span_m * slice_length_m",
            "missing_field_policy": "fail_closed",
        },
        "conclusion": "Historical mapping conservation does not establish physical force scale. No span or tributary length is inferred from legacy data.",
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"physical_force_scaling": result["legacy"]["physical_force_scaling"], "result": str(RESULT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
