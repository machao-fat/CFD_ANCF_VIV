"""Launch exactly one frozen Ns=2 real runtime attempt."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess


def wsl_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--adapter-lib-wsl", required=True)
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    runtime = Path(args.runtime).resolve()
    repo_wsl = wsl_path(repo)
    runtime_wsl = wsl_path(runtime)
    case_root_wsl = wsl_path(runtime / "case")
    manifest_wsl = wsl_path(runtime / "manifest.json")
    config_wsl = wsl_path(runtime / "precice-config.xml")
    worker_wsl = wsl_path(runtime / "bin" / "cfd_ancf_ancf_kernel_worker_sld1")
    launcher_wsl = wsl_path(repo / "tools" / "real_two_slice_sld1_distributed_coupling_smoke_v1" / "launch_runtime.sh")
    participant_wsl = wsl_path(repo / "tools" / "real_two_slice_sld1_distributed_coupling_smoke_v1")
    command = (
        f"bash '{launcher_wsl}' '{runtime_wsl}' '{case_root_wsl}' '{manifest_wsl}' "
        f"'{config_wsl}' '{worker_wsl}' '{repo_wsl}' '{participant_wsl}' '{args.adapter_lib_wsl}'"
    )
    stdout_path = runtime / "launcher.stdout.log"
    stderr_path = runtime / "launcher.stderr.log"
    result = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", "-lc", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    print({"command": command, "return_code": result.returncode,
           "stdout_log": str(stdout_path), "stderr_log": str(stderr_path)})
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
