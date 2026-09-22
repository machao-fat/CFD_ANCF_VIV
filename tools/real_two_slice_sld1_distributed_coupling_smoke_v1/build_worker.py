"""Build and handshake the temporary Linux worker for this validation run."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess


def wsl_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    if len(value) < 3 or value[1:3] != ":/":
        raise RuntimeError(f"not a Windows drive path: {value}")
    return "/mnt/" + value[0].lower() + value[2:]


def run_wsl(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", "-lc", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--runtime", required=True)
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    runtime = Path(args.runtime).resolve()
    source = repo / "src" / "coupling" / "cpp_worker_persistent_ipc_v1"
    worker = runtime / "bin" / "cfd_ancf_ancf_kernel_worker_sld1"
    build_log = runtime / "logs" / "worker_build"
    build_log.parent.mkdir(parents=True, exist_ok=True)
    worker.parent.mkdir(parents=True, exist_ok=True)
    src = wsl_path(source)
    out = wsl_path(worker)
    command = (
        "set -e; "
        f"g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror "
        f"'{src}/ancf_kernel.cpp' '{src}/ancf_worker_main.cpp' -I'{src}' -o '{out}'; "
        f"test -x '{out}'; sha256sum '{out}'"
    )
    result = run_wsl(command)
    (build_log.with_suffix(".stdout.log")).write_text(result.stdout, encoding="utf-8")
    (build_log.with_suffix(".stderr.log")).write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0 or not worker.is_file():
        raise SystemExit(f"worker build failed: {result.returncode}\n{result.stderr}")

    handshake_command = (
        f"export PYTHONPATH='{wsl_path(repo / 'src')}'; "
        f"python3 '{wsl_path(repo / 'tools' / 'real_single_slice_legacy_coupling_smoke_v1_1' / 'worker_handshake_probe.py')}' "
        f"--worker '{out}'"
    )
    handshake = run_wsl(handshake_command)
    (build_log.with_suffix(".handshake.stdout.log")).write_text(handshake.stdout, encoding="utf-8")
    (build_log.with_suffix(".handshake.stderr.log")).write_text(handshake.stderr, encoding="utf-8")
    if handshake.returncode != 0:
        raise SystemExit(f"worker handshake failed: {handshake.returncode}\n{handshake.stderr}")
    print({
        "command": command,
        "worker": str(worker),
        "worker_wsl": out,
        "sha256": hashlib.sha256(worker.read_bytes()).hexdigest().upper(),
        "size_bytes": worker.stat().st_size,
        "handshake_return_code": handshake.returncode,
        "handshake_stdout": handshake.stdout,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
