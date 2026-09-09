"""Run the one authorized no-Adapter dynamic zero-motion probe.

This is a single-step, test-only case.  It uses the current bridge's
dynamicMeshDict/fvSolution and the same PRECURSOR_STATE_V1 fields, but removes
the preCICE function object and participant.  It refuses to overwrite an
existing runtime and never retries.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORMAL_CASE = ROOT / "runtime" / "formal_three_slice_implicit_0p05s_owned_mesh_history_v1_run_001" / "cases" / "slice_0000"
PRECURSOR = ROOT / "results" / "fixed_cylinder_precursor_initialization_contract_v1_run_002" / "PRECURSOR_STATE_V1"
RUNTIME = ROOT / "runtime" / "cfd_current_fixed_zero_bridge_v1_run_003_no_adapter_dynamic_one_step"
CASE = RUNTIME / "case"
RESULTS = ROOT / "results" / "cfd_current_fixed_zero_bridge_v1_run_003_no_adapter_dynamic_one_step"
PROTOTYPE_ROOT_WSL = "/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1"
ENV_SCRIPT_WSL = "/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/tools/of10_owned_atomic_mesh_history_restore_prototype_v1/prototype_env.sh"
DT = 0.005
START = 0.100
END = 0.105


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wsl(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def control_dict() -> str:
    return """FoamFile { format ascii; class dictionary; object controlDict; }
application pimpleFoam;
startFrom startTime; startTime 0.1; stopAt endTime; endTime 0.105; deltaT 0.005;
writeControl timeStep; writeInterval 1; purgeWrite 0; writeFormat ascii; writePrecision 12; writeCompression off; timeFormat general; timePrecision 12; runTimeModifiable false;
functions { cylinderForces { type forces; libs (\"libforces.so\"); writeControl timeStep; writeInterval 1; log yes; patches (cylinder); rho rhoInf; rhoInf 1000; CofR (0 0 0); } }
"""


def prepare() -> None:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to overwrite existing no-Adapter probe runtime/results")
    if not (PRECURSOR / "manifest.json").is_file():
        raise RuntimeError("PRECURSOR_STATE_V1 manifest missing")
    RUNTIME.mkdir(parents=True)
    shutil.copytree(FORMAL_CASE / "constant", CASE / "constant")
    shutil.copytree(FORMAL_CASE / "system", CASE / "system")
    (CASE / "0.1").mkdir(parents=True)
    expected = json.loads((PRECURSOR / "manifest.json").read_text(encoding="utf-8"))["field_hashes"]
    for field in ("U", "p", "phi"):
        source = PRECURSOR / field
        if sha256(source) != expected[field]:
            raise RuntimeError(f"PRECURSOR_STATE_V1 hash mismatch for {field}")
        shutil.copy2(source, CASE / "0.1" / field)
    for field in ("pointDisplacement", "cellDisplacement"):
        shutil.copy2(FORMAL_CASE / "0.1" / field, CASE / "0.1" / field)
    (CASE / "system" / "preciceDict").unlink(missing_ok=True)
    write(CASE / "system" / "controlDict", control_dict())
    manifest = {
        "schema_version": "cfd-current-fixed-zero-no-adapter-dynamic-probe-v1",
        "status": "prepared",
        "source_formal_case": str(FORMAL_CASE),
        "precursor_manifest": str(PRECURSOR / "manifest.json"),
        "start_time_s": START,
        "end_time_s": END,
        "dt_s": DT,
        "steps": 1,
        "adapter_loaded": False,
        "dynamicMeshDict_sha256": sha256(CASE / "constant" / "dynamicMeshDict"),
        "fvSolution_sha256": sha256(CASE / "system" / "fvSolution"),
        "fvSchemes_sha256": sha256(CASE / "system" / "fvSchemes"),
        "field_sha256": {field: sha256(CASE / "0.1" / field) for field in ("U", "p", "phi")},
    }
    write(RUNTIME / "manifest.json", json.dumps(manifest, indent=2) + "\n")


def launch() -> int:
    script = "\n".join(
        (
            "set -o pipefail",
            f"source '{ENV_SCRIPT_WSL}' '{PROTOTYPE_ROOT_WSL}'",
            f"cd '{wsl(CASE)}'",
            f"pimpleFoam > '{wsl(RUNTIME / 'fluid.stdout')}' 2> '{wsl(RUNTIME / 'fluid.stderr')}'",
        )
    ) + "\n"
    write(RUNTIME / "launch.sh", script)
    done = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(RUNTIME / "launch.sh")],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=300,
    )
    write(RUNTIME / "launch.stdout", done.stdout)
    write(RUNTIME / "launch.stderr", done.stderr)
    return done.returncode


def collect(return_code: int) -> dict:
    target = CASE / "0.105"
    log = RUNTIME / "fluid.stdout"
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    return {
        "schema_version": "cfd-current-fixed-zero-no-adapter-dynamic-probe-v1",
        "status": "PASS_RUNTIME" if return_code == 0 and text.rstrip().endswith("End") else "FAIL_CLOSED",
        "return_code": return_code,
        "adapter_loaded": False,
        "target_time_written": target.is_dir(),
        "target_force_file": str(next(iter((CASE / "postProcessing" / "cylinderForces").glob("*/forces.dat")), "")) if (CASE / "postProcessing" / "cylinderForces").exists() else None,
        "log_ends_with_End": text.rstrip().endswith("End"),
        "runtime": str(RUNTIME),
    }


def main() -> int:
    prepare()
    return_code = launch()
    result = collect(return_code)
    RESULTS.mkdir(parents=True, exist_ok=True)
    write(RESULTS / "probe_result.json", json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 0 if result["status"] == "PASS_RUNTIME" else 1


if __name__ == "__main__":
    raise SystemExit(main())
