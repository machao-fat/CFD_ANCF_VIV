"""Read-only structured comparison for the compatible-Uf counterfactual."""

from __future__ import annotations

import json
from pathlib import Path

import inspect_openfoam_fields as parser


ROOT = Path(__file__).resolve().parents[2]
CASES = {
    "fixed": ROOT / "runtime/cfd_current_fixed_zero_bridge_v1_run_002/fixed_case",
    "original_zero": ROOT / "runtime/cfd_current_fixed_zero_bridge_v1_run_002/zero_precice_case",
    "compatible_uf": ROOT / "runtime/cfd_current_fixed_zero_bridge_v1_compatible_uf_counterfactual_v1/case",
}
FIELDS = ("U", "p", "phi", "pointDisplacement", "cellDisplacement", "meshPhi", "Uf")
TIMES = ("0.1", "0.105")


def semantic(record: dict) -> str | None:
    if not record.get("exists"):
        return None
    return json.dumps(
        {key: record.get(key) for key in ("class", "object", "dimensions", "internalField", "boundaryField")},
        sort_keys=True,
        separators=(",", ":"),
    )


def internal_values(path: Path) -> list[float] | None:
    if not path.is_file():
        return None
    text = parser.strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    expression = parser.entry(text, "internalField")
    return parser.parsed_values(expression or "").get("values", [])


def numeric_difference(left: list[float] | None, right: list[float] | None) -> dict | None:
    if left is None or right is None or len(left) != len(right):
        return None
    differences = [a - b for a, b in zip(left, right)]
    return {
        "count": len(differences),
        "max_abs": max((abs(value) for value in differences), default=0.0),
        "l2": sum(value * value for value in differences) ** 0.5,
    }


def main() -> int:
    result = []
    for time_name in TIMES:
        for field_name in FIELDS:
            records = {
                case_name: parser.field(case / time_name / field_name)
                if (case / time_name / field_name).is_file()
                else {"exists": False}
                for case_name, case in CASES.items()
            }
            result.append(
                {
                    "time": time_name,
                    "field": field_name,
                    "exists": {name: value.get("exists", False) for name, value in records.items()},
                    "fixed_vs_compatible": semantic(records["fixed"]) == semantic(records["compatible_uf"])
                    and semantic(records["fixed"]) is not None,
                    "original_vs_compatible": semantic(records["original_zero"])
                    == semantic(records["compatible_uf"])
                    and semantic(records["original_zero"]) is not None,
                    "internal_summary": {
                        name: records[name].get("internalField")
                        for name in records
                        if records[name].get("exists")
                    },
                    "internal_numeric_difference_fixed_compatible": numeric_difference(
                        internal_values(CASES["fixed"] / time_name / field_name),
                        internal_values(CASES["compatible_uf"] / time_name / field_name),
                    ),
                    "internal_numeric_difference_original_compatible": numeric_difference(
                        internal_values(CASES["original_zero"] / time_name / field_name),
                        internal_values(CASES["compatible_uf"] / time_name / field_name),
                    ),
                }
            )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
