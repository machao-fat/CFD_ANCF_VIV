from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "runtime" / "cfd_current_fixed_zero_bridge_v1_run_002"
OUT = ROOT / "results" / "cfd_current_fixed_zero_bridge_v1_run_002" / "field_comparison.json"
TIMES = [f"{0.1 + i * 0.005:.3f}".rstrip("0").rstrip(".") for i in range(1, 11)]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def post_dimensions(path: Path) -> list[float]:
    text = path.read_text(encoding="utf-8", errors="replace")
    marker = "dimensions"
    start = text.find(marker)
    end = text.find(";", start)
    text = text[end + 1:] if end >= 0 else text[start:]
    return [float(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", text)]


def field_row(fixed: Path, zero: Path, name: str) -> dict:
    a = fixed / name
    b = zero / name
    aa = post_dimensions(a) if a.is_file() else []
    bb = post_dimensions(b) if b.is_file() else []
    n = min(len(aa), len(bb))
    diff = [bb[i] - aa[i] for i in range(n)]
    return {
        "fixed_exists": a.is_file(),
        "zero_exists": b.is_file(),
        "fixed_sha256": sha(a) if a.is_file() else None,
        "zero_sha256": sha(b) if b.is_file() else None,
        "numeric_count_fixed": len(aa),
        "numeric_count_zero": len(bb),
        "max_abs_value_zero": max((abs(x) for x in bb), default=0.0),
        "max_abs_difference": max((abs(x) for x in diff), default=None),
        "l2_difference": math.sqrt(sum(x * x for x in diff)) if diff else None,
    }


def log_metrics(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    rows = []
    for match in re.finditer(r"Time = ([0-9.]+)s(.*?)(?=Time = |End\\s*$)", text, re.S):
        block = match.group(2)
        residuals = [
            float(x)
            for x in re.findall(r"Final residual = ([0-9.eE+-]+)", block)
        ]
        iterations = [
            int(x)
            for x in re.findall(r"No Iterations ([0-9]+)", block)
        ]
        continuity = [
            float(x)
            for x in re.findall(r"global = ([0-9.eE+-]+)", block)
        ]
        co = re.findall(
            r"Courant Number mean: ([0-9.eE+-]+) max: ([0-9.eE+-]+)", block
        )
        rows.append(
            {
                "time_s": float(match.group(1)),
                "max_final_residual": max(residuals, default=None),
                "max_linear_iterations": max(iterations, default=None),
                "max_abs_global_continuity": max((abs(x) for x in continuity), default=None),
                "courant": [
                    {"mean": float(a), "max": float(b)} for a, b in co
                ],
            }
        )
    return rows


def main() -> int:
    fixed = RUN / "fixed_case"
    zero = RUN / "zero_precice_case"
    per_time = []
    for t in TIMES:
        fixed_t = fixed / t
        zero_t = zero / t
        per_time.append(
            {
                "time_s": float(t),
                "pointDisplacement": field_row(fixed_t, zero_t, "pointDisplacement"),
                "cellDisplacement": field_row(fixed_t, zero_t, "cellDisplacement"),
                "meshPhi": field_row(fixed_t, zero_t, "meshPhi"),
                "phi": field_row(fixed_t, zero_t, "phi"),
                "p": field_row(fixed_t, zero_t, "p"),
                "U": field_row(fixed_t, zero_t, "U"),
                "Uf": field_row(fixed_t, zero_t, "Uf"),
                "fixed_points_sha256": sha(fixed / "constant" / "polyMesh" / "points"),
                "zero_points_sha256": sha(zero / "constant" / "polyMesh" / "points"),
            }
        )
    result = {
        "schema_version": "cfd-current-fixed-zero-bridge-analysis-v1",
        "run": str(RUN),
        "target_times_s": [float(x) for x in TIMES],
        "per_time": per_time,
        "fixed_log_metrics": log_metrics(RUN / "fixed.stdout"),
        "zero_log_metrics": log_metrics(RUN / "zero_fluid.stdout"),
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"times": len(per_time), "output": str(OUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
