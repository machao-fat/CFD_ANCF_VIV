"""Offline forensic comparison for the first strict MATLAB/C++ mismatch.

This tool uses the read-only step-559 fixture and the existing MATLAB golden
JSONL. It starts only the locally built C++ diagnostic/worker executables; it
never starts MATLAB, OpenFOAM, WSL, or CFD.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import subprocess
from pathlib import Path

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    KernelModel,
    KernelStepRequest,
    decode_kernel_response,
    encode_kernel_request,
    validate_kernel_response,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import HEADER, MESSAGE_SHUTDOWN, encode_control


def _errors(left: list[float], right: list[float]) -> dict[str, object]:
    if len(left) != len(right):
        raise ValueError("dimension mismatch")
    values = [abs(float(a) - float(b)) for a, b in zip(left, right)]
    relative_values = [
        error / max(1.0, abs(float(a)), abs(float(b)))
        for error, a, b in zip(values, left, right)
    ]
    index = max(range(len(values)), key=values.__getitem__)
    relative_index = max(range(len(relative_values)), key=relative_values.__getitem__)
    scale = max(1.0, abs(float(left[index])), abs(float(right[index])))
    return {
        "max_abs": values[index],
        "max_relative": relative_values[relative_index],
        "max_relative_index_zero_based": relative_index,
        "max_relative_left": float(left[relative_index]),
        "max_relative_right": float(right[relative_index]),
        "max_index_zero_based": index,
        "left_at_max": float(left[index]),
        "right_at_max": float(right[index]),
    }


def _write_diagnostic_fixture(path: Path, fixture: dict[str, object], target: dict[str, object]) -> None:
    n = len(fixture["q"])
    values: list[float] = []
    values.extend(float(x) for x in target["q"])
    values.extend(float(x) for x in fixture["qdot"])
    values.extend(float(x) for x in fixture["qddot"])
    values.extend(float(x) for x in fixture["base_load"])
    # The persistent-worker fixture schema permits an omitted mass matrix:
    # the worker then reconstructs its contract mass matrix.  The diagnostic
    # text reader still requires a fixed-size block, so use a zero block only
    # for this diagnostic input (the worker request remains unchanged).
    mass_matrix = fixture.get("mass_matrix")
    if mass_matrix is None:
        mass_matrix = [0.0] * (n * n)
    values.extend(float(x) for x in mass_matrix)
    values.extend(float(x) for x in fixture["slice_force"])
    header = (
        f"{float(fixture['length_m']):.17g} {float(fixture['diameter_m']):.17g} "
        f"{float(fixture['inner_diameter_m']):.17g} {int(fixture['elements'])} "
        f"{int(fixture['slices'])} {float(fixture['youngs_modulus_Pa']):.17g} "
        f"{float(fixture['material_density']):.17g} {float(fixture['fluid_density']):.17g} "
        f"{float(fixture['gravity']):.17g} {float(fixture['beta']):.17g} "
        f"{float(fixture['gamma']):.17g} {float(fixture['newton_tolerance']):.17g} "
        f"{int(fixture['gauss_order'])} {int(fixture['max_newton'])} {float(fixture['dt_s']):.17g}\n"
    )
    positions = " ".join(f"{float(x):.17g}" for x in fixture["slice_positions_m"])
    lines = [header, positions + "\n"]
    for offset, count in ((0, n), (n, n), (2 * n, n), (3 * n, n),
                          (4 * n, n * n), (4 * n + n * n, 3 * int(fixture["slices"]))):
        lines.append(" ".join(f"{values[offset + i]:.17g}" for i in range(count)) + "\n")
    path.write_text("".join(lines), encoding="utf-8")


def _run_worker(worker: Path, fixture: dict[str, object], golden: dict[str, object]) -> dict[str, object]:
    model = KernelModel(
        length_m=float(fixture["length_m"]), diameter_m=float(fixture["diameter_m"]),
        inner_diameter_m=float(fixture["inner_diameter_m"]), elements=int(fixture["elements"]),
        slices=int(fixture["slices"]), top_tension_N=float(fixture["top_tension_N"]),
        youngs_modulus_Pa=float(fixture["youngs_modulus_Pa"]),
        material_density=float(fixture["material_density"]), fluid_density=float(fixture["fluid_density"]),
        gravity=float(fixture["gravity"]), beta=float(fixture["beta"]), gamma=float(fixture["gamma"]),
        newton_tolerance=float(fixture["newton_tolerance"]), damping_alpha=float(fixture["damping_alpha"]),
        damping_beta=float(fixture["damping_beta"]), gauss_order=int(fixture["gauss_order"]),
        max_newton=int(fixture["max_newton"]), slice_positions_m=tuple(float(x) for x in fixture["slice_positions_m"]),
    )
    request = KernelStepRequest(
        sequence=1, global_step=int(golden["global_step"]),
        case_local_bridge_step=int(golden["case_local_bridge_step"]),
        integer_tick=int(golden["integer_tick"]), time_s=float(golden["time_s"]),
        dt_s=float(fixture["dt_s"]), request_id=971001, transaction_id=972001,
        run_id=str(golden["run_id"]), case_id=str(golden["case_id"]), model=model,
        q=tuple(float(x) for x in fixture["q"]), qdot=tuple(float(x) for x in fixture["qdot"]),
        qddot=tuple(float(x) for x in fixture["qddot"]),
        base_load=tuple(float(x) for x in fixture["base_load"]),
        slice_force=tuple(float(x) for x in fixture["slice_force"]),
        mass_matrix=tuple(float(x) for x in fixture.get("mass_matrix", [])),
    )
    process = subprocess.Popen([str(worker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(encode_kernel_request(request))
        process.stdin.flush()
        header = process.stdout.read(HEADER.size)
        if len(header) != HEADER.size:
            raise RuntimeError("worker response header missing")
        length = struct.unpack_from("<I", header, 8)[0]
        frame = header + process.stdout.read(length)
        response = decode_kernel_response(frame)
        validate_kernel_response(request, response)
        if process.poll() is None:
            process.stdin.write(encode_control(MESSAGE_SHUTDOWN))
            process.stdin.flush()
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    fields = ("q", "qdot", "qddot", "internal_force", "external_force",
              "generalized_force", "predictor", "corrector")
    return {
        name: _errors(list(golden[name]), list(getattr(response, name))) for name in fields
    } | {"worker_return_code": process.returncode}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    golden = json.loads(args.golden.read_text(encoding="utf-8").splitlines()[0])
    diagnostic_fixture = args.output.with_name("target_q_diagnostic_fixture.txt")
    diagnostic_output = args.output.with_name("target_q_cpp_diagnostic.txt")
    _write_diagnostic_fixture(diagnostic_fixture, fixture, golden)
    completed = subprocess.run([str(args.diagnostic), str(diagnostic_fixture), str(diagnostic_output)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError(f"diagnostic failed: {completed.returncode}: {completed.stderr}")
    diagnostic_lines = diagnostic_output.read_text(encoding="utf-8").splitlines()
    cpp_internal = None
    for line in diagnostic_lines:
        if line.startswith("internal_before "):
            fields = line.split()
            cpp_internal = [float(value) for value in fields[2:]]
            break
    if cpp_internal is None:
        raise RuntimeError("diagnostic internal_before is missing")
    result = {
        "stage_id": "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage160",
        "run_id": "cpp_worker_comprehensive_audit_repair_160_forensic_001",
        "case_id": "cpp_worker_comprehensive_audit_stage160_forensic_case_001",
        "source_step": int(fixture["source_step"]),
        "target_step": int(golden["global_step"]),
        "target_q_direct_internal_force": _errors(list(golden["internal_force"]), cpp_internal),
        "worker_first_step": _run_worker(args.worker, fixture, golden),
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "interpretation": {
            "target_q_direct_test": "C++ internal force evaluated at MATLAB golden target q",
            "newton_or_transport_error": "not_applicable_to_direct_test",
            "no_threshold_or_physics_change": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
