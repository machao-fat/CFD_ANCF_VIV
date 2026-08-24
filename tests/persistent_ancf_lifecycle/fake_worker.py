from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def response(root: Path, request: dict, *, status: str = "complete", **extra: object) -> None:
    target = root / "responses" / f"response_{request['command_id']}.json"
    payload = {"status": status, "command_id": request["command_id"], "operation_id": request["operation_id"], **extra}
    target.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--mode", choices=("success", "exit", "timeout", "error"), default="success")
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "environment_audit").mkdir(exist_ok=True)
    (root / "environment_audit" / "fake_worker_environment.json").write_text(
        json.dumps({key: os.environ.get(key, "") for key in ("TEMP", "TMP", "TMPDIR", "MATLAB_PREFDIR")}),
        encoding="utf-8",
    )
    child = None
    if args.child:
        child = subprocess.Popen([sys.executable, "-c", "import threading; threading.Event().wait(600)"])
    requests = root / "requests"
    requests.mkdir(exist_ok=True)
    (root / "responses").mkdir(exist_ok=True)
    try:
        while True:
            files = sorted(requests.glob("request_*.json"))
            if not files:
                time.sleep(0.01)
                continue
            path = files[0]
            request = json.loads(path.read_text(encoding="utf-8"))
            path.unlink(missing_ok=True)
            action = request.get("action")
            if action == "initialize":
                if args.mode == "exit":
                    return 17
                if args.mode == "timeout":
                    threading.Event().wait(600)
                if args.mode == "error":
                    response(root, request, status="error", error_code="fake_protocol_error", message="synthetic failure")
                else:
                    response(root, request, q=[0.0], qdot=[0.0], qddot=[0.0], time_s=0.0, global_step=-1)
            elif action == "shutdown":
                response(root, request)
                return 0
            else:
                response(root, request)
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
