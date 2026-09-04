from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools/stage308_moving_mesh_smoke_v1") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools/stage308_moving_mesh_smoke_v1"))

from run_stage308_smoke import post_audit  # noqa: E402


def main() -> int:
    runtime = ROOT / "runtime/stage317_moving_mesh_smoke_v1_fresh"
    results = ROOT / "results/317_moving_mesh_smoke_v1"
    cases = [runtime / f"slice_{index:04d}" for index in range(3)]
    started = datetime.fromisoformat((runtime / "logs/start_utc.txt").read_text(encoding="utf-8").strip())
    ended = datetime.fromisoformat((runtime / "logs/end_utc.txt").read_text(encoding="utf-8").strip())
    return_code = post_audit(
        runtime,
        results,
        cases,
        0,
        started,
        ended,
        "stage317_moving_mesh_smoke_v1",
        "s317_fresh_three_slice_moving_mesh_smoke_v1",
        "c317_fresh_three_slice_moving_mesh_smoke_v1",
    )
    print("pass" if return_code == 0 else "do_not_pass")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
