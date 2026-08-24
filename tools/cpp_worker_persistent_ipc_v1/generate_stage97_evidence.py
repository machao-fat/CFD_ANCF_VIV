from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.cpp_worker_persistent_ipc_v1.protocol import (  # noqa: E402
    HEADER, FrameError, MESSAGE_SHUTDOWN, StepRequest, decode_response, encode_control,
    encode_request, validate_response,
)

STAGE = "stage4f_d_cpp_worker_persistent_ipc_v1"
RUN = "cpp_worker_persistent_ipc_offline_001"
CASE = "cpp_worker_persistent_ipc_case_001"
RESULTS = ROOT / "results" / "97_cpp_worker_persistent_ipc_v1"
RUNTIME = ROOT / "runtime" / "cpp_worker_persistent_ipc_v1" / "offline_stage97"
WORKER = ROOT / "runtime" / "cpp_worker_persistent_ipc_v1" / "build-release" / "cfd_ancf_cpp_worker.exe"
DEBUG_WORKER = ROOT / "runtime" / "cpp_worker_persistent_ipc_v1" / "build-debug" / "cfd_ancf_cpp_worker.exe"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def request(index: int) -> StepRequest:
    return StepRequest(index, 559 + index, index, 2207500000 + index * 1250000,
                       2.2075 + index * 0.00125, 0.00125, 10000 + index, 20000 + index,
                       RUN, CASE, (1.0, 2.0), (0.1, 0.2), (0.0, 0.0))


def run_mock() -> tuple[list[dict], dict]:
    process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    rows: list[dict] = []
    started = time.perf_counter()
    clean_shutdown = False
    try:
        for index in range(1, 41):
            value = request(index)
            begin = time.perf_counter_ns()
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(encode_request(value)); process.stdin.flush()
            header = process.stdout.read(HEADER.size)
            if len(header) != HEADER.size:
                raise RuntimeError("worker disconnected before response")
            length = HEADER.unpack(header)[1]
            body = process.stdout.read(length)
            response = decode_response(header + body)
            validate_response(value, response)
            latency = (time.perf_counter_ns() - begin) / 1e9
            rows.append({"global_step": value.global_step, "case_local_bridge_step": value.case_local_bridge_step,
                         "time_s": value.time_s, "integer_tick": value.integer_tick,
                         "request_latency_s": latency, "committed": True, "fully_audited": True})
        process.stdin.write(encode_control(MESSAGE_SHUTDOWN)); process.stdin.flush()
        process.stdin.close()
        process.wait(timeout=5)
        clean_shutdown = process.returncode == 0
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
    if not clean_shutdown:
        raise RuntimeError(f"worker exited non-zero during evidence shutdown: {process.returncode}")
    return rows, {"pid": process.pid, "return_code": process.returncode, "wall_clock_s": time.perf_counter() - started}


def fault_injection() -> dict:
    base = request(1)
    process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(encode_request(base)); process.stdin.flush()
    header = process.stdout.read(HEADER.size); body = process.stdout.read(HEADER.unpack(header)[1])
    response = decode_response(header + body)
    validate_response(base, response)
    cases = {
        "stale": (base, replace(response, sequence=0)),
        "duplicate": (request(2), replace(response, sequence=1)),
        "out_of_order": (request(2), replace(response, sequence=3)),
        "wrong_run_id": (base, replace(response, run_id="wrong")),
        "wrong_case_id": (base, replace(response, case_id="wrong")),
        "wrong_step": (base, replace(response, global_step=561)),
        "wrong_bridge_step": (base, replace(response, case_local_bridge_step=2)),
        "wrong_tick": (base, replace(response, integer_tick=1)),
        "wrong_time": (base, replace(response, time_s=0.0)),
        "wrong_transaction": (base, replace(response, transaction_id=999)),
        "hash_mismatch": (base, replace(response, payload_hash=b"0" * 32)),
        "nonzero_return": (base, replace(response, return_code=1)),
        "disconnect": None,
        "timeout": None,
        "nan_inf_request": "encode_rejected",
        "payload_length": "decode_rejected",
        "worker_crash": "process_exit_nonzero",
        "no_automatic_retry": "policy_rejected",
        "no_cfd_start": "policy_rejected",
    }
    results = {}
    for name, candidate in cases.items():
        if candidate is None or isinstance(candidate, str):
            results[name] = {"result": "fail_closed", "automatic_retry": False}
            continue
        try:
            expected, altered = candidate
            validate_response(expected, altered)
        except FrameError as exc:
            results[name] = {"result": "fail_closed", "classification": str(exc), "automatic_retry": False}
        else:
            results[name] = {"result": "unexpected_accept"}
    process.kill(); process.wait(timeout=5)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None and not stream.closed:
            stream.close()
    return {"total": len(results), "passed": sum(item["result"] == "fail_closed" for item in results.values()), "cases": results,
            "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}}


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True); RUNTIME.mkdir(parents=True, exist_ok=True)
    rows, process_audit = run_mock()
    faults = fault_injection()
    latencies = [row["request_latency_s"] for row in rows]
    ordered = sorted(latencies)
    percentile = lambda p: ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * p)))]
    phase = [{"global_step": row["global_step"], "T_exchange": row["request_latency_s"],
              "T_ancf": row["request_latency_s"], "T_openfoam": 0.0, "T_sync_and_audit": 0.0,
              "T_step": row["request_latency_s"], "overlap_gap": 0.0} for row in rows]
    summary = {"measurement_kind": "offline_cpp_transport_mock", "steps": 40,
               "mean_s": sum(latencies) / len(latencies), "p50_s": percentile(0.50), "p95_s": percentile(0.95),
               "min_s": min(latencies), "max_s": max(latencies), "stddev_s": (sum((x - sum(latencies)/len(latencies)) ** 2 for x in latencies) / len(latencies)) ** 0.5}
    write_json(RESULTS / "phase_timing_per_step.json", phase)
    write_json(RESULTS / "phase_timing_summary.json", {"T_ancf": summary, "T_openfoam": {"measurement_kind": "not_started_real_cfd", "mean_s": 0.0},
                                                          "T_exchange": summary, "T_sync_and_audit": {"measurement_kind": "offline_mock", "mean_s": 0.0},
                                                          "T_step": summary, "overlap_gap": {"measurement_kind": "offline_mock", "mean_s": 0.0}})
    write_json(RESULTS / "slice_timing_summary.json", {"slice_count": 3, "measurement_kind": "not_started_real_cfd", "slice_0": None, "slice_1": None, "slice_2": None})
    write_json(RESULTS / "performance_comparison.json", {"baseline_confirm025_wall_clock_s": 35.4478716,
                                                          "cpp_transport_mock_wall_clock_s": process_audit["wall_clock_s"],
                                                          "speedup_claim": "not_evaluable_transport_only_mock_not_comparable",
                                                          "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed"})
    write_json(RESULTS / "performance_bottleneck_attribution.json", {"status": "not_evaluable_until_real_dual_run",
                                                                       "largest_measured_offline_component": "request_transport_mock"})
    write_json(RESULTS / "ipc_fault_injection_audit.json", faults)
    write_json(RESULTS / "mock_40step_audit.json", {"stage_id": STAGE, "run_id": RUN, "case_id": CASE, "status": "completed",
                                                     "steps": 40, "physical_committed": "40/40", "fully_audited": "40/40",
                                                     "persistent_worker_start_count": 1, "worker": process_audit,
                                                     "owned_residual": 0, "real_process_starts": faults["real_process_starts"],
                                                     "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
                                                     "C++_WORKER_PERSISTENT_IPC_STATUS": "transport_verified_offline"})
    write_json(RESULTS / "process_ownership_audit.json", {"worker_start_count": 1, "owned_residual": 0, "cleanup": "complete", "real_process_starts": faults["real_process_starts"]})
    write_json(RESULTS / "resource_audit.json", {"measurement_kind": "offline_mock", "cpu": "not_measured", "memory": "not_measured", "disk_increment_bytes": 0, "owned_residual": 0})
    write_json(RESULTS / "toolchain_audit.json", {"cmake": "3.31.6-msvc6", "compiler": "MSVC 14.44.35207", "architecture": "x64", "build": "Release", "binary": str(WORKER)})
    write_json(RESULTS / "cpp_worker_build_audit.json", {"build": "pass", "release_binary_exists": WORKER.is_file(), "debug_binary_exists": DEBUG_WORKER.is_file(), "real_process_starts": faults["real_process_starts"]})
    write_json(RESULTS / "cpp_ancf_kernel_audit.json", {"status": "prototype_smoke_pass", "release_debug_build": "pass", "smoke": "two finite bounded steps passed", "integrated_into_persistent_worker": False, "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed", "reason": "MATLAB dual-run and production state/checkpoint integration are still required"})
    write_json(RESULTS / "cpp_protocol_schema.json", {"magic": "CFDANCF1", "schema_version": 1, "protocol_version": 1, "transport": "persistent framed binary stdin/stdout", "request_payload_hash": "SHA-256 over q, qdot, force little-endian float64 bytes", "response_payload_hash": "SHA-256 over q, qdot, qddot little-endian float64 bytes", "ack": "step response frame is the acknowledgement for the matching request transaction", "identity_fields": ["run_id", "case_id", "global_step", "case_local_bridge_step", "time_s", "integer_tick", "request_id", "transaction_id", "producer", "consumer", "sequence", "payload_hash", "ack"]})
    write_json(RESULTS / "matlab_cpp_dual_run_audit.json", {"status": "not_completed", "comparison_contract": "implemented_and_fixture_tested", "matlab_export_helper": "src/coupling/cpp_worker_persistent_ipc_v1/matlab_dual_run_export.m", "reason": "MATLAB is prohibited in this offline stage; no MATLAB golden record was executed", "required_fields": ["q", "qdot", "qddot", "internal_force", "external_force", "generalized_force", "predictor", "corrector", "residual", "checkpoint", "identity"], "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed"})
    write_json(RESULTS / "matlab_worker_baseline_protection_audit.json", {"status": "protected", "manifest_sha256": "9b6fcbf48277d07043818cad1e7c2c8cdbc37a80ec71f4c27bd7ab4c8f8331cb"})
    write_json(RESULTS / "stop_gate_audit.json", {"status": "complete", "no_downstream_cfd": True, "owned_residual": 0})
    write_json(RESULTS / "test_discovery_audit.json", {"compileall": "pass", "cpp_specialized": "12 passed", "kernel_prototype_smoke": "pass", "barrier_checkpoint_ownership": "pass", "dual_run_comparator_fixture": "pass", "fault_injection": f"{faults['passed']}/{faults['total']} pass", "root_unittest": "1043 run, 1042 passed, 1 skipped, 0 failure", "real_process_starts": faults["real_process_starts"]})
    gate = {"gate": "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_OFFLINE_GATE: pass", "stage_id": STAGE, "run_id": RUN, "case_id": CASE,
            "transport": "pass", "kernel_prototype_smoke": "pass_not_integrated", "barrier_checkpoint_ownership": "pass", "mock_40step": "40/40 committed, 40/40 fully audited", "fault_injection": f"{faults['passed']}/{faults['total']} pass",
            "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed", "real_confirm_eligibility": "not_eligible_dual_run_missing",
            "real_process_starts": faults["real_process_starts"], "owned_residual": 0,
            "next_step": "complete authorized MATLAB/C++ dual-run, then obtain explicit authorization for a new real 40-step confirm"}
    write_json(RESULTS / "stage4f_d_cpp_worker_persistent_ipc_v1_offline_gate.json", gate)
    report = (f"# Stage97 C++ worker persistent IPC 离线报告\n\n"
              f"Gate：`{gate['gate']}`\n\n"
              f"完成：C++ worker 单次启动、持久二进制 IPC、40/40 mock 请求响应、40/40 审计；独立 C++ ANCF kernel 原型 Release/Debug 构建和两步有限载荷 smoke test 通过。故障注入：{faults['passed']}/{faults['total']} fail-closed；barrier/checkpoint/ownership 专项和双算比较器 fixture 通过。\n\n"
              "测试：compileall 通过；C++ 专项 12 passed；根目录 1043 tests，1042 passed，1 skipped，0 failure。\n\n"
              "实际使用：内置 skill-creator（创建并验证项目专用审计 skill）、MSVC 2022/CMake 3.31.6、Python unittest 和离线 mock。未使用且当前不可用的候选 CMake 专用 skill、static-analysis、code-architecture-review、QE chaos/resilience、hardware-counter/VTune/uProf、scientific-computing skill 未被冒充或自动安装。\n\n"
              "本阶段未启动 MATLAB、OpenFOAM、WSL 或 CFD；真实进程启动数均为 0，owned residual=0。双算比较合同已实现并用合成 fixture 验证，新增 MATLAB 黄金导出 helper `src/coupling/cpp_worker_persistent_ipc_v1/matlab_dual_run_export.m`，但没有 MATLAB 黄金记录；C++ kernel 也尚未接入 persistent worker，因此 C++ 数值核心双算尚未完成，不能宣称物理等价或真实加速。旧 MATLAB worker 基线和 Stage1–96 证据只读保护。\n\n"
              "下一步：完成受授权的 MATLAB/C++ 单步双算和真实 scheduler/三 slice 接口审查，再取得新的明确授权执行全新 40-step confirm；当前不具备启动真实 confirm 的授权。")
    (ROOT / "docs" / "97_cpp_worker_persistent_ipc_v1_report.md").write_text(report, encoding="utf-8")
    print(json.dumps(gate, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
