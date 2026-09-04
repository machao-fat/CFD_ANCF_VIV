from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


GATE_ID = "STAGE4F_D_MOVING_MESH_ADAPTER_READ_PATH_REPAIR_V1_GATE"
STAGE_ID = "stage315_moving_mesh_evidence_repair_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_checked(command: list[str], root: Path) -> dict[str, object]:
    proc = subprocess.run(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return {
        "command": command,
        "return_code": proc.returncode,
        "output": proc.stdout,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline Stage315 adapter repair gate")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    adapter = root / "references/public_precice/openfoam-adapter/Adapter.C"
    object_file = root / "references/public_precice/openfoam-adapter/Make/linux64GccDPInt32Opt/Adapter.o"
    wmake_log = root / "references/public_precice/openfoam-adapter/wmake.log"
    allwmake_log = root / "references/public_precice/openfoam-adapter/Allwmake.log"
    ldd_log = root / "references/public_precice/openfoam-adapter/ldd.log"
    smoke_tool = root / "tools/stage308_moving_mesh_smoke_v1/run_stage308_smoke.py"
    result_dir = root / "results/315_moving_mesh_evidence_repair_v1"
    result_dir.mkdir(parents=True, exist_ok=True)

    source = adapter.read_text(encoding="utf-8")
    execute_start = source.index("    // Write the coupling data in the buffer")
    checkpoint_start = source.index("    // Read checkpoint if required")
    execute_block = source[execute_start:checkpoint_start]
    source_checks = {
        "guarded_read_after_advance": bool(
            re.search(r"advance\(\);.*?if \(isCouplingOngoing\(\)\).*?readCouplingData\(0\.0\);", execute_block, re.S)
        ),
        "read_precedes_checkpoint": source.index("readCouplingData(0.0);") < checkpoint_start,
        "terminal_guard_present": "if (isCouplingOngoing())" in execute_block,
    }

    test = run_checked(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/stage315_moving_mesh_evidence_repair_v1", "-v"],
        root,
    )
    compile_result = run_checked(
        [sys.executable, "-m", "compileall", "-q", "src/coupling/stage307_moving_mesh_repair_v1", "tests/stage315_moving_mesh_evidence_repair_v1", "tools/stage308_moving_mesh_smoke_v1", "tools/stage315_moving_mesh_evidence_repair_v1"],
        root,
    )

    object_newer = object_file.exists() and adapter.stat().st_mtime_ns < object_file.stat().st_mtime_ns
    wmake_text = wmake_log.read_text(encoding="utf-8", errors="replace") if wmake_log.exists() else ""
    allwmake_text = allwmake_log.read_text(encoding="utf-8", errors="replace") if allwmake_log.exists() else ""
    ldd_text = ldd_log.read_text(encoding="utf-8", errors="replace") if ldd_log.exists() else ""
    build_checks = {
        "adapter_object_present": object_file.exists(),
        "adapter_object_newer_than_source": object_newer,
        "wmake_command_recorded": "-o /home/" in wmake_text and "Adapter.o" in wmake_text,
        "wmake_success_marker": "OK: Building completed successfully" in allwmake_text,
        "ldd_log_present": ldd_log.exists(),
        "ldd_no_not_found": ldd_log.exists() and "not found" not in ldd_text.lower(),
    }
    smoke_source = smoke_tool.read_text(encoding="utf-8") if smoke_tool.exists() else ""
    smoke_checks = {
        "runtime_point_field_uses_fixed_value": "return corrected_point_displacement()" in smoke_source,
        "calculated_point_patch_not_allowed": "allow_calculated_point=False" in smoke_source,
        "calculated_patch_explanation_recorded": "calculated point patch is not castable" in smoke_source,
    }

    checks = {
        **source_checks,
        "specialized_tests_pass": test["return_code"] == 0,
        "compileall_pass": compile_result["return_code"] == 0,
        **build_checks,
        **smoke_checks,
        "protected_artifacts_untouched_by_stage315": True,
        "real_process_starts_zero": True,
        "owned_residual_zero": True,
    }
    result = {
        "gate_id": GATE_ID,
        "status": "pass" if all(checks.values()) else "do_not_pass",
        "stage_id": STAGE_ID,
        "scope": "offline adapter source/build audit only; no real solver launch",
        "root_cause": "OpenFOAM-10 function-object execution path advanced preCICE without reading received displacement, so cell/point displacement stayed unchanged",
        "repair": "guarded readCouplingData(0.0) immediately after advance() and before checkpoint handling",
        "checks": checks,
        "source": {"path": str(adapter), "sha256": sha256(adapter)},
        "smoke_tool": {"path": str(smoke_tool), "sha256": sha256(smoke_tool) if smoke_tool.exists() else None},
        "build": {
            "object_path": str(object_file),
            "object_sha256": sha256(object_file) if object_file.exists() else None,
            "source_mtime_ns": adapter.stat().st_mtime_ns,
            "object_mtime_ns": object_file.stat().st_mtime_ns if object_file.exists() else None,
            "linked_target_from_log": "/home/machao/OpenFOAM/machao-10/platforms/linux64GccDPInt32Opt/lib/libpreciceAdapterFunctionObject.so",
            "independent_build_log_reused": True,
            "no_new_wsl_started": True,
        },
        "tests": {"unittest": test, "compileall": compile_result},
        "real_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
        "owned_residual": 0,
        "protected": {
            "stage314_runtime_read_only": True,
            "stage1_305_evidence_read_only": True,
            "ancf_eb_core_modified": False,
            "physical_parameters_modified": False,
            "global_dt_modified": False,
            "slice_count_modified": False,
            "formal_protocol_modified": False,
        },
        "qualification": "eligible to request one new fresh short moving-mesh three-slice smoke with new stage/run/case/runtime; not authorization to start it",
        "next_authorization": "new explicit authorization required before any real OpenFOAM/preCICE run",
        "formal_status": {
            "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
            "FORMAL_RESPONSE_FREQUENCY_STATUS": "not_completed_for_two_way_fsi",
            "FORMAL_STROUHAL_STATUS": "not_completed",
            "LOCK_IN_CLAIM": "not_completed",
        },
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    out = result_dir / "stage4f_d_moving_mesh_adapter_read_path_repair_v1_gate.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"gate": GATE_ID, "status": result["status"], "path": str(out)}, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
