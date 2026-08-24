from __future__ import annotations

import argparse
import subprocess
import sys
import threading
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--role", choices=("launcher", "child", "grandchild"), default="launcher")
    parser.add_argument("--launcher-exits", action="store_true")
    args = parser.parse_args()
    children: list[subprocess.Popen[str]] = []
    if args.role in ("launcher", "child"):
        child_role = "child" if args.role == "launcher" else "grandchild"
        command = [sys.executable, str(Path(__file__).resolve()), "--token", args.token, "--role", child_role]
        child = subprocess.Popen(command, cwd=str(Path.cwd()))
        children.append(child)
    if args.role == "launcher" and args.launcher_exits:
        return 0
    # The controller owns termination.  Keeping the fake nodes free of signal
    # handlers makes Windows PID-tree cleanup deterministic.
    threading.Event().wait(600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
