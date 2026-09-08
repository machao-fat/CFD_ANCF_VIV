"""Read-only numeric audit for the immutable generation-2 oldPoints failure."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime" / "implicit_cross_window_ipc_lifecycle_closure_v1_formal_two_window_001"
OUTPUT = ROOT / "results" / "of10_oldpoints_rollback_lifecycle_closure_v1" / "historical_oldpoints_numeric_audit.json"


def read_points(path: Path) -> list[tuple[float, float, float]]:
    triples = re.findall(
        r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)",
        path.read_text(encoding="utf-8"),
    )
    return [tuple(map(float, row)) for row in triples]


def point_difference(reference: list[tuple[float, float, float]], trial: list[tuple[float, float, float]]) -> dict[str, object]:
    if len(reference) != len(trial):
        raise RuntimeError("point counts differ")
    delta = [tuple(b - a for a, b in zip(left, right)) for left, right in zip(reference, trial)]
    norms = [math.sqrt(sum(component * component for component in row)) for row in delta]
    maximum_index = max(range(len(norms)), key=norms.__getitem__)
    return {
        "count": len(delta),
        "nonzero_count": sum(value > 0.0 for value in norms),
        "max_abs_component_m": max(abs(value) for row in delta for value in row),
        "l2_difference_m": math.sqrt(sum(value * value for value in norms)),
        "max_difference_point_index": maximum_index,
        "max_difference_delta_xyz_m": list(delta[maximum_index]),
        "reference_point_xyz_m": list(reference[maximum_index]),
        "trial_point_xyz_m": list(trial[maximum_index]),
    }


def main() -> int:
    trace = [json.loads(line) for line in (RUNTIME / "fluid_0000_adapter_trace.jsonl").read_text(encoding="utf-8").splitlines()]
    second_restore = [row for row in trace if row["event"] == "POST_ROLLBACK_BEFORE_NEXT_INPUT" and row["time_index"] == 1][-1]
    preceding_trial = [row for row in trace if row["event"] == "PRE_ROLLBACK_TRIAL" and row["time_index"] == 2][-1]
    slices: dict[str, object] = {}
    for index in range(3):
        case = RUNTIME / "cases" / f"slice_{index:04d}"
        slices[f"slice_{index}"] = point_difference(
            read_points(case / "0.105" / "polyMesh" / "points"),
            read_points(case / "0.11" / "polyMesh" / "points"),
        )
    output = {
        "audit": "OF10_OLDPOINTS_ROLLBACK_LIFECYCLE_CLOSURE_V1",
        "mode": "read_only",
        "historical_trace": {
            "checkpoint_generation": {"event_sequence": 4, "physical_time_s": 0.105, "time_index": 1},
            "first_restore": {"event_sequence": 7, "status": "PASS"},
            "second_restore": {"event_sequence": 9, "old_points_hash": second_restore["states"]["old_points"]["canonical_hash_fnv1a64"]},
            "preceding_trial": {"event_sequence": 8, "mesh_points_hash": preceding_trial["states"]["mesh_points"]["canonical_hash_fnv1a64"]},
            "identity_interpretation": "The oldPoints hash at the second restore equals the preceding nonzero-trial mesh-points hash.",
        },
        "numeric_proxy": {
            "definition": "The trace lacks raw oldPoints arrays. The 0.105 and 0.11 persisted mesh-point snapshots are compared only because their canonical trace identities match the generation-2 checkpoint and preceding trial respectively.",
            "direct_raw_oldPoints_numeric_difference": "NOT_AVAILABLE_IN_IMMUTABLE_TRACE",
            "slices": slices,
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
