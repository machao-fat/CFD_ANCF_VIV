from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.coupling.file_exchange.csv_contract import MOTION_REQUIRED, atomic_write_csv
from src.coupling.online_file_coupling.protocol import FileCouplingError, publish_ready


def read_consumed(path: Path) -> tuple[int, float] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data["step"]), float(data["time_s"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def atomic_json(path: Path, data: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coupling", type=Path, required=True)
    parser.add_argument("--end-step", type=int, required=True)
    parser.add_argument("--start-step", type=int, default=0)
    parser.add_argument("--dt", type=float, default=0.0025)
    parser.add_argument("--amplitude", type=float, default=0.1)
    parser.add_argument("--omega", type=float, default=1.00530964914873)
    parser.add_argument("--timeout-s", type=float, default=90.0)
    parser.add_argument("--poll-s", type=float, default=0.02)
    parser.add_argument("--consumed-directory", type=Path, default=None)
    args = parser.parse_args()
    if args.start_step < 0 or args.end_step < args.start_step or args.dt <= 0 or args.timeout_s <= 0:
        raise SystemExit("start/end-step and dt/timeout are invalid")

    coupling = args.coupling
    coupling.mkdir(parents=True, exist_ok=True)
    motion_csv = coupling / "motion.csv"
    motion_ready = coupling / "motion_ready"
    consumed = coupling / "motion_consumed"
    if args.consumed_directory is not None:
        consumed = args.consumed_directory
        consumed.mkdir(parents=True, exist_ok=True)
    status = coupling / "motion_publisher_status.json"
    if args.consumed_directory is None:
        consumed.unlink(missing_ok=True)
    start = time.monotonic()
    rows = []

    for step in range(args.start_step, args.end_step + 1):
        expected_time = step * args.dt
        if step > args.start_step:
            deadline = time.monotonic() + args.timeout_s
            while True:
                ack_path = consumed
                if args.consumed_directory is not None:
                    ack_path = consumed / f"motion_consumed_{step - 1}.json"
                ack = read_consumed(ack_path)
                if ack is not None:
                    ack_step, ack_time = ack
                    if ack_step == step - 1 and abs(ack_time - (step - 1) * args.dt) <= 1.0e-10:
                        break
                    if ack_step > step - 1:
                        raise SystemExit(f"CFD acknowledgement jumped to step {ack_step}")
                if time.monotonic() > deadline:
                    raise SystemExit(f"timeout waiting for CFD to consume step {step - 1}")
                time.sleep(args.poll_s)

        y = args.amplitude * math.sin(args.omega * expected_time)
        vy = args.amplitude * args.omega * math.cos(args.omega * expected_time)
        ay = -args.amplitude * args.omega**2 * math.sin(args.omega * expected_time)
        row = {
            "schema_version": "0.1.0", "step": step, "coupling_iteration": 0,
            "time_s": expected_time, "slice_id": 0, "s_ref_m": 0.0,
            "x_m": 0.0, "y_m": y, "z_m": 0.0,
            "vx_mps": 0.0, "vy_mps": vy, "vz_mps": 0.0,
            "ax_mps2": 0.0, "ay_mps2": ay, "az_mps2": 0.0,
        }
        atomic_write_csv(motion_csv, MOTION_REQUIRED, [row])
        metadata = publish_ready(motion_csv, motion_ready, kind="motion", expected_s_ref_m=[0.0])
        rows.append({"step": step, "time_s": expected_time, "sha256": metadata["sha256"], "y_m": y, "vy_mps": vy, "ay_mps2": ay})

    deadline = time.monotonic() + args.timeout_s
    while True:
        ack_path = consumed
        if args.consumed_directory is not None:
            ack_path = consumed / f"motion_consumed_{args.end_step}.json"
        ack = read_consumed(ack_path)
        if ack is not None and ack[0] == args.end_step and abs(ack[1] - args.end_step * args.dt) <= 1.0e-10:
            break
        if time.monotonic() > deadline:
            raise SystemExit("timeout waiting for CFD to consume final motion")
        time.sleep(args.poll_s)

    atomic_json(status, {
        "status": "complete", "steps_published": len(rows),
        "first_step": args.start_step, "last_step": args.end_step,
        "dt_s": args.dt, "wall_time_s": time.monotonic() - start,
        "sha256_first": rows[0]["sha256"], "sha256_last": rows[-1]["sha256"],
    })
    atomic_write_csv(coupling / "motion_history.csv", ["step", "time_s", "y_m", "vy_mps", "ay_mps2", "sha256"], rows)


if __name__ == "__main__":
    try:
        main()
    except FileCouplingError as exc:
        raise SystemExit(str(exc)) from exc
