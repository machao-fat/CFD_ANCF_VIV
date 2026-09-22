"""V1.1 worker/wire regression for explicit section properties and model loads.

This harness is limited to the Python/C++ worker boundary and the canonical
kernel static_base_load helper.  It does not run a benchmark, participant,
G1, CFD, FSI, or literature case.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import types
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "runtime" / "ANCF_validation"
WIRE_REL = "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py"
BASELINE_COMMIT = "0e813bb680c6343fcdab24d86d56fa9c8718beba"
WORKER = OUTPUT / "ancf_explicit_section_properties_wire_protocol_patch_v1_1_worker.exe"
CANONICAL_PROBE = OUTPUT / "ancf_explicit_section_properties_wire_protocol_patch_v1_1_canonical_base_load.exe"
V1_HARNESS = ROOT / "tools" / "ancf_explicit_section_properties_wire_protocol_v1" / "wire_protocol_regression.py"

sys.path.insert(0, str(ROOT / "src"))
from coupling.cpp_worker_persistent_ipc_v1 import kernel_protocol as kp  # noqa: E402
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (  # noqa: E402
    FrameError,
    KernelModel,
    KernelStepRequest,
    SECTION_PROPERTY_MODE_EXPLICIT,
    SECTION_PROPERTY_MODE_LEGACY,
    BASE_LOAD_SOURCE_CALLER,
    BASE_LOAD_SOURCE_MODEL_STATIC,
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


def load_v1_harness() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("wire_protocol_regression_v1", V1_HARNESS)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load V1 harness")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def baseline_module() -> types.ModuleType:
    source = subprocess.check_output(["git", "show", f"{BASELINE_COMMIT}:{WIRE_REL}"], cwd=ROOT)
    name = "coupling.cpp_worker_persistent_ipc_v1.kernel_protocol_baseline_wire_v1_1"
    module = types.ModuleType(name)
    module.__file__ = f"{ROOT / WIRE_REL} @ {BASELINE_COMMIT}"
    module.__package__ = "coupling.cpp_worker_persistent_ipc_v1"
    sys.modules[name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def make_request(
    *,
    request_id: int,
    case_id: str,
    slices: int = 1,
    custom_boundary: bool = False,
    explicit: dict[str, float] | None = None,
    base_source: str = BASE_LOAD_SOURCE_CALLER,
    q_override: tuple[float, ...] | None = None,
    base_override: tuple[float, ...] | None = None,
) -> KernelStepRequest:
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
        "base_load_source": base_source,
    }
    if custom_boundary:
        model_args.update(
            fixed_dof=(0, 1, 2, 6, 7),
            prescribed_values=(0.0, 0.0, 0.0, 0.0, 0.0),
            boundary_contract_id="ancf_v1_wire_static_initializer",
            mass_gauss_order=3,
        )
    if slices > 1:
        model_args["slice_positions_m"] = tuple(length * index / (slices - 1) for index in range(slices))
    if explicit is not None:
        model_args.update(
            section_property_mode=SECTION_PROPERTY_MODE_EXPLICIT,
            explicit_EA_N=explicit["EA"],
            explicit_EI_Nm2=explicit["EI"],
            explicit_mass_per_length_kg_m=explicit["mass"],
            explicit_displaced_area_m2=explicit["displaced"],
        )
    model = KernelModel(**model_args)
    q = [0.0] * n
    for node in range(elements + 1):
        q[6 * node + 2] = length * node / elements
        q[6 * node + 5] = 1.0
    if q_override is not None:
        q = list(q_override)
    base = list(base_override) if base_override is not None else [0.0] * n
    return KernelStepRequest(
        sequence=1,
        global_step=1,
        case_local_bridge_step=1,
        integer_tick=1_000_000,
        time_s=0.001,
        dt_s=0.001,
        request_id=request_id,
        transaction_id=request_id + 10_000_000,
        # Keep the historical fixture identity byte-for-byte identical for
        # the old-request regression.  V1.1 is a successor test harness, not
        # a new wire identity for legacy payloads.
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


def run_valid(request: KernelStepRequest) -> tuple[Any, dict[str, Any]]:
    process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT)
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    process.stdin.write(encode_control(MESSAGE_INITIALIZE))
    process.stdin.flush()
    initialize = read_frame(process.stdout)
    if HEADER.unpack(initialize[: HEADER.size])[2] != MESSAGE_INITIALIZE_ACK:
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
    return response, {"response_frame_sha256": sha256_bytes(response_frame), "stderr": stderr}


def run_raw(frame: bytes) -> dict[str, Any]:
    process = subprocess.Popen([str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT)
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    process.stdin.write(encode_control(MESSAGE_INITIALIZE))
    process.stdin.flush()
    initialize = read_frame(process.stdout)
    if HEADER.unpack(initialize[: HEADER.size])[2] != MESSAGE_INITIALIZE_ACK:
        raise RuntimeError("raw request did not receive initialize acknowledgement")
    process.stdin.write(frame)
    process.stdin.flush()
    return_code = process.wait(timeout=10)
    stdout = process.stdout.read()
    stderr = process.stderr.read().decode("utf-8", errors="replace")
    return {"return_code": return_code, "rejected": return_code != 0,
            "stdout_bytes_after_request": len(stdout), "stderr": stderr}


def response_vectors(response: Any) -> list[tuple[float, ...]]:
    return [response.q, response.qdot, response.qddot, response.internal_force,
            response.external_force, response.generalized_force, response.predictor,
            response.corrector]


def compare_responses(left: Any, right: Any, tolerance: float = 1e-12) -> dict[str, Any]:
    differences = [abs(a - b) for lv, rv in zip(response_vectors(left), response_vectors(right)) for a, b in zip(lv, rv)]
    differences += [abs(left.residual - right.residual), abs(left.time_s - right.time_s)]
    maximum = max(differences + [0.0])
    return {"pass": maximum <= tolerance, "max_abs_difference": maximum,
            "tolerance": tolerance, "iterations_equal": left.iterations == right.iterations,
            "return_code_equal": left.return_code == right.return_code}


def legacy_properties(model: KernelModel) -> dict[str, float]:
    area = math.pi * (model.diameter_m ** 2 - model.inner_diameter_m ** 2) / 4.0
    inertia = math.pi * (model.diameter_m ** 4 - model.inner_diameter_m ** 4) / 64.0
    return {"EA": model.youngs_modulus_Pa * area, "EI": model.youngs_modulus_Pa * inertia,
            "mass": model.material_density * area, "displaced": math.pi * model.diameter_m ** 2 / 4.0}


def canonical_base_load(properties: dict[str, float] | None = None) -> tuple[float, ...]:
    args = [str(CANONICAL_PROBE), "legacy"]
    if properties is not None:
        args = [str(CANONICAL_PROBE), "explicit", *(f"{properties[key]:.17g}" for key in ("EA", "EI", "mass", "displaced"))]
    completed = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True)
    values = tuple(float(item) for item in completed.stdout.split())
    if len(values) != 12 or not all(math.isfinite(value) for value in values):
        raise RuntimeError("canonical base-load probe returned invalid vector")
    return values


def frame_marker_offset(frame: bytes, marker: int) -> int:
    marker_bytes = struct.pack("<I", marker)
    offset = frame.find(marker_bytes, HEADER.size)
    if offset < 0:
        raise RuntimeError(f"marker {marker:#x} not found")
    return offset


def mutate_u32(frame: bytes, offset: int, value: int) -> bytes:
    data = bytearray(frame)
    struct.pack_into("<I", data, offset, value)
    return bytes(data)


def truncate_extension(frame: bytes, offset: int, size: int) -> bytes:
    data = bytearray(frame)
    del data[offset + size - 4:offset + size]
    return HEADER.pack(kp.MAGIC, len(data) - HEADER.size, kp.MESSAGE_KERNEL_STEP_REQUEST) + data[HEADER.size:]


def assert_gate(name: str, value: bool, evidence: dict[str, Any]) -> None:
    if not value:
        raise RuntimeError(f"{name}: {json.dumps(evidence, sort_keys=True)}")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if not WORKER.exists() or not CANONICAL_PROBE.exists():
        raise SystemExit("V1.1 worker or canonical probe binary is missing")
    v1 = load_v1_harness()
    baseline = baseline_module()
    results: dict[str, Any] = {
        "baseline_commit": BASELINE_COMMIT,
        "worker_sha256": sha256_file(WORKER),
        "canonical_probe_sha256": sha256_file(CANONICAL_PROBE),
        "old_request_compatibility": {},
        "explicit_equivalence": {},
        "modelstatic_legacy_equivalence": {},
        "displaced_area_observability": {},
        "mass_observability": {},
        "no_double_counting": {},
        "python_invalid": {},
        "raw_cpp_invalid": {},
        "response_schema_unchanged": True,
        "participant_modified": False,
        "G1_run": False,
        "C_regression_run": False,
        "F_regression_run": False,
        "CFD_FSI_run": False,
    }
    old_raw: list[str] = []
    old_cases = [("ordinary_kernel_step", dict(slices=1)), ("static_initializer_shape", dict(slices=1, custom_boundary=True)),
                 ("single_slice_participant_shape", dict(slices=1)), ("three_slice_participant_shape", dict(slices=3))]
    for index, (name, options) in enumerate(old_cases):
        old_request = v1.make_request(baseline, request_id=1000 + index, case_id=name, **options)
        current_request = make_request(request_id=1000 + index, case_id=name, **options)
        old_frame = baseline.encode_kernel_request(old_request)
        current_frame = encode_kernel_request(current_request)
        response, meta = run_valid(old_request)
        record = {"byte_identical": old_frame == current_frame,
                  "old_frame_sha256": sha256_bytes(old_frame), "current_frame_sha256": sha256_bytes(current_frame),
                  "response_frame_sha256": meta["response_frame_sha256"], "response_decode_pass": True,
                  "default_section_mode": SECTION_PROPERTY_MODE_LEGACY,
                  "default_base_load_source": BASE_LOAD_SOURCE_CALLER,
                  "iterations": response.iterations}
        results["old_request_compatibility"][name] = record
        old_raw.append(json.dumps({name: record}, sort_keys=True))
    old_gate = all(item["byte_identical"] and item["response_decode_pass"] for item in results["old_request_compatibility"].values())
    assert_gate("OLD_REQUEST_COMPATIBILITY_FAIL", old_gate, results["old_request_compatibility"])
    (OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_OLD_REQUEST_RAW_V1.1.txt").write_text("\n".join(old_raw) + "\n", encoding="utf-8")

    legacy = make_request(request_id=2001, case_id="explicit_equivalence_legacy")
    props = legacy_properties(legacy.model)
    explicit = make_request(request_id=2002, case_id="explicit_equivalence_explicit", explicit=props)
    legacy_response, legacy_meta = run_valid(legacy)
    explicit_response, explicit_meta = run_valid(explicit)
    results["explicit_equivalence"] = {"properties": props, "comparison": compare_responses(legacy_response, explicit_response),
                                        "legacy_response_sha256": legacy_meta["response_frame_sha256"],
                                        "explicit_response_sha256": explicit_meta["response_frame_sha256"],
                                        "section_extension_bytes": kp._SECTION_PROPERTY_EXTENSION.size,
                                        "base_load_source": BASE_LOAD_SOURCE_CALLER}
    assert_gate("V1_EXPLICIT_EQUIVALENCE_FAIL", results["explicit_equivalence"]["comparison"]["pass"], results["explicit_equivalence"])
    (OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_EXPLICIT_EQUIVALENCE_RAW_V1.1.txt").write_text(json.dumps(results["explicit_equivalence"], indent=2, sort_keys=True) + "\n", encoding="utf-8")

    canonical_legacy = canonical_base_load()
    caller_request = make_request(request_id=3001, case_id="modelstatic_legacy_caller", base_override=canonical_legacy)
    static_request = make_request(request_id=3002, case_id="modelstatic_legacy_static", base_source=BASE_LOAD_SOURCE_MODEL_STATIC)
    caller_response, _ = run_valid(caller_request)
    static_response, _ = run_valid(static_request)
    results["modelstatic_legacy_equivalence"] = {"canonical_base_load": canonical_legacy,
                                                   "comparison": compare_responses(caller_response, static_response),
                                                   "modelstatic_caller_field_ignored": True}
    assert_gate("MODELSTATIC_LEGACY_EQUIVALENCE_FAIL", results["modelstatic_legacy_equivalence"]["comparison"]["pass"], results["modelstatic_legacy_equivalence"])
    (OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_MODELSTATIC_LEGACY_EQUIVALENCE_RAW_V1.1.txt").write_text(json.dumps(results["modelstatic_legacy_equivalence"], indent=2, sort_keys=True) + "\n", encoding="utf-8")

    p1 = dict(props)
    p2 = dict(props)
    p2["displaced"] *= 2.0
    d1 = make_request(request_id=4001, case_id="displaced_area_one", explicit=p1, base_source=BASE_LOAD_SOURCE_MODEL_STATIC)
    d2 = make_request(request_id=4002, case_id="displaced_area_two", explicit=p2, base_source=BASE_LOAD_SOURCE_MODEL_STATIC)
    d1_response, _ = run_valid(d1)
    d2_response, _ = run_valid(d2)
    expected_d1 = canonical_base_load(p1)
    expected_d2 = canonical_base_load(p2)
    actual_d1 = d1_response.external_force
    actual_d2 = d2_response.external_force
    expected_delta = tuple(b - a for a, b in zip(expected_d1, expected_d2))
    actual_delta = tuple(b - a for a, b in zip(actual_d1, actual_d2))
    displacement_error = max(abs(a - b) for a, b in zip(actual_delta, expected_delta))
    displacement_nonzero = max(abs(value) for value in actual_delta) > 1e-12
    displacement_z_positive = actual_delta[2] > 0.0 or actual_delta[8] > 0.0
    results["displaced_area_observability"] = {"properties_one": p1, "properties_two": p2,
        "canonical_load_one": expected_d1, "canonical_load_two": expected_d2, "worker_load_one": list(actual_d1),
        "worker_load_two": list(actual_d2), "max_delta_error": displacement_error,
        "finite_nonzero_effect": displacement_nonzero, "expected_global_z_direction": displacement_z_positive,
        "pass": displacement_error <= 1e-12 and displacement_nonzero and displacement_z_positive}
    assert_gate("EXPLICIT_DISPLACED_AREA_OBSERVABILITY_FAIL", results["displaced_area_observability"]["pass"], results["displaced_area_observability"])
    (OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_DISPLACED_AREA_RAW_V1.1.txt").write_text(json.dumps(results["displaced_area_observability"], indent=2, sort_keys=True) + "\n", encoding="utf-8")

    m1 = dict(props)
    m2 = dict(props)
    m2["mass"] *= 2.0
    m1_request = make_request(request_id=5001, case_id="mass_one", explicit=m1, base_source=BASE_LOAD_SOURCE_MODEL_STATIC)
    m2_request = make_request(request_id=5002, case_id="mass_two", explicit=m2, base_source=BASE_LOAD_SOURCE_MODEL_STATIC)
    m1_response, _ = run_valid(m1_request)
    m2_response, _ = run_valid(m2_request)
    expected_m1 = canonical_base_load(m1)
    expected_m2 = canonical_base_load(m2)
    expected_mass_delta = tuple(b - a for a, b in zip(expected_m1, expected_m2))
    actual_mass_delta = tuple(b - a for a, b in zip(m1_response.external_force, m2_response.external_force))
    mass_error = max(abs(a - b) for a, b in zip(actual_mass_delta, expected_mass_delta))
    mass_nonzero = max(abs(value) for value in actual_mass_delta) > 1e-12
    mass_z_negative = actual_mass_delta[2] < 0.0 or actual_mass_delta[8] < 0.0
    results["mass_observability"] = {"properties_one": m1, "properties_two": m2,
        "canonical_load_one": expected_m1, "canonical_load_two": expected_m2,
        "worker_load_one": list(m1_response.external_force), "worker_load_two": list(m2_response.external_force),
        "max_delta_error": mass_error, "finite_nonzero_effect": mass_nonzero,
        "expected_global_z_direction": mass_z_negative, "pass": mass_error <= 1e-12 and mass_nonzero and mass_z_negative}
    assert_gate("EXPLICIT_MASS_OBSERVABILITY_FAIL", results["mass_observability"]["pass"], results["mass_observability"])
    (OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_MASS_RAW_V1.1.txt").write_text(json.dumps(results["mass_observability"], indent=2, sort_keys=True) + "\n", encoding="utf-8")

    distinctive = [0.0] * legacy.model.ndof
    distinctive[2] = 1234.5
    static_zero = make_request(request_id=6001, case_id="no_double_zero", explicit=props, base_source=BASE_LOAD_SOURCE_MODEL_STATIC)
    static_distinctive = make_request(request_id=6002, case_id="no_double_distinctive", explicit=props, base_source=BASE_LOAD_SOURCE_MODEL_STATIC, base_override=tuple(distinctive))
    zero_response, _ = run_valid(static_zero)
    distinctive_response, _ = run_valid(static_distinctive)
    results["no_double_counting"] = {"comparison": compare_responses(zero_response, distinctive_response),
                                       "caller_base_load_ignored": True, "distinctive_base_load": distinctive}
    assert_gate("BASE_LOAD_DOUBLE_COUNTING_FAIL", results["no_double_counting"]["comparison"]["pass"], results["no_double_counting"])
    (OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_DOUBLE_COUNTING_RAW_V1.1.txt").write_text(json.dumps(results["no_double_counting"], indent=2, sort_keys=True) + "\n", encoding="utf-8")

    python_invalid_cases: dict[str, Any] = {}
    template = make_request(request_id=7000, case_id="invalid_template", explicit=props, base_source=BASE_LOAD_SOURCE_MODEL_STATIC)
    for name, replacement in [
        ("unknown_base_load_source", {"base_load_source": "unknown"}),
        ("unknown_section_mode", {"section_property_mode": "unknown"}),
        ("missing_EA", {"explicit_EA_N": None}),
        ("missing_EI", {"explicit_EI_Nm2": None}),
        ("missing_mass", {"explicit_mass_per_length_kg_m": None}),
        ("missing_displaced_area", {"explicit_displaced_area_m2": None}),
        ("zero_EA", {"explicit_EA_N": 0.0}),
        ("negative_EI", {"explicit_EI_Nm2": -1.0}),
        ("nan_mass", {"explicit_mass_per_length_kg_m": float("nan")}),
        ("inf_displaced_area", {"explicit_displaced_area_m2": float("inf")}),
    ]:
        model = dataclasses.replace(template.model, **replacement)
        request = dataclasses.replace(template, model=model)
        try:
            request.payload()
        except FrameError as error:
            python_invalid_cases[name] = {"rejected": True, "error": str(error)}
        else:
            python_invalid_cases[name] = {"rejected": False, "error": None}
    results["python_invalid"] = python_invalid_cases
    assert_gate("PYTHON_INVALID_WIRE_VALIDATION_FAIL", all(item["rejected"] for item in python_invalid_cases.values()), python_invalid_cases)

    valid_frame = encode_kernel_request(template)
    base_ext = frame_marker_offset(valid_frame, kp.BASE_LOAD_SOURCE_EXTENSION_MARKER)
    raw_cases = {
        "unknown_base_load_source": mutate_u32(valid_frame, base_ext + 8, 99),
        "unsupported_base_load_version": mutate_u32(valid_frame, base_ext + 4, 2),
        "truncated_base_load_extension": truncate_extension(valid_frame, base_ext, 12),
    }
    # Retain the V1 raw parser checks in the successor evidence.
    section_ext = frame_marker_offset(valid_frame, kp.SECTION_PROPERTY_EXTENSION_MARKER)
    raw_cases.update({
        "unknown_section_mode": mutate_u32(valid_frame, section_ext + 8, 99),
        "short_section_extension": truncate_extension(valid_frame, section_ext, kp._SECTION_PROPERTY_EXTENSION.size),
    })
    raw_invalid: dict[str, Any] = {}
    invalid_raw_lines: list[str] = []
    for name, frame in raw_cases.items():
        outcome = run_raw(frame)
        outcome["frame_sha256"] = sha256_bytes(frame)
        raw_invalid[name] = outcome
        invalid_raw_lines.append(json.dumps({name: outcome}, sort_keys=True))
    results["raw_cpp_invalid"] = raw_invalid
    assert_gate("RAW_CPP_INVALID_WIRE_VALIDATION_FAIL", all(item["rejected"] for item in raw_invalid.values()), raw_invalid)
    (OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_INVALID_RAW_V1.1.txt").write_text("\n".join(invalid_raw_lines) + "\n", encoding="utf-8")
    (OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_INVALID_PYTHON_RAW_V1.1.txt").write_text(json.dumps(python_invalid_cases, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    expected_response_fields = tuple(field.name for field in dataclasses.fields(baseline.KernelStepResponse))
    actual_response_fields = tuple(field.name for field in dataclasses.fields(type(legacy_response)))
    results["response_schema_unchanged"] = actual_response_fields == expected_response_fields
    assert_gate("RESPONSE_SCHEMA_CHANGE_REQUIRED", results["response_schema_unchanged"], {"actual": actual_response_fields, "expected": expected_response_fields})
    results["gates"] = {
        "old_request_compatibility": old_gate,
        "explicit_equivalence": results["explicit_equivalence"]["comparison"]["pass"],
        "modelstatic_legacy_equivalence": results["modelstatic_legacy_equivalence"]["comparison"]["pass"],
        "displaced_area_observability": results["displaced_area_observability"]["pass"],
        "mass_observability": results["mass_observability"]["pass"],
        "no_double_counting": results["no_double_counting"]["comparison"]["pass"],
        "python_invalid": all(item["rejected"] for item in python_invalid_cases.values()),
        "raw_cpp_invalid": all(item["rejected"] for item in raw_invalid.values()),
        "response_schema_unchanged": results["response_schema_unchanged"],
    }
    results["overall_gate"] = all(results["gates"].values())
    summary = OUTPUT / "ANCF_EXPLICIT_SECTION_PROPERTIES_WIRE_PROTOCOL_PATCH_TEST_SUMMARY_V1.1.json"
    summary.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
