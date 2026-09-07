"""One-step, zero-motion CFD-only reproduction of the immutable tentative solve."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log  # noqa: E402

RUN = os.environ.get("CFD_ONLY_QUALITY_RUN_ID", "formal_implicit_ipc_quality_cfd_only_reproduction_v1_run_001")
RUNTIME = ROOT / "runtime" / RUN
RESULTS = ROOT / "results" / RUN
SOURCE = ROOT / "runtime" / "formal_implicit_projected_initial_state_guard_closure_v1_run_001" / "cases" / "slice_0000"
QUALITY = ROOT / "tools" / "parallel_explicit_fsi_timestep_stability_diagnostic_v1" / "openfoam_quality_contract_v4.json"


def wsl(path: Path) -> str:
    text = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + text[0].lower() + text[2:]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to overwrite CFD-only quality runtime")
    shutil.copytree(SOURCE, RUNTIME / "case", ignore=shutil.ignore_patterns("postProcessing", "precice-profiling", "precice-*.log"))
    case = RUNTIME / "case"
    control = '''FoamFile { format ascii; class dictionary; object controlDict; }
application pimpleFoam;
startFrom startTime; startTime 0.1; stopAt endTime; endTime 0.105; deltaT 0.005;
writeControl timeStep; writeInterval 1; purgeWrite 0; writeFormat ascii; writePrecision 12; writeCompression off; timeFormat general; timePrecision 12; runTimeModifiable false;
functions { cylinderForces { type forces; libs ("libforces.so"); writeControl timeStep; writeInterval 1; log yes; patches (cylinder); rho rhoInf; rhoInf 1000; CofR (0 0 0); } }
'''
    with (case / "system" / "controlDict").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(control)
    command = "source /opt/openfoam10/etc/bashrc && cd '" + wsl(case) + "' && pimpleFoam > cfd_only.stdout 2>&1"
    completed = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", "-lc", command], text=True, capture_output=True, encoding="utf-8", errors="replace", timeout=180)
    (case / "cfd_only.launch.stdout").write_text(completed.stdout, encoding="utf-8")
    (case / "cfd_only.launch.stderr").write_text(completed.stderr, encoding="utf-8")
    evaluator_path = ROOT / "tools" / "parallel_explicit_fsi_timestep_stability_diagnostic_v1" / "quality_v4.py"
    namespace: dict[str, object] = {"__file__": str(evaluator_path)}
    exec(compile(evaluator_path.read_text(encoding="utf-8"), str(evaluator_path), "exec"), namespace)
    try:
        raw = audit_log(case / "cfd_only.stdout", case / "system" / "fvSolution")
        quality = namespace["evaluate_quality_v4"](raw, json.loads(QUALITY.read_text(encoding="utf-8")))
    except Exception as exc:
        raw, quality = None, {"status": "fail", "error": f"{type(exc).__name__}: {exc}"}
    result = {
        "CFD_ONLY_FIRST_STEP_QUALITY_REPRODUCTION": "PASS" if completed.returncode == 0 and quality.get("status") == "pass" else "FAIL",
        "source_immutable_runtime": str(SOURCE),
        "source_input_hashes": {field: sha(SOURCE / "0.1" / field) for field in ("U", "p", "phi", "pointDisplacement", "cellDisplacement")},
        "no_precice": True,
        "no_ANCF": True,
        "motion": "zero total displacement; exact initial trial state before the historical IPC FrameError",
        "return_code": completed.returncode,
        "quality_v4": quality,
        "raw_audit": raw,
    }
    RESULTS.mkdir(parents=True)
    (RESULTS / "cfd_only_quality_reproduction.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["CFD_ONLY_FIRST_STEP_QUALITY_REPRODUCTION"], "quality": quality.get("status")}, ensure_ascii=False))
    return 0 if result["CFD_ONLY_FIRST_STEP_QUALITY_REPRODUCTION"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
