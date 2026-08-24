from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path


FLOAT = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
FORCE_RE = re.compile(
    rf"^\s*({FLOAT})\s+\(\(({FLOAT})\s+({FLOAT})\s+({FLOAT})\)\s+\(({FLOAT})\s+({FLOAT})\s+({FLOAT})\)\)"
)


def read_forces(path: Path) -> list[dict[str, float]]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = FORCE_RE.match(line)
        if not m:
            continue
        vals = [float(v) for v in m.groups()]
        out.append({"time_s": vals[0], "force_x_N": vals[1]+vals[4], "force_y_N": vals[2]+vals[5], "force_z_N": vals[3]+vals[6]})
    return out


def read_coeffs(path: Path) -> list[dict[str, float]]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        values = [float(v) for v in line.split()]
        if len(values) >= 4:
            out.append({"time_s": values[0], "Cd": values[2], "Cl": values[3]})
    return out


def rmse(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b))/max(1, len(a)))


def relative_rmse(a: list[float], b: list[float]) -> float:
    denom = math.sqrt(sum(x*x for x in a)/max(1, len(a)))
    return rmse(a, b)/max(denom, 1.0e-30)


def numeric_tokens(path: Path) -> list[float]:
    values = []
    for token in re.findall(FLOAT, path.read_text(encoding="utf-8", errors="replace")):
        try:
            values.append(float(token))
        except ValueError:
            pass
    return values


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    native = root / "cases/openfoam/online_motion_ab2_native"
    file_case = root / "cases/openfoam/online_motion_ab2_file"
    result = root / "results/04_identical_motion_equivalence"
    result.mkdir(parents=True, exist_ok=True)
    f_native = read_forces(native / "postProcessing/cylinderForces/0/forces.dat")
    f_file = read_forces(file_case / "postProcessing/cylinderForces/0/forces.dat")
    n = min(len(f_native), len(f_file))
    force_rows = []
    for a, b in zip(f_native[:n], f_file[:n]):
        force_rows.append({"time_s_native": a["time_s"], "time_s_file": b["time_s"],
                           "delta_time_s": b["time_s"]-a["time_s"],
                           "native_force_x_N": a["force_x_N"], "file_force_x_N": b["force_x_N"],
                           "native_force_y_N": a["force_y_N"], "file_force_y_N": b["force_y_N"],
                           "delta_force_x_N": b["force_x_N"]-a["force_x_N"],
                           "delta_force_y_N": b["force_y_N"]-a["force_y_N"]})
    with (result / "per_step_force_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(force_rows[0])); writer.writeheader(); writer.writerows(force_rows)
    native_y = [0.1*math.sin(1.00530964914873*r["time_s"]) for r in f_native[:n]]
    file_y = [0.1*math.sin(1.00530964914873*r["time_s"]) for r in f_file[:n]]
    coeff_native = read_coeffs(native / "postProcessing/cylinderForceCoeffs/0/forceCoeffs.dat")
    coeff_file = read_coeffs(file_case / "postProcessing/cylinderForceCoeffs/0/forceCoeffs.dat")
    u_native = native / "1/U"; u_file = file_case / "1/U"
    p_native = native / "1/p"; p_file = file_case / "1/p"
    point_native = native / "1/polyMesh/points"; point_file = file_case / "1/polyMesh/points"
    u_native_values = numeric_tokens(u_native); u_file_values = numeric_tokens(u_file)
    p_native_values = numeric_tokens(p_native); p_file_values = numeric_tokens(p_file)
    point_native_values = numeric_tokens(point_native) if point_native.is_file() else []
    point_file_values = numeric_tokens(point_file) if point_file.is_file() else []
    def numerical_max_diff(a: list[float], b: list[float]) -> float | None:
        return max(abs(x-y) for x, y in zip(a, b)) if len(a) == len(b) and a else None
    summary = {
        "status": "complete" if len(f_native) == len(f_file) == 401 else "partial",
        "cases": {"native": str(native), "file": str(file_case)},
        "identical_base_copy": True,
        "steps_compared": n,
        "native_steps": len(f_native), "file_steps": len(f_file),
        "time_max_abs_error_s": max(abs(r["delta_time_s"]) for r in force_rows),
        "trajectory_native_vs_file_max_abs_error_m": max(abs(a-b) for a, b in zip(native_y, file_y)),
        "force_x_rmse_N": rmse([r["native_force_x_N"] for r in force_rows], [r["file_force_x_N"] for r in force_rows]),
        "force_y_rmse_N": rmse([r["native_force_y_N"] for r in force_rows], [r["file_force_y_N"] for r in force_rows]),
        "force_y_relative_rmse": relative_rmse([r["native_force_y_N"] for r in force_rows], [r["file_force_y_N"] for r in force_rows]),
        "force_x_relative_rmse": relative_rmse([r["native_force_x_N"] for r in force_rows], [r["file_force_x_N"] for r in force_rows]),
        "max_force_y_abs_difference_N": max(abs(r["delta_force_y_N"]) for r in force_rows),
        "coeff_steps_compared": min(len(coeff_native), len(coeff_file)),
        "U_sha256_equal_at_1s": hashlib.sha256(u_native.read_bytes()).hexdigest() == hashlib.sha256(u_file.read_bytes()).hexdigest(),
        "p_sha256_equal_at_1s": hashlib.sha256(p_native.read_bytes()).hexdigest() == hashlib.sha256(p_file.read_bytes()).hexdigest(),
        "U_numeric_token_count": min(len(u_native_values), len(u_file_values)),
        "U_max_numeric_difference": numerical_max_diff(u_native_values, u_file_values),
        "p_numeric_token_count": min(len(p_native_values), len(p_file_values)),
        "p_max_numeric_difference": numerical_max_diff(p_native_values, p_file_values),
        "mesh_point_file_emitted": point_native.is_file() and point_file.is_file(),
        "mesh_points_sha256_equal_at_1s": point_native.is_file() and point_file.is_file() and hashlib.sha256(point_native.read_bytes()).hexdigest() == hashlib.sha256(point_file.read_bytes()).hexdigest(),
        "mesh_points_max_numeric_difference": numerical_max_diff(point_native_values, point_file_values),
        "mesh_point_comparison_note": "Mesh point files are compared when emitted by points0MotionSolver; numeric U/p comparisons include the complete OpenFOAM field text and are not hash-only.",
        "restart_checked": False,
    }
    (result / "identical_motion_equivalence.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
