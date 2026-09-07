"""Read-only completion audit for the already executed OFF/ON regression."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUN = ROOT / "runtime" / "precice_rollback_fixture_configuration_fix_and_qualification_v1_off_on_003"
RESULTS = ROOT / "results" / "precice_rollback_fixture_configuration_fix_and_qualification_v1_off_on_003_reanalysis"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(label: str) -> dict:
    case = SOURCE_RUN / label
    targets = [case / "0.005" / name for name in ("U", "p", "phi")]
    targets.extend((case / "0.005" / "polyMesh" / "points", case / "postProcessing" / "cylinderForces" / "0" / "forces.dat"))
    return {
        "return_code": 0 if "End" in (case / "run.stdout").read_text(encoding="utf-8", errors="replace") else 1,
        "hashes": {str(path.relative_to(case)): digest(path) for path in targets if path.is_file()},
        "missing": [str(path.relative_to(case)) for path in targets if not path.is_file()],
        "time_directory_present": (case / "0.005").is_dir(),
    }


def main() -> int:
    if RESULTS.exists():
        raise RuntimeError("refusing to overwrite reanalysis evidence")
    off, on = inspect("off"), inspect("on")
    passed = off["return_code"] == on["return_code"] == 0 and not off["missing"] and not on["missing"] and off["hashes"] == on["hashes"]
    result = {"source_runtime": str(SOURCE_RUN), "off": off, "on": on, "NON_INTRUSIVE_REGRESSION": "PASS" if passed else "FAIL", "criterion": "exact SHA256 equality for U/p/phi, full mesh points, and forces.dat at t=0.005; both solvers ended normally"}
    RESULTS.mkdir(parents=True)
    (RESULTS / "off_on_regression_reanalysis.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
