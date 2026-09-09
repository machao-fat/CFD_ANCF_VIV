"""Read-only comparison for the single strict no-Adapter dynamic probe.

This utility parses already-written OpenFOAM field files and force logs only;
it never opens an OpenFOAM object or starts a solver.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_openfoam_fields import byte_compare, field, parsed_compare, sha256  # noqa: E402


STRICT = ROOT / "runtime" / "cfd_current_fixed_zero_bridge_v1_run_004_no_adapter_dynamic_one_step" / "case"
REAL = ROOT / "runtime" / "cfd_current_fixed_zero_bridge_v1_run_002" / "zero_precice_case"
FIXED = ROOT / "runtime" / "cfd_current_fixed_zero_bridge_v1_run_002" / "fixed_case"
OUT = ROOT / "results" / "cfd_current_fixed_zero_bridge_v1_run_004_no_adapter_dynamic_one_step" / "strict_probe_comparison.json"


def force_rows(path: Path) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    pattern = re.compile(
        r"^\s*([0-9.]+)\s+\(\(([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\)\s+\(([0-9.eE+-]+)\s+([0-9.eE+-]+)\s+([0-9.eE+-]+)\)\)"
    )
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line)
        if match:
            values = [float(value) for value in match.groups()]
            rows.append(
                {
                    "time_s": values[0],
                    "pressure_x_N": values[1],
                    "pressure_y_N": values[2],
                    "viscous_x_N": values[4],
                    "viscous_y_N": values[5],
                    "total_x_N": values[1] + values[4],
                    "total_y_N": values[2] + values[5],
                }
            )
    return rows


def file_hashes(paths: list[Path]) -> dict[str, object]:
    return {str(path.relative_to(ROOT)): sha256(path) if path.is_file() else None for path in paths}


def main() -> int:
    output: dict[str, object] = {
        "schema_version": "cfd-current-fixed-zero-strict-probe-comparison-v1",
        "read_only": True,
        "solver_started_by_comparator": False,
        "strict_runtime": str(STRICT.parent.parent),
        "real_zero_runtime": str(REAL.parent),
        "input_file_hashes": {},
        "fields": {},
        "forces": {},
    }

    input_files = [
        "system/fvSolution",
        "system/fvSchemes",
        "constant/dynamicMeshDict",
        "constant/physicalProperties",
        "constant/momentumTransport",
        "constant/polyMesh/points",
        "0.1/U",
        "0.1/p",
        "0.1/phi",
    ]
    output["input_file_hashes"] = {
        name: {
            "strict": sha256(STRICT / name),
            "real_zero": sha256(REAL / name),
            "fixed": sha256(FIXED / name) if (FIXED / name).is_file() else None,
            "strict_equals_real_zero": (STRICT / name).read_bytes() == (REAL / name).read_bytes(),
            "strict_equals_fixed": (STRICT / name).read_bytes() == (FIXED / name).read_bytes()
            if (FIXED / name).is_file()
            else False,
        }
        for name in input_files
    }

    fields: dict[str, object] = {}
    for time_name in ("0.1", "0.105"):
        for name in ("U", "p", "phi", "pointDisplacement", "cellDisplacement", "meshPhi", "Uf"):
            strict = STRICT / time_name / name
            real = REAL / time_name / name
            paths = [strict, real]
            fields[f"{time_name}/{name}"] = {
                "byte": byte_compare(paths),
                "structured": parsed_compare(paths),
                "strict_record": field(strict),
                "real_zero_record": field(real),
            }
    output["fields"] = fields

    strict_force = STRICT / "postProcessing" / "cylinderForces" / "0.1" / "forces.dat"
    real_force = REAL / "postProcessing" / "cylinderForces" / "0.1" / "forces.dat"
    fixed_force = FIXED / "postProcessing" / "cylinderForces" / "0.1" / "forces.dat"
    output["forces"] = {
        "strict": force_rows(strict_force),
        "real_zero": force_rows(real_force),
        "fixed": force_rows(fixed_force),
        "strict_force_file_sha256": sha256(strict_force),
        "real_zero_force_file_sha256": sha256(real_force),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "solver_started_by_comparator": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
