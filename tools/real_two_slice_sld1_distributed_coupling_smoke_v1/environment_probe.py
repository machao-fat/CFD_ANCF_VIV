"""Record the bounded WSL/OpenFOAM/preCICE environment for this attempt."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def wsl_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def run(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", "-lc", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--adapter-lib-wsl", required=True)
    parser.add_argument("--worker", required=True)
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    runtime = Path(args.runtime).resolve()
    worker = Path(args.worker).resolve()
    deps = "/mnt/d/CFD/CFD_ANCF_VIV/runtime/284_precice_single_slice_smoke_real_v1/python_deps"
    repo_wsl = wsl_path(repo)
    worker_wsl = wsl_path(worker)
    command = (
        "set +u; source /opt/openfoam10/etc/bashrc; "
        f"export PYTHONPATH='{repo_wsl}/src:{deps}'; "
        "printf 'OPENFOAM_VERSION='; foamVersion 2>&1 || true; "
        "printf 'PIMPLEFOAM='; command -v pimpleFoam; "
        "printf 'CHECKMESH='; command -v checkMesh; "
        "printf 'PYTHON='; python3 --version 2>&1; "
        "set -u; "
        "python3 -c 'import precice; print(\"PRECICE_MODULE=\" + str(precice.__file__)); print(\"PRECICE_VERSION=\" + str(getattr(precice, \"__version__\", \"unknown\")))'; "
        f"printf 'WORKER='; test -x '{worker_wsl}' && echo present; "
        f"printf 'ADAPTER='; test -f '{args.adapter_lib_wsl}' && echo present; "
        f"printf 'ADAPTER_SHA256='; sha256sum '{args.adapter_lib_wsl}' | awk '{{print $1}}'"
    )
    result = run(command)
    env = {
        "command": command,
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "openfoam_bashrc": "/opt/openfoam10/etc/bashrc",
        "openfoam_expected_version": "OpenFOAM-10 (10-c4cf895ad8fa)",
        "python_dependencies": deps,
        "adapter_library_wsl": args.adapter_lib_wsl,
        "worker": str(worker),
        "worker_sha256": hashlib.sha256(worker.read_bytes()).hexdigest().upper(),
    }
    out = runtime / "environment_probe.json"
    out.write_text(json.dumps(env, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(env, ensure_ascii=True))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
