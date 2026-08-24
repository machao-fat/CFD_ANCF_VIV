from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.cpp_worker_persistent_ipc_v1.protocol import (
    HEADER, MESSAGE_SHUTDOWN, StepRequest, decode_response, encode_control,
    encode_request, validate_response,
)


def main() -> int:
    runtime = ROOT / "runtime" / "cpp_worker_persistent_ipc_v1" / "offline_001"
    results = ROOT / "results" / "97_cpp_worker_persistent_ipc_v1"
    runtime.mkdir(parents=True, exist_ok=True); results.mkdir(parents=True, exist_ok=True)
    exe = ROOT / "runtime" / "cpp_worker_persistent_ipc_v1" / "build-release" / "cfd_ancf_cpp_worker.exe"
    process = subprocess.Popen([str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    started = time.perf_counter(); rows = []
    clean_shutdown = False
    try:
        for index in range(1, 41):
            value = StepRequest(index, 559 + index, index, 2207500000 + index * 1250000,
                                2.2075 + index * 0.00125, 0.00125, 10000 + index, 20000 + index,
                                "cpp_worker_offline_001", "cpp_worker_case_offline_001", (1.0, 2.0), (0.1, 0.2), (0.0, 0.0))
            request_started = time.perf_counter_ns(); process.stdin.write(encode_request(value)); process.stdin.flush()
            header = process.stdout.read(HEADER.size); magic, length, message_type = HEADER.unpack(header); body = process.stdout.read(length)
            response = decode_response(header + body); validate_response(value, response)
            rows.append({"global_step": response.global_step, "case_local_bridge_step": response.case_local_bridge_step,
                         "integer_tick": response.integer_tick, "time_s": response.time_s,
                         "request_latency_s": (time.perf_counter_ns() - request_started) / 1.0e9,
                         "message_type": message_type})
        process.stdin.write(encode_control(MESSAGE_SHUTDOWN)); process.stdin.flush()
        process.stdin.close()
        process.wait(timeout=5)
        clean_shutdown = process.returncode == 0
    finally:
        if process.poll() is None:
            process.terminate(); process.wait(timeout=5)
    if not clean_shutdown:
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        raise RuntimeError(f"worker exited non-zero during offline shutdown: {process.returncode}; stderr={stderr}")
    wall = time.perf_counter() - started
    audit = {"stage_id": "stage4f_d_cpp_worker_persistent_ipc_v1", "run_id": "cpp_worker_offline_001",
             "case_id": "cpp_worker_case_offline_001", "status": "completed", "steps": len(rows),
             "persistent_worker_start_count": 1, "worker_return_code": process.returncode,
             "wall_clock_s": wall, "rows": rows, "owned_residual": 0,
             "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
             "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
             "C++_WORKER_PERSISTENT_IPC_STATUS": "transport_verified_offline"}
    (results / "mock_40step_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "steps": audit["steps"], "wall_clock_s": wall}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
