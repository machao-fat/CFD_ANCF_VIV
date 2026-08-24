from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ..process_control import ProcessLimiter
from .developed_flow import _run_openfoam, prepare_fixed_case


def _wsl_case(case: Path) -> str:
    drive, rest = str(case.resolve()).replace("\\", "/").split(":", 1)
    return f"/mnt/{drive.lower()}{rest}"


def run_real_openfoam_limiter_smoke(*, root: Path, result_path: Path, max_processes: int = 2) -> dict[str, Any]:
    """Run three independent one-step pimpleFoam children through the limiter."""
    case_root = root / "process_smoke"
    if case_root.exists():
        raise FileExistsError(f"refusing to overwrite process smoke cases: {case_root}")
    case_root.mkdir(parents=True)
    limiter = ProcessLimiter(max_processes, run_id="stage4d-real-openfoam-smoke")
    children = []
    log_streams = []
    records = []
    try:
        for slice_id, U in enumerate((0.8, 1.0, 1.2)):
            case = case_root / f"slice_{slice_id}"
            prepare_fixed_case(case, U, 0.0025, f"stage4d_smoke_slice_{slice_id}")
            check = _run_openfoam(case, f"checkMesh_smoke_{slice_id}", timeout_s=300.0)
            seed = _run_openfoam(case, f"setFields_smoke_{slice_id}", timeout_s=300.0)
            if check["return_code"] != 0 or seed["return_code"] != 0:
                raise RuntimeError(f"smoke preflight failed for slice {slice_id}")
            wcase = _wsl_case(case)
            log = case / "log.pimpleFoam_smoke"
            stream = log.open("w", encoding="utf-8")
            log_streams.append(stream)
            command = ["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", f"source /opt/openfoam10/etc/bashrc; cd '{wcase}'; pimpleFoam"]
            managed = limiter.launch(command, slice_id=slice_id, global_step=0, timeout_s=600.0, stdout=stream, stderr=subprocess.STDOUT)
            children.append((slice_id, managed, log, case))
        for slice_id, managed, log, case in children:
            code = managed.wait(timeout=600.0)
            text = log.read_text(encoding="utf-8", errors="replace")
            records.append({"slice_id": slice_id, "return_code": code, "normal_end": "End" in text, "case": str(case.resolve()), "log": str(log.resolve())})
    finally:
        for stream in log_streams:
            stream.close()
        limiter.assert_no_leaks()
        audit = limiter.shutdown()
    result = {
        "status": "passed" if len(records) == 3 and all(item["return_code"] == 0 and item["normal_end"] for item in records) and audit["interval_peak_active_count"] <= max_processes else "failed",
        "scope": "real_three_openfoam_process_limiter_smoke_without_ANCF_coupling",
        "max_processes": max_processes,
        "peak_active_count": audit["peak_active_count"],
        "interval_peak_active_count": audit["interval_peak_active_count"],
        "permit_leak": audit["permit_leak"],
        "processes": records,
        "intervals": audit["records"],
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result
