"""Bounded 40-step transport replay for Stage 156; never starts CFD software."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.cpp_worker_persistent_ipc_v1.protocol import (  # noqa: E402
    HEADER, MESSAGE_SHUTDOWN, StepRequest, decode_response, encode_control,
    encode_request, validate_response,
)


def main(worker_path: str, output_path: str) -> int:
    worker = Path(worker_path).resolve()
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen([str(worker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, cwd=str(output.parent), bufsize=0)
    started_ns = time.time_ns()
    rows: list[dict[str, object]] = []
    clean = False
    try:
        assert process.stdin is not None and process.stdout is not None
        for index in range(1, 41):
            request = StepRequest(
                sequence=index, global_step=559 + index, case_local_bridge_step=index,
                integer_tick=2_207_500_000 + index * 1_250_000,
                time_s=2.2075 + index * 0.00125, dt_s=0.00125,
                request_id=156000 + index, transaction_id=15600000 + index,
                run_id="cpp_worker_audit_repair_156_001", case_id="cpp_worker_audit_case_156_001",
                q=(1.0, 2.0), qdot=(0.1, 0.2), force=(0.0, 0.0),
            )
            t0 = time.perf_counter_ns()
            process.stdin.write(encode_request(request)); process.stdin.flush()
            header = process.stdout.read(HEADER.size)
            if len(header) != HEADER.size:
                raise RuntimeError(f"worker disconnected at step {request.global_step}")
            body = process.stdout.read(HEADER.unpack(header)[1])
            response = decode_response(header + body)
            validate_response(request, response)
            rows.append({"global_step": response.global_step,
                         "case_local_bridge_step": response.case_local_bridge_step,
                         "time_s": response.time_s,
                         "integer_tick": response.integer_tick,
                         "latency_s": (time.perf_counter_ns() - t0) / 1.0e9})
        process.stdin.write(encode_control(MESSAGE_SHUTDOWN)); process.stdin.flush()
        process.stdin.close(); process.wait(timeout=5)
        clean = process.returncode == 0
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    audit = {
        "stage_id": "stage4f_d_cpp_worker_comprehensive_audit_repair_v2",
        "run_id": "cpp_worker_audit_repair_156_001",
        "case_id": "cpp_worker_audit_case_156_001",
        "status": "pass" if clean and len(rows) == 40 else "do_not_pass",
        "requested_steps": 40, "processed_steps": len(rows),
        "worker_start_count": 1, "worker_return_code": process.returncode,
        "worker_process": {"pid": process.pid, "parent_pid": os.getpid(),
                            "start_time_ns": started_ns, "cwd": str(output.parent),
                            "command_line": [str(worker)], "owned": True,
                            "cleanup_result": "closed" if process.poll() is not None else "residual"},
        "stderr": stderr, "owned_residual": 0 if process.poll() is not None else 1,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "rows": rows,
    }
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))
    return 0 if audit["status"] == "pass" and audit["owned_residual"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
