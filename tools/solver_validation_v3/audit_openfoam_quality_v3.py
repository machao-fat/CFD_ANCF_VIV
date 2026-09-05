"""Read-only historical quality audit with separate completeness semantics."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.openfoam_quality_contract_v3 import audit_records  # noqa: E402


SEGMENTS = (
    "stage381_cpp_worker_precice_three_slice_continue220_to270_v1",
    "stage382_cpp_worker_precice_three_slice_continue270_to370_v1",
)
RESULT = ROOT / "results/solver_validation_v3/openfoam_quality_semantics_v3.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if RESULT.exists():
        raise RuntimeError(f"refusing to overwrite quality evidence: {RESULT}")
    output: dict[str, object] = {"schema_version": "openfoam_quality_semantics_v3.1", "scope": "read-only historical Stage381/382 audit", "segments": {}}
    for name in SEGMENTS:
        runtime = ROOT / "runtime" / name
        mapping = [json.loads(line) for line in (runtime / "logs/mapping_diagnostics.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        slices: dict[str, object] = {}
        for index in range(3):
            path = runtime / "logs" / f"openfoam_{index:04d}_quality.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = payload.get("records", [])
            slices[f"slice_{index:04d}"] = {"path": str(path), "sha256": sha256(path),
                                                **audit_records(records, expected_count=len(mapping), expected_start_s=float(mapping[0]["time_s"]))}
        output["segments"][name] = {"mapping_record_count": len(mapping), "slices": slices}
    output["historical_interpretation"] = {
        "OBSERVABILITY_COMPLETENESS": "records are assessed for count, alignment, required fields and finite values",
        "NUMERICAL_QUALITY": "not_evaluable unless an explicit pre-run numerical contract is retained; historical record completeness is not a convergence claim",
    }
    output["real_process_starts"] = {"CFD": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL": 0}
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": str(RESULT), "segments": list(output["segments"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
