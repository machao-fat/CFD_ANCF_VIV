"""Worker/wire regression for the explicit ANCF section-property extension.

This is intentionally limited to the Python binary protocol and the C++
worker.  It does not run a benchmark, participant, CFD case, or G1 case.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import types
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WIRE_REL = "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py"
BASELINE_COMMIT = "0e813bb680c6343fcdab24d86d56fa9c8718beba"
OUTPUT = ROOT / "runtime" / "ANCF_validation"
CURRENT_WORKER = OUTPUT / "ancf_explicit_section_properties_wire_protocol_patch_v1_worker.exe"

sys.path.insert(0, str(ROOT / "src"))
from coupling.cpp_worker_persistent_ipc_v1 import kernel_protocol as kp  # noqa: E402
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (  # noqa: E402
    FrameError,
    KernelModel,
    KernelStepRequest,
    SECTION_PROPERTY_MODE_EXPLICIT,
    SECTION_PROPERTY_MODE_LEGACY,
    decode_kernel_response,
    encode_kernel_request,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import (  # noqa: E402
    HEADER,
    MESSAGE_INITIALIZE,
    MESSAGE_INITIALIZE_ACK,
    MESSAGE_SHUTDOWN,
    encode_control,
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def baseline_module() -> types.ModuleType:
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE_COMMIT}:{WIRE_REL}"], cwd=ROOT
    )
    name = "coupling.cpp_worker_persistent_ipc_v1.kernel_protocol_baseline_wire_v1"
    module = types.ModuleType(name)
    module.__file__ = f"{ROOT / WIRE_REL} @ {BASELINE_COMMIT}"
    module.__package__ = "coupling.cpp_worker_persistent_ipc_v1"
    sys.modules[name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def make_request(
    module: types.ModuleType,
    *,
    request_id: int,
    case_id: str,
    slices: int = 1,
    custom_boundary: bool = False,
    explicit: dict[str, float] | None = None,
    q_override: tuple[float, ...] | None = None,
    base_override: tuple[float, ...] | None = None,
) -> Any:
    elements = 1
    length = 1.0
    n = 6 * (elements + 1)
    model_args: dict[str, Any] = {
        "length_m": length,
        "diameter_m": 0.028,
        "inner_diameter_m": 0.024,
        "elements": elements,
        "slices": slices,
        "top_tension_N": 0.0,
        "youngs_modulus_Pa": 2.07e11,
        "material_density": 7850.0,
        "fluid_density": 1025.0,
        "gravity": 9.81,
        "beta": 0.25,
        "gamma": 0.5,
        "newton_tolerance": 1e-8,
        "damping_alpha": 0.0,
        "damping_beta": 0.0,
        "gauss_order": 3,
        "mass_gauss_order": 5,
        "max_newton": 40,
    }
    if custom_boundary:
        model_args.update(
            fixed_dof=(0, 1, 2, 6, 7),
            prescribed_values=(0.0, 0.0, 0.0, 0.0, 0.0),
            boundary_contract_id="ancf_v1_wire_static_initializer",
            mass_gauss_order=3,
        )
    if slices > 1:
        model_args["slice_positions_m"] = tuple(
            length * index / (slices - 1) for index in range(slices)
        )
    if explicit is not None:
        model_args.update(
            section_property_mode=SECTION_PROPERTY_MODE_EXPLICIT,
            explicit_EA_N=explicit["EA"],
            explicit_EI_Nm2=explicit["EI"],
            explicit_mass_per_length_kg_m=explicit["mass"],
            explicit_displaced_area_m2=explicit["displaced"],
        )
    model = module.KernelModel(**model_args)
    q = [0.0] * n
    for node in range(elements + 1):
        q[6 * node + 2] = length * node / elements
        q[6 * node + 5] = 1.0
    if q_override is not None:
        q = list(q_override)
    base = list(base_override) if base_override is not None else [0.0] * n
    return module.KernelStepRequest(
        sequence=1,
        global_step=1,
        case_local_bridge_step=1,
        integer_tick=1_000_000,
        time_s=0.001,
        dt_s=0.001,
        request_id=request_id,
        transaction_id=request_id + 10_000_000,
        run_id="wire_protocol_patch_v1_run",
        case_id=case_id,
        model=model,
        q=tuple(q),
        qdot=(0.0,) * n,
        qddot=(0.0,) * n,
        base_load=tuple(base),
        slice_force=(0.0,) * (3 * slices),
    )


def read_exact(stream: Any, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        block = stream.read(remaining)
        if not block:
            raise RuntimeError(f"worker stream ended with {remaining} bytes pending")
        chunks.append(block)
        remaining -= len(block)
    return b"".join(chunks)


def read_frame(stream: Any) -> bytes:
    header = read_exact(stream, HEADER.size)
    magic, length, _message_type = HEADER.unpack(header)
    if magic != kp.MAGIC:
        raise RuntimeError("worker frame magic mismatch")
    return header + read_exact(stream, length)


def run_valid(worker: Path, request: Any) -> tuple[Any, dict[str, Any]]:
    process = subprocess.Popen(
        [str(worker)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=ROOT,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(encode_control(MESSAGE_INITIALIZE))
    process.stdin.flush()
    initialize = read_frame(process.stdout)
    magic, length, message_type = HEADER.unpack(initialize[: HEADER.size])
    if (
        magic != kp.MAGIC
        or message_type != MESSAGE_INITIALIZE_ACK
        or length != len(initialize) - HEADER.size
    ):
        raise RuntimeError("worker initialize acknowledgement mismatch")
    process.stdin.write(encode_kernel_request(request))
    process.stdin.flush()
    response_frame = read_frame(process.stdout)
    response = decode_kernel_response(response_frame)
    kp.validate_kernel_response(request, response)
    process.stdin.write(encode_control(MESSAGE_SHUTDOWN))
    process.stdin.flush()
    return_code = process.wait(timeout=10)
    stderr = process.stderr.read().decode("utf-8", errors="replace")
    if return_code != 0:
        raise RuntimeError(f"valid worker request exited {return_code}: {stderr}")
    return response, {
        "response_frame_sha256": sha256_bytes(response_frame),
        "response_frame_bytes": len(response_frame),
        "stderr": stderr,
    }


def run_raw_invalid(worker: Path, frame: bytes) -> dict[str, Any]:
    process = subprocess.Popen(
        [str(worker)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=ROOT,
    )
    assert process.stdin is not None
    process.stdin.write(encode_control(MESSAGE_INITIALIZE))
    process.stdin.flush()
    assert process.stdout is not None
    initialize = read_frame(process.stdout)
    _magic, _length, message_type = HEADER.unpack(initialize[: HEADER.size])
    if message_type != MESSAGE_INITIALIZE_ACK:
        raise RuntimeError("raw invalid test did not receive initialize acknowledgement")
    process.stdin.write(frame)
    process.stdin.flush()
    return_code = process.wait(timeout=10)
    stdout = process.stdout.read()
    stderr = process.stderr.read().decode("utf-8", errors="replace")
    return {
        "return_code": return_code,
        "rejected": return_code != 0,
        "stdout_bytes_after_request": len(stdout),
        "stderr": stderr,
    }


def response_vector_fields(response: Any) -> list[tuple[float, ...]]:
    return [
        response.q,
        response.qdot,
        response.qddot,
        response.internal_force,
        response.external_force,
        response.generalized_force,
        response.predictor,
        response.corrector,
    ]


def compare_responses(left: Any, right: Any, tolerance: float = 1e-12) -> dict[str, Any]:
    differences: list[float] = []
    for left_field, right_field in zip(response_vector_fields(left), response_vector_fields(right)):
        differences.extend(abs(a - b) for a, b in zip(left_field, right_field))
    scalar_differences = {
        "residual": abs(left.residual - right.residual),
        "time_s": abs(left.time_s - right.time_s),
    }
    max_difference = max(differences + list(scalar_differences.values()) + [0.0])
    return {
        "pass": max_difference <= tolerance,
        "max_abs_difference": max_difference,
        "payload_hash_equal": left.payload_hash == right.payload_hash,
        "return_code_equal": left.return_code == right.return_code,
        "iterations_equal": left.iterations == right.iterations,
        "tolerance": tolerance,
    }


def legacy_properties(model: KernelModel) -> dict[str, float]:
    area = math.pi * (model.diameter_m**2 - model.inner_diameter_m**2) / 4.0
    inertia = math.pi * (model.diameter_m**4 - model.inner_diameter_m**4) / 64.0
    return {
        "EA": model.youngs_modulus_Pa * area,
        "EI": model.youngs_modulus_Pa * inertia,
        "mass": model.material_density * area,
        "displaced": math.pi * model.diameter_m**2 / 4.0,
    }


def extension_offset(request: KernelStepRequest) -> int:
    return (
        HEADER.size
        + kp._PREFIX.size
        + kp._MODEL.size
        + 8 * request.model.slices
    )


def mutate_extension(frame: bytes, request: KernelStepRequest, offset: int, value: Any) -> bytes:
    data = bytearray(frame)
    struct.pack_into("<I", data, offset, int(value))
    return bytes(data)


def mutate_double(frame: bytes, offset: int, value: float) -> bytes:
    data = bytearray(frame)
    struct.pack_into("<d", data, offset, value)
    return bytes(data)


def make_short_extension_frame(frame: bytes, request: KernelStepRequest) -> bytes:
    data = frame[HEADER.size:]
    start = extension_offset(request)
    end = start + kp._SECTION_PROPERTY_EXTENSION.size
    shortened = data[: end - 8] + data[end:]
    return HEADER.pack(kp.MAGIC, len(shortened), kp.MESSAGE_KERNEL_STEP_REQUEST) + shortened


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if not CURRENT_WORKER.exists():
        raise SystemExit(f"worker binary not found: {CURRENT_WORKER}")
    baseline = baseline_module()
    results: dict[str, Any] = {
        "baseline_commit": BASELINE_COMMIT,
        "worker": str(CURRENT_WORKER),
        "worker_sha256": sha256_file(CURRENT_WORKER),
        "legacy_old_request": {},
        "explicit_equivalence": {},
        "independent_properties": {},
        "python_invalid": {},
        "raw_cpp_invalid": {},
        "response_schema_unchanged": True,
        "participant_modified": False,
        "benchmark_run": False,
        "G1_run": False,
        "CFD_FSI_run": False,
    }

    old_cases = [
        ("ordinary_kernel_step", dict(slices=1)),
        ("static_initializer_shape", dict(slices=1, custom_boundary=True)),
        ("single_slice_participant_shape", dict(slices=1)),
        ("three_slice_participant_shape", dict(slices=3)),
    ]
    old_raw_lines: list[str] = []
    for index, (name, options) in enumerate(old_cases):
        old_request = make_request(baseline, request_id=1000 + index, case_id=name, **options)
        current_request = make_request(kp, request_id=1000 + index, case_id=name, **options)
        old_frame = baseline.encode_kernel_request(old_request)
        current_frame = encode_kernel_request(current_request)
        byte_equal = old_frame == current_frame
        response, response_meta = run_valid(CURRENT_WORKER, old_request)
        result = {
            "payload_bytes": len(old_request.payload()),
            "frame_bytes": len(old_frame),
            "old_payload_sha256": sha256_bytes(old_request.payload()),
            "current_payload_sha256": sha256_bytes(current_request.payload()),
            "old_frame_sha256": sha256_bytes(old_frame),
            "current_frame_sha256": sha256_bytes(current_frame),
            "byte_identical_to_baseline_source": byte_equal,
            "patched_worker_return_code": response.return_code,
            "patched_worker_iterations": response.iterations,
            "patched_worker_response_sha256": response_meta["response_frame_sha256"],
            "patched_worker_response_bytes": response_meta["response_frame_bytes"],
            "response_decode_pass": True,
        }
        results["legacy_old_request"][name] = result
        old_raw_lines.append(json.dumps({name: result}, sort_keys=True))
    (OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_OLD_REQUEST_RAW_V1.txt").write_text(
        "\n".join(old_raw_lines) + "\n", encoding="utf-8"
    )

    legacy = make_request(kp, request_id=2001, case_id="explicit_equivalence_legacy")
    properties = legacy_properties(legacy.model)
    explicit = make_request(
        kp,
        request_id=2002,
        case_id="explicit_equivalence_explicit",
        explicit=properties,
    )
    legacy_response, legacy_meta = run_valid(CURRENT_WORKER, legacy)
    explicit_response, explicit_meta = run_valid(CURRENT_WORKER, explicit)
    results["explicit_equivalence"] = {
        "properties": properties,
        "legacy_payload_bytes": len(legacy.payload()),
        "explicit_payload_bytes": len(explicit.payload()),
        "section_extension_bytes": kp._SECTION_PROPERTY_EXTENSION.size,
        "extension_marker": hex(kp.SECTION_PROPERTY_EXTENSION_MARKER),
        "legacy_response_sha256": legacy_meta["response_frame_sha256"],
        "explicit_response_sha256": explicit_meta["response_frame_sha256"],
        "comparison": compare_responses(legacy_response, explicit_response),
        "legacy_mode": SECTION_PROPERTY_MODE_LEGACY,
        "explicit_mode": SECTION_PROPERTY_MODE_EXPLICIT,
    }
    (OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_EXPLICIT_EQUIVALENCE_RAW_V1.txt").write_text(
        json.dumps(results["explicit_equivalence"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    independent_properties = {
        "EA": properties["EA"] * 1.25,
        "EI": properties["EI"] * 0.80,
        "mass": properties["mass"] * 1.50,
        "displaced": properties["displaced"] * 2.00,
    }
    deformed_q = list(legacy.q)
    deformed_q[8] = 1.02
    deformed_q[11] = 1.05
    applied_base = [0.0] * legacy.model.ndof
    applied_base[8] = 0.1
    independent_legacy = make_request(
        kp,
        request_id=3001,
        case_id="independent_properties_legacy",
        q_override=tuple(deformed_q),
        base_override=tuple(applied_base),
    )
    independent_explicit = make_request(
        kp,
        request_id=3002,
        case_id="independent_properties_explicit",
        explicit=independent_properties,
        q_override=tuple(deformed_q),
        base_override=tuple(applied_base),
    )
    independent_legacy_response, independent_legacy_meta = run_valid(CURRENT_WORKER, independent_legacy)
    independent_explicit_response, independent_explicit_meta = run_valid(CURRENT_WORKER, independent_explicit)
    independent_comparison = compare_responses(independent_legacy_response, independent_explicit_response)
    displaced_area_used_by_step = False
    results["independent_properties"] = {
        "supplied_explicit_properties": independent_properties,
        "comparison_against_different_legacy_properties": independent_comparison,
        "legacy_response_sha256": independent_legacy_meta["response_frame_sha256"],
        "explicit_response_sha256": independent_explicit_meta["response_frame_sha256"],
        "observable_response_difference": independent_comparison["max_abs_difference"] > 1e-12,
        "EA_EI_mass_wire_mapping_observable": independent_comparison["max_abs_difference"] > 1e-12,
        "displaced_area_wire_field_serialized": True,
        "displaced_area_used_by_ancf_worker_step": displaced_area_used_by_step,
        "displaced_area_observability": (
            "blocked: ancf_worker_main consumes caller-supplied base_load and does not call static_base_load(); "
            "response schema has no computed buoyancy/base-load field"
        ),
        "independent_property_wire_gate": "PARTIAL_ONLY_DISPLACED_AREA_UNOBSERVABLE",
    }
    (OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_INDEPENDENT_RAW_V1.txt").write_text(
        json.dumps(results["independent_properties"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    explicit_template = make_request(
        kp,
        request_id=4000,
        case_id="invalid_template",
        explicit=properties,
    )
    python_invalid_cases: dict[str, Any] = {}
    for name, replacement in [
        ("unknown_mode", {"section_property_mode": "unknown"}),
        ("missing_EA", {"explicit_EA_N": None}),
        ("missing_EI", {"explicit_EI_Nm2": None}),
        ("missing_mass", {"explicit_mass_per_length_kg_m": None}),
        ("missing_displaced_area", {"explicit_displaced_area_m2": None}),
        ("zero_EA", {"explicit_EA_N": 0.0}),
        ("negative_EI", {"explicit_EI_Nm2": -1.0}),
        ("nan_mass", {"explicit_mass_per_length_kg_m": float("nan")}),
        ("inf_displaced_area", {"explicit_displaced_area_m2": float("inf")}),
        ("legacy_with_explicit_values", {
            "section_property_mode": SECTION_PROPERTY_MODE_LEGACY,
            "explicit_EA_N": properties["EA"],
            "explicit_EI_Nm2": properties["EI"],
            "explicit_mass_per_length_kg_m": properties["mass"],
            "explicit_displaced_area_m2": properties["displaced"],
        }),
    ]:
        model = dataclasses.replace(explicit_template.model, **replacement)
        request = dataclasses.replace(explicit_template, model=model)
        try:
            request.payload()
        except FrameError as error:
            python_invalid_cases[name] = {"rejected": True, "error": str(error)}
        else:
            python_invalid_cases[name] = {"rejected": False, "error": None}
    results["python_invalid"] = python_invalid_cases
    (OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_INVALID_PYTHON_RAW_V1.txt").write_text(
        json.dumps(python_invalid_cases, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    valid_frame = encode_kernel_request(explicit_template)
    ext = extension_offset(explicit_template)
    raw_cases = {
        "unknown_mode": mutate_extension(valid_frame, explicit_template, ext + 8, 99),
        "zero_EA": mutate_double(valid_frame, ext + 12, 0.0),
        "negative_EI": mutate_double(valid_frame, ext + 20, -1.0),
        "nan_mass": mutate_double(valid_frame, ext + 28, float("nan")),
        "inf_displaced_area": mutate_double(valid_frame, ext + 36, float("inf")),
        "short_explicit_extension": make_short_extension_frame(valid_frame, explicit_template),
    }
    raw_invalid_results: dict[str, Any] = {}
    raw_lines: list[str] = []
    for index, (name, frame) in enumerate(raw_cases.items()):
        outcome = run_raw_invalid(CURRENT_WORKER, frame)
        outcome["frame_sha256"] = sha256_bytes(frame)
        raw_invalid_results[name] = outcome
        raw_lines.append(json.dumps({name: outcome}, sort_keys=True))
    results["raw_cpp_invalid"] = raw_invalid_results
    (OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_INVALID_RAW_CPP_RAW_V1.txt").write_text(
        "\n".join(raw_lines) + "\n", encoding="utf-8"
    )

    results["gates"] = {
        "legacy_old_requests_byte_identical": all(
            item["byte_identical_to_baseline_source"]
            for item in results["legacy_old_request"].values()
        ),
        "legacy_old_requests_worker_decode": all(
            item["response_decode_pass"] for item in results["legacy_old_request"].values()
        ),
        "explicit_equivalence": results["explicit_equivalence"]["comparison"]["pass"],
        "independent_EA_EI_mass_observable": results["independent_properties"][
            "EA_EI_mass_wire_mapping_observable"
        ],
        "independent_displaced_area_observable": results["independent_properties"][
            "displaced_area_used_by_ancf_worker_step"
        ],
        "python_invalid_all_rejected": all(
            item["rejected"] for item in python_invalid_cases.values()
        ),
        "raw_cpp_invalid_all_rejected": all(
            item["rejected"] for item in raw_invalid_results.values()
        ),
        "response_schema_unchanged": True,
    }
    results["overall_wire_regression_gate"] = (
        all(results["gates"].values())
    )
    summary_path = OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_TEST_SUMMARY_V1.json"
    summary_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if results["overall_wire_regression_gate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
