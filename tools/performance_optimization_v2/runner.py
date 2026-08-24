from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.performance_optimization_v2.session_runner import BenchmarkSessionRunner

runtime = ROOT / "runtime" / "performance_optimization_v2"
runner = BenchmarkSessionRunner(project_root=ROOT, runtime=runtime,
                                session_id=int(os.environ.get("CFD_ANCF_SESSION_ID", "1")),
                                username=os.environ.get("USERNAME", ""),
                                sessionname=os.environ.get("SESSIONNAME", ""))
runner.write_status("IDLE_WAITING_FOR_CONTRACT", "Stage95 runner ready; no automatic scope expansion")
try:
    while not (runtime / "status" / "stop.request").exists():
        if runner.process is not None:
            return_code = runner.process.poll()
            if return_code is not None:
                result_path = runtime / "benchmark_result.json"
                completed = False
                if result_path.is_file():
                    try:
                        completed = json.loads(result_path.read_text(encoding="utf-8")).get("status") == "completed" and return_code == 0
                    except (OSError, ValueError, TypeError):
                        completed = False
                runner.write_status("AUTHORIZED_WINDOW_COMPLETE" if completed else "FAILED_TERMINAL",
                                    "benchmark coordinator exited", None if completed else "benchmark_failed")
                runner.failed = True
                runner.process = None
                if runner.stream is not None:
                    runner.stream.close(); runner.stream = None
        for path in sorted((runtime / "inbox").glob("*.json")):
            if runner.current is None and runner.process is None and not runner.failed:
                runner.write_status("PREFLIGHT_RUNNING", "benchmark contract discovered")
                runner.accept(path, launch_matlab=True)
        time.sleep(0.2)
finally:
    runner.stop()
