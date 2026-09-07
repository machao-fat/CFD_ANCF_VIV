"""No-CFD boundary and real-worker regression for IPC identity contract v1."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.cpp_worker_persistent_ipc_v1.identity_contract import (  # noqa: E402
    MAX_CASE_UTF8_BYTES, MAX_RUN_UTF8_BYTES, assert_ledger_compatible,
    build_identity, validate_wire_id,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import FrameError, StepRequest, encode_request  # noqa: E402

RUN = os.environ.get("IPC_CONTRACT_REGRESSION_RUN_ID", "formal_implicit_ipc_contract_regression_v1_run_001")
RUNTIME = ROOT / "runtime" / RUN
RESULTS = ROOT / "results" / RUN


def expect_reject(value: object, name: str, limit: int) -> bool:
    try:
        validate_wire_id(value, name, limit)
    except FrameError:
        return True
    return False


def main() -> int:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to overwrite IPC regression evidence")
    RUNTIME.mkdir(parents=True)
    long_human = "formal_implicit_projected_initial_state_guard_closure_v1_run_001"
    identity = build_identity(long_human, "formal_ancf_cfd_implicit_one_window_qualification_v1_case_001", str(RUNTIME))
    assert_ledger_compatible(identity)
    # A plain v1 frame proves encoder treatment at both legal maximum fields.
    max_run = "r" * MAX_RUN_UTF8_BYTES
    max_case = "c" * MAX_CASE_UTF8_BYTES
    request = StepRequest(1, 1, 1, 5_000_000, .005, .005, 1, 1, max_run, max_case,
                          (0.0,), (0.0,), (0.0,))
    frame = encode_request(request)
    boundaries = {
        "legal_short_run_id": validate_wire_id(identity["run_id"], "run_id", MAX_RUN_UTF8_BYTES) == identity["run_id"],
        "legal_max_run_bytes": validate_wire_id(max_run, "run_id", MAX_RUN_UTF8_BYTES) == max_run,
        "legal_max_case_bytes": validate_wire_id(max_case, "case_id", MAX_CASE_UTF8_BYTES) == max_case,
        "frame_encode_round_trip_shape": len(frame) > 0 and frame[:8] == b"CFDANCF1",
        "oversize_run_fail_closed": expect_reject("r" * (MAX_RUN_UTF8_BYTES + 1), "run_id", MAX_RUN_UTF8_BYTES),
        "oversize_case_fail_closed": expect_reject("c" * (MAX_CASE_UTF8_BYTES + 1), "case_id", MAX_CASE_UTF8_BYTES),
        "empty_fail_closed": expect_reject("", "run_id", MAX_RUN_UTF8_BYTES),
        "control_character_fail_closed": expect_reject("bad\nrun", "run_id", MAX_RUN_UTF8_BYTES),
        "utf8_byte_limit_fail_closed": expect_reject("测" * 22, "run_id", MAX_RUN_UTF8_BYTES),
    }
    env = dict(os.environ)
    worker_run = "ipc_wrb_" + hashlib.sha256(RUN.encode("utf-8")).hexdigest()[:16]
    env["PRODUCTION_PARTICIPANT_ROLLBACK_RUN_ID"] = worker_run
    regression_script = ROOT / "tools" / "checkpoint_aware_structure_participant_and_one_window_implicit_qualification_v1" / "production_participant_rollback_regression.py"
    if os.name == "nt":
        root_wsl = "/mnt/" + ROOT.drive[0].lower() + ROOT.as_posix()[2:]
        script_wsl = root_wsl + "/tools/checkpoint_aware_structure_participant_and_one_window_implicit_qualification_v1/production_participant_rollback_regression.py"
        command = (
            "source /opt/openfoam10/etc/bashrc && "
            f"export PYTHONPATH='{root_wsl}/src' && "
            f"export PRODUCTION_PARTICIPANT_ROLLBACK_RUN_ID='{worker_run}' && "
            f"python3 '{script_wsl}'"
        )
        completed = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", "-lc", command], text=True, capture_output=True, encoding="utf-8", errors="replace")
    else:
        completed = subprocess.run([sys.executable, str(regression_script)], cwd=ROOT, text=True, capture_output=True, encoding="utf-8", errors="replace", env=env)
    worker_evidence = ROOT / "runtime" / worker_run / "production_participant_rollback_regression.json"
    worker = json.loads(worker_evidence.read_text(encoding="utf-8")) if worker_evidence.is_file() else {"missing": True}
    passed = all(boundaries.values()) and completed.returncode == 0 and worker.get("PRODUCTION_PARTICIPANT_ROLLBACK") == "PASS"
    result = {
        "IPC_IDENTITY_CONTRACT_V1": "PASS" if passed else "FAIL",
        "identity": identity,
        "boundary_tests": boundaries,
        "real_cpp_worker": {
            "return_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "evidence_path": str(worker_evidence),
            "status": worker.get("PRODUCTION_PARTICIPANT_ROLLBACK"),
            "completed_cycles": worker.get("completed_cycles"),
            "unique_wire_ids": worker.get("unique_wire_ids"),
            "deterministic_trial": worker.get("deterministic_trial"),
        },
    }
    RESULTS.mkdir(parents=True)
    (RUNTIME / "ipc_identity_contract_v1.json").write_text(json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "ipc_contract_regression.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"IPC_IDENTITY_CONTRACT_V1": result["IPC_IDENTITY_CONTRACT_V1"], "worker": result["real_cpp_worker"]["status"]}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
