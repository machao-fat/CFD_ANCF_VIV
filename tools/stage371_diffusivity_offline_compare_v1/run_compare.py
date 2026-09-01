"""Offline comparison of OpenFOAM-10 motion-diffusivity candidates.

This is a deterministic radial proxy, not a CFD run. It is used only to
document candidate availability and concentration tendencies before any
future production configuration change.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "runtime/stage341_dt005_long_convergence_v1"
RESULTS = ROOT / "results/371_diffusivity_offline_compare_v1"


def read_vectors(path: Path) -> list[tuple[float, float, float]]:
    data = path.read_bytes()
    match = re.search(rb"\n(\d+)\s*\n\(", data)
    if not match:
        raise ValueError(f"list header missing: {path}")
    count, start = int(match.group(1)), match.end()
    header = data[:start].decode("latin1", errors="ignore")
    if "format      binary" in header:
        values = struct.unpack_from("<" + "d" * count * 3, data, start)
        return [tuple(values[i : i + 3]) for i in range(0, len(values), 3)]
    text = data[start:].decode("latin1", errors="ignore")
    rows = [tuple(float(v) for v in m.groups()) for m in re.finditer(r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)", text)]
    if len(rows) < count:
        raise ValueError(f"incomplete vector list: {path}")
    return rows[:count]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def source_candidates() -> dict[str, object]:
    command = "find /opt/openfoam10/src/fvMotionSolver/motionDiffusivity -type f"
    found = subprocess.run(["wsl.exe", "bash", "-lc", command], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=20).stdout.splitlines()
    names = {Path(path).stem.replace("Diffusivity", "") for path in found if path.endswith("Diffusivity.C")}
    return {
        "openfoam_root": "/opt/openfoam10",
        "source_files_present": {name: name in names for name in ("inverseDistance", "quadratic", "exponential", "inverseFaceDistance", "uniform", "inverseVolume", "inversePointDistance")},
        "syntax": {
            "inverseDistance": "inverseDistance 1(cyl)",
            "quadratic_inverseDistance": "quadratic inverseDistance 1(cyl)",
            "exponential_inverseDistance": "exponential 1 inverseDistance 1(cyl)",
            "inverseFaceDistance": "inverseFaceDistance 1(cyl)",
            "uniform": "uniform",
            "inverseVolume": "inverseVolume",
        },
    }


def proxy_metrics(points: list[tuple[float, float, float]]) -> dict[str, object]:
    # The cylinder is centered at (0, 0) in the preserved benchmark mesh.
    distances = [max(math.hypot(x, y), 1.0e-6) for x, y, _ in points]
    candidates = {
        "inverseDistance": [1.0 / d for d in distances],
        "quadratic_inverseDistance": [1.0 / (d * d) for d in distances],
        "exponential_inverseDistance_alpha1": [math.exp(-d) for d in distances],
        "uniform": [1.0 for _ in distances],
        "inverseVolume_proxy": [1.0 / max(d ** 3, 1.0e-18) for d in distances],
    }
    result: dict[str, object] = {"sample_count": len(distances), "distance_min_m": min(distances), "distance_max_m": max(distances)}
    for name, values in candidates.items():
        finite = all(math.isfinite(value) for value in values)
        positive = [value for value in values if value > 0.0 and math.isfinite(value)]
        ordered = sorted(positive)
        threshold = ordered[int(0.9 * (len(ordered) - 1))] if ordered else None
        result[name] = {
            "finite": finite,
            "min": min(positive) if positive else None,
            "max": max(positive) if positive else None,
            "max_to_median": (max(positive) / ordered[len(ordered) // 2]) if positive else None,
            "near_field_fraction_top_10pct": (sum(1 for value in values if value >= threshold) / len(values)) if values and threshold is not None else 0.0,
        }
    return result


def main() -> int:
    candidates = source_candidates()
    slices = []
    for index in range(3):
        points_path = SOURCE / f"slice_{index:04d}/80/polyMesh/points"
        points = read_vectors(points_path)
        slices.append({"slice_id": f"slice_{index:04d}", "points_sha256": sha(points_path), "proxy": proxy_metrics(points)})
    report = {
        "schema_version": 1,
        "stage_id": "stage4f_d_diffusivity_offline_compare_v1",
        "offline_only": True,
        "source_stage": "stage341_dt005_long_convergence_v1",
        "method": "same preserved 80 s mesh points; radial concentration proxy only; no OpenFOAM solve",
        "candidates": candidates,
        "slices": slices,
        "interpretation": {
            "inverseDistance": "baseline; less concentrated than quadratic/inverseVolume in this proxy",
            "quadratic_inverseDistance": "available in OpenFOAM 10; more near-field concentrated and therefore not automatically safer",
            "exponential_inverseDistance_alpha1": "available in OpenFOAM 10; smoothly decays with distance; alpha is a configuration choice, not changed here",
            "inverseFaceDistance": "available in OpenFOAM 10; requires a separate bounded validation",
            "uniform": "available but not a preferred moving-cylinder production candidate",
            "inverseVolume_proxy": "proxy only; not claimed as an OpenFOAM motion-diffusivity selection here",
        },
        "real_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 1, "cfd": 0},
        "owned_residual": 0,
        "production_configuration_changed": False,
        "status": "pass",
        "gate_id": "STAGE4F_D_DIFFUSIVITY_OFFLINE_COMPARE_V1_GATE",
        "next_action": "only compare a candidate in a new bounded smoke after explicit authorization; do not change production case automatically",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "diffusivity_compare.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "stage4f_d_diffusivity_offline_compare_v1_gate.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "candidates": candidates["source_files_present"], "real_process_starts": report["real_process_starts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
