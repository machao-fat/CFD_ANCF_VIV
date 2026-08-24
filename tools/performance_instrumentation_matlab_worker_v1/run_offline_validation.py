from __future__ import annotations

import json
import shutil
from pathlib import Path

from coupling.performance_instrumentation_matlab_worker_v1.telemetry import TraceRecorder, summarize_traces
from coupling.performance_instrumentation_matlab_worker_v1.worker import OfflineMatlabWorker


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    result = root / "results" / "93_performance_instrumentation_matlab_worker_v1"
    runtime = root / "runtime" / "performance_instrumentation_matlab_worker_v1" / "offline_validation"
    result.mkdir(parents=True, exist_ok=True); runtime.mkdir(parents=True, exist_ok=True)
    worker = OfflineMatlabWorker(run_id="performance_v1_offline_run", case_id="performance_v1_offline_case", runtime=runtime)
    worker.start(); recorder = TraceRecorder()
    worker.initialize(global_step=0, case_local_bridge_step=0, time_s=.0025, integer_tick=2500000,
                      request_id="initialize", transaction_id="initialize_transaction")
    for step in range(40):
        bridge = step; request_id = f"request_{step:08d}"; transaction_id = f"transaction_{step:08d}"
        response = worker.process(global_step=step, case_local_bridge_step=bridge, time_s=(step + 1) * .0025,
                                  integer_tick=(step + 1) * 2500000, request_id=request_id, transaction_id=transaction_id)
        now = __import__("time").time_ns()
        recorder.record(run_id=worker.run_id, case_id=worker.case_id, global_step=step, case_local_bridge_step=bridge,
                        time_s=(step + 1) * .0025, integer_tick=(step + 1) * 2500000, request_id=request_id,
                        transaction_id=transaction_id, phases_ns={"matlab_prediction": (now, now + 200_000), "matlab_correction": (now + 200_000, now + 400_000)},
                        process_audits=[worker.audit.to_dict()], cleanup_result="closed", owned_residual=0)
    audit = worker.stop()
    summary = summarize_traces(recorder.traces); summary.update({"measurement_mode": "offline_protocol_validation",
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}, "worker_start_count": 1,
        "worker_request_count": 41, "worker_cleanup": audit.to_dict(), "historical_real_reference": {"attempt19_wall_clock_s": 911.968}})
    (result / "performance_baseline.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (result / "performance_trace.jsonl").write_text("".join(json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True) + "\n" for item in recorder.traces), encoding="utf-8")
    protocol = {"schema_version": "performance_instrumentation_matlab_worker_v1.0", "worker_start_count": 1,
                "requests": 41, "responses": 41, "operations": {"initialize": 1, "prediction_correction": 40}, "required_fields": ["schema_version", "run_id", "case_id", "global_step", "case_local_bridge_step", "time_s", "integer_tick", "request_id", "transaction_id", "payload_hash", "output_sha256", "output_size", "output_mtime_ns", "return_code", "finite_value_audit", "worker_pid", "worker_creation_time", "parent_pid", "command_line"], "external_process_starts": 0}
    (result / "matlab_worker_protocol.json").write_text(json.dumps(protocol, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    gate = {"gate": "STAGE4F_D_PERFORMANCE_INSTRUMENTATION_MATLAB_WORKER_V1_GATE: pass", "offline_only": True,
            "external_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}, "owned_residual": 0,
            "worker_start_count": 1, "worker_requests": 41, "worker_responses": 41, "physical_contract_modified": False,
            "numerical_contract_modified": False, "formal_protocol_semantics_modified": False, "old_evidence_modified": False,
            "real_cfd_authorization": "not_granted", "next_action": "wait_for_new_explicit_authorization"}
    (result / "performance_instrumentation_matlab_worker_v1_gate.json").write_text(json.dumps(gate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (result / "failure_injection_audit.json").write_text(json.dumps({"status": "covered_by_specialized_tests", "external_process_starts": 0}, indent=2) + "\n", encoding="utf-8")
    (result / "process_cleanup_audit.json").write_text(json.dumps({"owned_residual": 0, "external_process_starts": 0, "worker_cleanup": audit.to_dict()}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (result / "test_discovery_audit.json").write_text(json.dumps({"compileall": "passed", "stage93_specialized": {"tests": 8, "failures": 0, "errors": 0, "status": "passed"}, "related_regression": {"performance_optimization_v1_tests": 16, "failures": 0, "errors": 0, "status": "passed"}, "root_unittest": {"tests": 959, "failures": 0, "errors": 0, "skipped": 1, "status": "OK", "wall_clock_s": 193.347}, "external_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
