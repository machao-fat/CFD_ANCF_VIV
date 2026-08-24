from __future__ import annotations

import time
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "src"))
from coupling.user_session_matlab_worker_v1.core import UserSessionWorker

runtime = root / "runtime" / "user_session_matlab_worker_v1"
runner = UserSessionWorker(project_root=root, runtime=runtime)
runner._event("IDLE_WAITING_FOR_CONTRACT", "runner ready; MATLAB worker contracts only; no CFD commands accepted")
try:
    while not (runtime / "stop.request").exists():
        for path in sorted((runtime / "inbox").glob("*.json")):
            if runner.process is None:
                runner.accept(path, launch=True)
        time.sleep(0.2)
finally:
    runner.stop()
