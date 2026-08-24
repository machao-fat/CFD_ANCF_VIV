from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.coupling.file_exchange.csv_contract import LOAD_REQUIRED, atomic_write_csv
from src.coupling.online_file_coupling.protocol import publish_ready

FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def vectors(line: str) -> list[list[float]]:
    result = []
    for group in re.findall(r"\(([^()]*)\)", line):
        values = [float(item) for item in re.findall(FLOAT, group)]
        if len(values) == 3:
            result.append(values)
    return result


def atomic_json(path: Path, data: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forces", type=Path, required=True)
    parser.add_argument("--coupling", type=Path, required=True)
    parser.add_argument("--end-step", type=int, required=True)
    parser.add_argument("--start-step", type=int, default=0)
    parser.add_argument("--dt", type=float, default=0.0025)
    parser.add_argument("--s-ref-m", type=float, required=True)
    parser.add_argument("--timeout-s", type=float, default=90.0)
    args = parser.parse_args()
    if args.start_step < 0 or args.end_step < args.start_step:
        raise SystemExit("start/end-step are invalid")
    load_csv = args.coupling / "slice_loads.csv"
    load_ready = args.coupling / "load_ready"
    status = args.coupling / "load_publisher_status.json"
    seen: set[int] = set()
    records = []
    byte_offset = 0
    remainder = ""
    deadline = time.monotonic() + args.timeout_s + max(0, args.end_step) * 0.5
    while len(seen) < args.end_step - args.start_step + 1:
        if args.forces.is_file():
            try:
                file_size = args.forces.stat().st_size
                if file_size < byte_offset:
                    byte_offset = 0
                    remainder = ""
                with args.forces.open("r", encoding="utf-8", errors="replace") as stream:
                    stream.seek(byte_offset)
                    chunk = stream.read()
                    byte_offset = stream.tell()
                text = remainder + chunk
                lines = text.splitlines(keepends=True)
                if lines and not lines[-1].endswith(("\n", "\r")):
                    remainder = lines.pop()
                else:
                    remainder = ""
            except OSError:
                lines = []
            for raw in lines:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                values = [float(item) for item in re.findall(FLOAT, line)]
                groups = vectors(line)
                if not values or len(groups) < 2:
                    continue
                time_s = values[0]
                step = int(round(time_s / args.dt))
                if step in seen or step < args.start_step or step > args.end_step:
                    continue
                pressure, viscous = groups[0], groups[1]
                total = [pressure[i] + viscous[i] for i in range(3)]
                row = {
                    "schema_version": "0.1.0", "step": step, "coupling_iteration": 0,
                    "time_s": time_s, "slice_id": 0, "s_ref_m": args.s_ref_m,
                    "force_representation": "integrated_N", "unit_span_m": 1.0,
                    "slice_length_m": 1.0, "force_x_N": total[0],
                    "force_y_N": total[1], "force_z_N": total[2],
                    "pressure_force_x_N": pressure[0], "pressure_force_y_N": pressure[1],
                    "pressure_force_z_N": pressure[2], "viscous_force_x_N": viscous[0],
                    "viscous_force_y_N": viscous[1], "viscous_force_z_N": viscous[2],
                    "status": "complete",
                }
                if not all(math.isfinite(float(row[key])) for key in ("time_s", "force_x_N", "force_y_N", "force_z_N")):
                    raise SystemExit(f"non-finite force at step {step}")
                atomic_write_csv(load_csv, LOAD_REQUIRED + ("force_representation", "unit_span_m", "slice_length_m", "pressure_force_x_N", "pressure_force_y_N", "pressure_force_z_N", "viscous_force_x_N", "viscous_force_y_N", "viscous_force_z_N", "status"), [row])
                metadata = publish_ready(load_csv, load_ready, kind="load", expected_s_ref_m=[args.s_ref_m])
                seen.add(step)
                records.append({"step": step, "time_s": time_s, "sha256": metadata["sha256"]})
        if time.monotonic() > deadline:
            raise SystemExit(f"timeout waiting for forces through step {args.end_step}; seen={sorted(seen)}")
        time.sleep(0.05)
    atomic_json(status, {"status": "complete", "steps_published": len(records), "first_step": args.start_step, "last_step": args.end_step})


if __name__ == "__main__":
    main()
