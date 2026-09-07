"""Run the frozen noncoupled small-motion fixture with diagnostics disabled/enabled."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = "precice_rollback_fixture_configuration_fix_and_qualification_v1_off_on_004"
RUNTIME, RESULTS = ROOT / "runtime" / RUN, ROOT / "results" / RUN
SOURCE = ROOT / "runtime" / "reproducible_openfoam10_adapter_baseline_recovery_v1" / "small_motion"
DIAG_WSL = "/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_003/lib"
DIAG_UNC = Path(r"\\wsl$\Ubuntu-22.04") / DIAG_WSL.lstrip("/").replace("/", "\\")


def wsl(path: Path) -> str:
    if os.name != "nt":
        return str(path.resolve())
    value = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def prepare(label: str) -> Path:
    case = RUNTIME / label
    case.mkdir(parents=True)
    for item in ("0", "constant", "system"):
        shutil.copytree(SOURCE / item, case / item)
    control = (case / "system" / "controlDict").read_text(encoding="utf-8")
    old = "/home/machao/OpenFOAM/reproducible_adapter_baseline_v1/build_d/lib/libpreciceAdapterFunctionObject.so"
    control = control.replace(old, DIAG_WSL + "/libpreciceAdapterFunctionObject.so")
    if old in control:
        raise RuntimeError("baseline adapter path was not replaced")
    write(case / "system" / "controlDict", control)
    return case


def run(label: str, case: Path) -> dict:
    env = "" if label == "off" else f"export PRECICE_ADAPTER_ROLLBACK_DIAGNOSTICS_PATH='{wsl(RUNTIME / 'on-diagnostics.jsonl')}'\n"
    launch = "\n".join((
        "source /opt/openfoam10/etc/bashrc",
        "set -e -o pipefail",
        f"export LD_LIBRARY_PATH='{DIAG_WSL}':$LD_LIBRARY_PATH",
        env.rstrip(),
        f"cd '{wsl(case)}'",
        "pimpleFoam > run.stdout 2> run.stderr",
    )) + "\n"
    write(case / "launch.sh", launch)
    command = (["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(case / "launch.sh")]
               if os.name == "nt" else ["bash", wsl(case / "launch.sh")])
    result = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=120)
    write(case / "launcher.stdout", result.stdout); write(case / "launcher.stderr", result.stderr)
    targets = [case / "0.005" / name for name in ("U", "p", "phi")]
    targets.extend((case / "0.005" / "polyMesh" / "points", case / "postProcessing" / "cylinderForces" / "0" / "forces.dat"))
    missing = [str(path.relative_to(case)) for path in targets if not path.is_file()]
    return {"return_code": result.returncode, "hashes": {str(path.relative_to(case)): digest(path) for path in targets if path.is_file()}, "missing": missing}


def main() -> int:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to overwrite OFF/ON regression evidence")
    if not (DIAG_UNC / "libpreciceAdapterFunctionObject.so").is_file():
        raise RuntimeError("diagnostic library is unavailable")
    RUNTIME.mkdir(parents=True)
    off, on = prepare("off"), prepare("on")
    off_result, on_result = run("off", off), run("on", on)
    identical = off_result["return_code"] == on_result["return_code"] == 0 and not off_result["missing"] and not on_result["missing"] and off_result["hashes"] == on_result["hashes"]
    output = {"diagnostic_library_sha256": digest(DIAG_UNC / "libpreciceAdapterFunctionObject.so"), "off": off_result, "on": on_result, "non_intrusive_identity": identical, "diagnostic_callbacks_expected": False}
    RESULTS.mkdir(parents=True)
    write(RESULTS / "off_on_regression.json", json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, sort_keys=True))
    return 0 if identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
