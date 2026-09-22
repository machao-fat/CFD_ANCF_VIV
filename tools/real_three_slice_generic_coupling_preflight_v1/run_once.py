"""Launch exactly one frozen Ns=3 real preflight through WSL."""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess


def wsl_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True); parser.add_argument("--runtime", required=True)
    parser.add_argument("--adapter-lib-wsl", required=True)
    args = parser.parse_args(); repo = Path(args.repo).resolve(); runtime = Path(args.runtime).resolve()
    repo_wsl = wsl_path(repo); runtime_wsl = wsl_path(runtime)
    launcher = wsl_path(repo / "tools" / "real_three_slice_generic_coupling_preflight_v1" / "launch_runtime.sh")
    participant = wsl_path(repo / "tools" / "real_three_slice_generic_coupling_preflight_v1")
    command = (f"bash '{launcher}' '{runtime_wsl}' '{wsl_path(runtime / 'case')}' "
               f"'{wsl_path(runtime / 'manifest.json')}' '{wsl_path(runtime / 'precice-config.xml')}' "
               f"'{wsl_path(runtime / 'bin' / 'cfd_ancf_ancf_kernel_worker_sld1')}' '{repo_wsl}' "
               f"'{participant}' '{args.adapter_lib_wsl}'")
    result = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", "-lc", command],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    (runtime / "launcher.stdout.log").write_text(result.stdout, encoding="utf-8")
    (runtime / "launcher.stderr.log").write_text(result.stderr, encoding="utf-8")
    print({"command": command, "return_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
