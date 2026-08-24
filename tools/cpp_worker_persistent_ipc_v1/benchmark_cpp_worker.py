from __future__ import annotations

import json
import statistics
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.cpp_worker_persistent_ipc_v1.dual_run import DualStepRecord
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelModel, KernelStepRequest, decode_kernel_response, encode_kernel_request, validate_kernel_response
from coupling.cpp_worker_persistent_ipc_v1.protocol import HEADER, MESSAGE_SHUTDOWN, encode_control


def stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))]
    return {"mean_s": statistics.fmean(values), "p50_s": ordered[len(ordered) // 2],
            "p95_s": p95, "min_s": min(values), "max_s": max(values),
            "std_s": statistics.pstdev(values) if len(values) > 1 else 0.0}


def main(fixture_path: str, golden_jsonl: str, output_path: str, worker_path: str) -> int:
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    golden = [DualStepRecord.from_mapping(json.loads(line)) for line in Path(golden_jsonl).read_text(encoding="utf-8").splitlines() if line.strip()]
    model = KernelModel(length_m=fixture["length_m"], diameter_m=fixture["diameter_m"], inner_diameter_m=fixture["inner_diameter_m"],
                        elements=fixture["elements"], slices=fixture["slices"], top_tension_N=fixture["top_tension_N"],
                        youngs_modulus_Pa=fixture["youngs_modulus_Pa"], material_density=fixture["material_density"],
                        fluid_density=fixture["fluid_density"], gravity=fixture["gravity"], beta=fixture["beta"], gamma=fixture["gamma"],
                        newton_tolerance=fixture["newton_tolerance"], damping_alpha=fixture["damping_alpha"], damping_beta=fixture["damping_beta"],
                        gauss_order=fixture["gauss_order"], max_newton=fixture["max_newton"], slice_positions_m=tuple(fixture["slice_positions_m"]))
    start = time.perf_counter()
    process = subprocess.Popen([worker_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    launch_done = time.perf_counter()
    q, qdot, qddot = tuple(fixture["q"]), tuple(fixture["qdot"]), tuple(fixture["qddot"])
    step_times: list[float] = []; encode_times: list[float] = []; ipc_times: list[float] = []
    try:
        assert process.stdin is not None and process.stdout is not None
        for index, item in enumerate(golden, 1):
            request = KernelStepRequest(index, item.global_step, item.case_local_bridge_step, item.integer_tick, item.time_s,
                                        fixture["dt_s"], 910000 + index, 91000000 + index, item.run_id, item.case_id, model,
                                        q, qdot, qddot, tuple(fixture["base_load"]), tuple(fixture["slice_force"]))
            t0 = time.perf_counter(); frame = encode_kernel_request(request); encode_times.append(time.perf_counter() - t0)
            t1 = time.perf_counter(); process.stdin.write(frame); process.stdin.flush();
            header = process.stdout.read(HEADER.size); length = struct.unpack_from("<I", header, 8)[0]
            response = decode_kernel_response(header + process.stdout.read(length)); ipc_times.append(time.perf_counter() - t1)
            validate_kernel_response(request, response); q, qdot, qddot = response.q, response.qdot, response.qddot
            step_times.append(time.perf_counter() - t0)
        process.stdin.write(encode_control(MESSAGE_SHUTDOWN)); process.stdin.flush(); process.stdin.close(); process.wait(timeout=5)
    finally:
        if process.poll() is None: process.kill(); process.wait(timeout=5)
    result = {"status": "pass" if process.returncode == 0 and len(step_times) == len(golden) else "do_not_pass",
              "steps": len(step_times), "worker_start_count": 1, "worker_return_code": process.returncode,
              "owned_residual": 0 if process.poll() is not None else 1,
              "startup_s": launch_done - start, "segment_wall_clock_s": time.perf_counter() - start,
              "step": stats(step_times), "encode": stats(encode_times), "ipc_send_receive_decode": stats(ipc_times),
              "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}}
    Path(output_path).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
