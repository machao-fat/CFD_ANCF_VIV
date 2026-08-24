"""Real OpenFOAM overlap evidence for Stage 4D-A-v2."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ..process_control import ProcessLimiter
from .developed_flow import _run_openfoam
from .developed_flow_v2 import prepare_v2_fresh_case


def _wsl_case(case: Path) -> str:
    drive, rest = str(case.resolve()).replace("\\", "/").split(":", 1)
    return f"/mnt/{drive.lower()}{rest}"


def run_real_openfoam_limiter_overlap_v2(*, root: Path, result_path: Path, max_processes: int = 2, end_time_s: float = 0.1) -> dict[str, Any]:
    """Prepare all cases first, then submit three real pimpleFoam children.

    The third submission waits on the actual permit released by one of the
    first two children.  No sleep or synthetic interval is used.
    """

    if max_processes != 2:
        raise ValueError("Stage 4D-A-v2 overlap evidence requires max_processes=2")
    case_root = root / "process_limiter_overlap_v2"
    if case_root.exists():
        raise FileExistsError(f"refusing to overwrite v2 overlap cases: {case_root}")
    case_root.mkdir(parents=True)
    limiter = ProcessLimiter(max_processes, run_id="stage4d-a-v2-real-overlap")
    children: list[tuple[int, Any, Path, Path]] = []
    streams: list[Any] = []
    records: list[dict[str, Any]] = []
    preflight: list[dict[str, Any]] = []
    failure: str | None = None
    try:
        # All preparation and checkMesh/setFields calls finish before any
        # solver child is submitted, so they cannot hide overlap evidence.
        for slice_id, U in enumerate((0.8, 1.0, 1.2)):
            case = case_root / f"slice_{slice_id}"
            provenance = prepare_v2_fresh_case(case, U, run_id=f"stage4d-a-v2-overlap-slice-{slice_id}", end_time_s=end_time_s)
            check = _run_openfoam(case, f"checkMesh_overlap_{slice_id}", timeout_s=300.0)
            seed = _run_openfoam(case, f"setFields_overlap_{slice_id}", timeout_s=300.0)
            if check["return_code"] != 0 or seed["return_code"] != 0:
                raise RuntimeError(f"v2 overlap preflight failed for slice {slice_id}")
            preflight.append({"slice_id": slice_id, "U_mps": U, "case": str(case.resolve()), "provenance": provenance, "checkMesh": check, "setFields": seed})

        for slice_id in range(3):
            case = case_root / f"slice_{slice_id}"
            log = case / "log.pimpleFoam_overlap_v2"
            stream = log.open("w", encoding="utf-8")
            streams.append(stream)
            command = [
                "wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc",
                f"source /opt/openfoam10/etc/bashrc; cd '{_wsl_case(case)}'; pimpleFoam",
            ]
            # The third call blocks here until a real first/second child exits.
            managed = limiter.launch(command, slice_id=slice_id, global_step=0, timeout_s=900.0, stdout=stream, stderr=subprocess.STDOUT)
            children.append((slice_id, managed, log, case))
        for slice_id, managed, log, case in children:
            code = managed.wait(timeout=900.0)
            text = log.read_text(encoding="utf-8", errors="replace")
            records.append({"slice_id": slice_id, "return_code": code, "normal_end": "End" in text, "case": str(case.resolve()), "log": str(log.resolve()), "pid": managed.pid})
    except BaseException as exc:
        failure = repr(exc)
        for _, managed, _, _ in children:
            if managed.poll() is None:
                managed.terminate()
        for _, managed, _, _ in children:
            try:
                managed.wait(timeout=30.0)
            except (TimeoutError, subprocess.TimeoutExpired):
                managed.kill()
                managed.wait(timeout=30.0)
    finally:
        for stream in streams:
            stream.close()
        audit = limiter.shutdown(force=bool(failure))
    result = {
        "status": "passed" if failure is None and len(records) == 3 and all(item["return_code"] == 0 and item["normal_end"] for item in records) and audit["interval_peak_active_count"] == 2 and not audit["permit_leak"] else "failed",
        "scope": "real_three_openfoam_process_limiter_overlap_without_ANCF_coupling",
        "max_processes": max_processes,
        "preflight_completed_before_solver_submission": len(preflight) == 3,
        "preflight": preflight,
        "peak_active_count": audit["peak_active_count"],
        "interval_peak_active_count": audit["interval_peak_active_count"],
        "permit_leak": audit["permit_leak"],
        "processes": records,
        "intervals": audit["records"],
        "failure": failure,
        "sleep_used_to_create_overlap": False,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result

