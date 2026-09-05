"""Offline Python/C++ generalized-force replay; it never starts CFD or preCICE."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.multi_slice_mapping.mapping import (  # noqa: E402
    SliceDefinition, SliceManifest, build_H_for_manifest,
    map_integrated_slice_forces,
)
from coupling.three_slice_force_contract_smoke_v1.contract import bounded_midpoint_voronoi  # noqa: E402

TASK = "generalized_force_mismatch_root_cause_audit_v1"
FAILED_RUNTIME = ROOT / "runtime" / "moving_mesh_patch_consistency_1s_retry_v1_run_001"
CONTRACT = FAILED_RUNTIME / "moving_mesh_patch_consistency_fix_and_1s_retry_v1_contract.json"
STATE = ROOT / "runtime/stage4f_d_cpp_worker_initialization_v1/run_20260827_cpp_only/ancf_t0_state_cpp.json"
RESULTS = ROOT / "results" / TASK


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def norm2(value: list[float]) -> float:
    return math.sqrt(sum(item * item for item in value))


def build_manifest(contract: dict[str, Any]) -> tuple[SliceManifest, dict[int, tuple[tuple[float, ...], ...]], tuple[SliceDefinition, ...]]:
    items = contract["slices"]["items"]
    partition = bounded_midpoint_voronoi([item["s_ref_m"] for item in items], contract["slices"]["represented_interval_m"])
    definitions = tuple(SliceDefinition(int(item["slice_id"]), float(item["s_ref_m"]), right - left,
                                        float(item["unit_span_m"]))
                        for item, (left, _, right) in zip(items, partition))
    length = float(contract["ANCF"]["length_m"])
    manifest = SliceManifest("0.2.1", str(contract["case_id"]), length, length, definitions)
    h = build_H_for_manifest(manifest, tuple(length * i / int(contract["ANCF"]["elements"])
                                              for i in range(int(contract["ANCF"]["elements"]) + 1)))
    return manifest, h, definitions


def write_fixture(path: Path, contract: dict[str, Any], state: dict[str, Any], force: list[float]) -> None:
    ancf, cfd, items = contract["ANCF"], contract["CFD"], contract["slices"]["items"]
    header = [float(ancf["length_m"]), float(ancf["diameter_m"]), float(ancf["inner_diameter_m"]),
              int(ancf["elements"]), len(items), float(ancf["youngs_modulus_Pa"]),
              float(ancf["material_density_kgpm3"]), float(cfd["fluid_density_kgpm3"]),
              float(ancf["gravity_mps2"]), float(ancf["newmark_beta"]), float(ancf["newmark_gamma"]),
              float(ancf["newton_tolerance"]), int(ancf["gauss_order"]), int(ancf["max_newton_iterations"]),
              float(contract["dt_s"])]
    values = header + [float(item["s_ref_m"]) for item in items]
    for key in ("q", "qdot", "qddot", "base_load", "mass_matrix"):
        values.extend(float(item) for item in state[key])
    values.extend(float(item) for item in force)
    path.write_text(" ".join(format(item, ".17g") for item in values) + "\n", encoding="ascii")


def read_diagnostic(path: Path) -> dict[str, list[float]]:
    wanted = {"mapping_H3", "external_total", "external_slice_0", "external_slice_1", "external_slice_2"}
    result: dict[str, list[float]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        words = line.split()
        if not words or words[0] not in wanted:
            continue
        size = int(words[1]); values = [float(item) for item in words[2:]]
        if len(values) != size:
            raise RuntimeError(f"diagnostic vector length mismatch: {words[0]}")
        result[words[0]] = values
    if result.keys() != wanted:
        raise RuntimeError("diagnostic output lacks mapping evidence")
    return result


def cpp_run(executable: Path, fixture: Path, output: Path) -> dict[str, list[float]]:
    completed = subprocess.run([str(executable), str(fixture), str(output)], text=True,
                               capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    if completed.returncode != 0:
        raise RuntimeError(f"C++ diagnostic failed: rc={completed.returncode}; stderr={completed.stderr.strip()}")
    return read_diagnostic(output)


def location(s_ref_m: float, length_m: float, elements: int) -> dict[str, float | int]:
    le = length_m / elements
    element = elements - 1 if s_ref_m == length_m else min(elements - 1, int(math.floor(s_ref_m / le)))
    x = s_ref_m - element * le
    return {"element_index_0_based": element, "xi": x / le, "element_length_m": le}


def compare_case(name: str, executable: Path, contract: dict[str, Any], state: dict[str, Any],
                 force: list[float], manifest: SliceManifest, h: dict[int, tuple[tuple[float, ...], ...]],
                 definitions: tuple[SliceDefinition, ...], output_dir: Path) -> dict[str, Any]:
    fixture, output = output_dir / f"{name}.fixture.txt", output_dir / f"{name}.cpp.txt"
    write_fixture(fixture, contract, state, force)
    cpp = cpp_run(executable, fixture, output)
    # ``force`` is already the formal integrated slice force in N.  Passing
    # bare vectors deliberately prevents a second unit-span/tributary-length
    # conversion inside this offline mapper.
    loads = {item.slice_id: tuple(force[3 * item.slice_id:3 * item.slice_id + 3]) for item in definitions}
    formal = map_integrated_slice_forces(manifest, h, loads)
    q_formal, q_cpp = list(formal.generalized_force), cpp["external_total"]
    delta = [right - left for left, right in zip(q_formal, q_cpp)]
    scale = max(1.0, *(abs(item) for item in q_formal), *(abs(item) for item in q_cpp))
    per_slice = []
    for item in definitions:
        sid = item.slice_id
        a, b = list(formal.slice_contributions[sid]), cpp[f"external_slice_{sid}"]
        d = [right - left for left, right in zip(a, b)]
        per_slice.append({"slice_id": sid, "Q_formal_N": a, "Q_cpp_N": b,
                          "max_abs_error_N": max(map(abs, d)), "l2_error_N": norm2(d)})
    cpp_h = [cpp["mapping_H3"][row * len(q_formal):(row + 1) * len(q_formal)] for row in range(9)]
    py_h = [list(value) for sid in range(3) for value in h[sid]]
    h_delta = [b - a for aa, bb in zip(py_h, cpp_h) for a, b in zip(aa, bb)]
    largest = max(range(len(delta)), key=lambda index: abs(delta[index]))
    result = {"name": name, "force_representation": "integrated_slice_force_N", "force_flatten_order":
              "[slice0_x,slice0_y,slice0_z,slice1_x,slice1_y,slice1_z,slice2_x,slice2_y,slice2_z]",
              "force_N": force, "Q_formal_N": q_formal, "Q_cpp_N": q_cpp, "delta_Q_N": delta,
              "max_abs_error_N": max(map(abs, delta)), "l2_error_N": norm2(delta),
              "scale_N": scale, "normalized_inf_error": max(map(abs, delta)) / scale,
              "max_difference_dof": largest, "per_slice": per_slice,
              "H_max_abs_error": max(map(abs, h_delta)),
              "location": {str(item.slice_id): location(item.s_ref_m, manifest.reference_length_m,
                                                          int(contract["ANCF"]["elements"])) for item in definitions},
              "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
              "cpp_output_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    (output_dir / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpp-diagnostic", type=Path, required=True)
    args = parser.parse_args()
    if not args.cpp_diagnostic.is_file():
        raise SystemExit("C++ diagnostic executable is missing")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8")); initial = json.loads(STATE.read_text(encoding="utf-8"))
    records = [json.loads(line) for line in (FAILED_RUNTIME / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    manifest, h, definitions = build_manifest(contract); RESULTS.mkdir(parents=True, exist_ok=True)
    committed: list[dict[str, Any]] = []
    for index, row in enumerate(records):
        input_state = initial if index == 0 else {**initial, **records[index - 1]["ancf_state"]}
        force = [float(load[f"force_{axis}_N"]) for load in row["loads"] for axis in "xyz"]
        replay = compare_case(f"committed_step_{row['global_step']:03d}", args.cpp_diagnostic, contract,
                              input_state, force, manifest, h, definitions, RESULTS)
        observed_cpp = [float(value) for value in row["correction"]["cpp_cfd_generalized_force_N"]]
        observed_delta = [right - left for left, right in zip(replay["Q_formal_N"], observed_cpp)]
        observed_scale = max(1.0, *(abs(value) for value in replay["Q_formal_N"]),
                             *(abs(value) for value in observed_cpp))
        replay["historical_adapter_comparison"] = {
            "Q_cpp_cfd_derived_by_total_minus_base_N": observed_cpp,
            "delta_Q_N": observed_delta,
            "max_abs_error_N": max(map(abs, observed_delta)),
            "l2_error_N": norm2(observed_delta),
            "scale_N": observed_scale,
            "normalized_inf_error": max(map(abs, observed_delta)) / observed_scale,
            "max_difference_dof": max(range(len(observed_delta)), key=lambda i: abs(observed_delta[i])),
            "semantics": "historical adapter compares Q_cpp_total_N - frozen_base_load_N against formal CFD-only H^T F",
        }
        replay["global_step"] = row["global_step"]; replay["time_s"] = row["time_s"]
        committed.append(replay)
    realistic = [float(load[f"force_{axis}_N"]) for load in records[-1]["loads"] for axis in "xyz"]
    synthetic_forces = {
        "zero_force": [0.0] * 9,
        "slice0_x": [1.0, 0.0, 0.0] + [0.0] * 6,
        "slice1_y": [0.0] * 3 + [0.0, 1.0, 0.0] + [0.0] * 3,
        "slice2_z": [0.0] * 6 + [0.0, 0.0, 1.0],
        "all_equal": [2.0, -3.0, 4.0] * 3,
        "all_different": [1.0, 2.0, 3.0, -4.0, 5.0, -6.0, 7.0, -8.0, 9.0],
        "mixed_sign": [-1.0, 2.0, -3.0, 4.0, -5.0, 6.0, -7.0, 8.0, -9.0],
        "realistic_step9": realistic,
        "realistic_step9_x0p1": [0.1 * item for item in realistic],
        "realistic_step9_x10": [10.0 * item for item in realistic],
        "realistic_step9_x0p01": [0.01 * item for item in realistic],
        "realistic_step9_x100": [100.0 * item for item in realistic],
    }
    synthetic = [compare_case(name, args.cpp_diagnostic, contract, initial, force, manifest, h, definitions, RESULTS)
                 for name, force in synthetic_forces.items()]
    summary = {"task": TASK, "offline_only": True, "failed_runtime_read_only_sha256": {
        "records_jsonl": hashlib.sha256((FAILED_RUNTIME / "records.jsonl").read_bytes()).hexdigest(),
        "structure_summary_json": hashlib.sha256((FAILED_RUNTIME / "structure_summary.json").read_bytes()).hexdigest()},
        "committed_replays": committed, "historical_adapter_error_evolution": [
            {"global_step": entry["global_step"], "time_s": entry["time_s"],
             **entry["historical_adapter_comparison"]} for entry in committed], "synthetic_matrix": synthetic,
        "failure_step_10_replay": "NOT_EVALUABLE: no correction-attempt fixture, request payload, received force vector, or Q_cpp was persisted before the fail-closed exception",
        "replay_gate": "PARTIAL_PASS: all persisted committed fixtures replayed; failed correction cannot be reproduced from immutable evidence"}
    (RESULTS / "generalized_force_replay_v1_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"replay_gate": summary["replay_gate"], "committed_steps": len(committed)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
