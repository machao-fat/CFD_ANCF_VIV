"""Read-only audit of the single authorized W10 prescribed-motion replay."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "runtime/formal_three_slice_implicit_0p05s_owned_mesh_history_v1_run_001"
REPLAY = ROOT / "runtime/window10_predictor_force_identity_replay_v1_run_003"
OUT = ROOT / "results/window10_predictor_force_identity_replay_v1_run_001"
DT = 0.005
# Applied only by this read-only audit.  It was not serialized in preflight,
# so it cannot retroactively satisfy the requested pre-execution comparator
# governance.  It does make the observed arithmetic comparison reproducible.
ABS_TOL_N = 1.0e-5
REL_TOL = 1.0e-11


def canonical(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def put_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def force_blocks(path: Path) -> list[dict[str, list[float]]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    pressure = viscous = None
    mode = ""
    result: list[dict[str, list[float]]] = []
    vector = re.compile(r"\(([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\)")
    for line in lines:
        if "sum of forces:" in line:
            mode, pressure, viscous = "forces", None, None
        elif "sum of moments:" in line:
            mode, pressure, viscous = "", None, None
        elif mode == "forces" and "pressure :" in line:
            match = vector.search(line)
            pressure = [float(match.group(index)) for index in (1, 2, 3)] if match else None
        elif mode == "forces" and "viscous  :" in line:
            match = vector.search(line)
            viscous = [float(match.group(index)) for index in (1, 2, 3)] if match else None
            if pressure is not None and viscous is not None:
                result.append({"pressure_N": pressure, "viscous_N": viscous,
                               "total_N": [pressure[index] + viscous[index] for index in range(3)]})
                mode, pressure, viscous = "", None, None
    if not result:
        raise RuntimeError(f"no cylinderForces force blocks in {path}")
    return result


def final_co(path: Path) -> dict[str, float]:
    matches = re.findall(r"Courant Number mean:\s*([0-9.eE+-]+)\s+max:\s*([0-9.eE+-]+)",
                         path.read_text(encoding="utf-8", errors="replace"))
    if not matches:
        raise RuntimeError(f"no Courant evidence in {path}")
    mean, maximum = matches[-1]
    return {"mean": float(mean), "max": float(maximum)}


def final_structure_force(slice_id: int) -> dict[str, Any]:
    value = json.loads((REPLAY / f"structure_{slice_id:04d}_transaction.json").read_text(encoding="utf-8"))
    rows = [row for row in value["rows"] if row["event"] == "STRUCTURE_RECEIVE_RAW_FORCE" and
            any(abs(float(item)) > 0.0 for item in row["sum_force_xy_N"])]
    if len(rows) != 1 or rows[0]["iteration"] != 3:
        raise RuntimeError(f"slice {slice_id} lacks one nonzero trial-3 received force")
    return rows[0]


def original_breach() -> dict[str, float]:
    value = json.loads((SOURCE / "containment_event.json").read_text(encoding="utf-8"))
    if value["window_index"] != 10 or value["iteration_index"] != 3:
        raise RuntimeError("immutable containment event is not W10/trial3")
    return {str(row["slice_id"]): float(row["value"]) for row in value["breaches"] if row["quantity"] == "raw_Fx_N"}


def compare(actual: float, expected: float) -> dict[str, Any]:
    absolute = abs(actual - expected)
    relative = absolute / max(1.0, abs(actual), abs(expected))
    return {"actual": actual, "expected": expected, "abs_error": absolute, "rel_error": relative,
            "pass": absolute <= ABS_TOL_N or relative <= REL_TOL}


def trace_final(slice_id: int) -> dict[str, Any]:
    rows = [json.loads(line) for line in (REPLAY / f"fluid_{slice_id:04d}_adapter_trace.jsonl").read_text(encoding="utf-8").splitlines() if line]
    finals = [row for row in rows if row.get("event") == "FINAL_COMMIT"]
    if len(finals) != 1 or finals[0].get("physical_time") != 0.15:
        raise RuntimeError(f"slice {slice_id} has no unique participant-local replay FINAL_COMMIT")
    return finals[0]


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from coupling.multi_slice_mapping.mapping import (LoadRecord, SliceDefinition, SliceManifest,
        build_H_for_manifest, map_integrated_slice_forces)
    from coupling.three_slice_force_contract_smoke_v1.contract import bounded_midpoint_voronoi

    preflight = json.loads((REPLAY / "preflight.json").read_text(encoding="utf-8"))
    payloads = json.loads((REPLAY / "payloads.json").read_text(encoding="utf-8"))
    contract = json.loads((SOURCE / "preconditioned_coupled_0p1s_smoke_v1_contract.json").read_text(encoding="utf-8"))
    breaches = original_breach()
    raw: dict[int, dict[str, Any]] = {}
    replay_fluid: dict[int, dict[str, list[float]]] = {}
    for sid in range(3):
        replay_fluid[sid] = force_blocks(REPLAY / f"fluid_{sid:04d}.stdout")[-1]
        received = final_structure_force(sid)
        raw[sid] = {"fluid_cylinderForces": replay_fluid[sid], "structure_receive": received,
                    "fluid_to_structure_x": compare(float(received["sum_force_xy_N"][0]), replay_fluid[sid]["total_N"][0]),
                    "fluid_to_structure_y": compare(float(received["sum_force_xy_N"][1]), replay_fluid[sid]["total_N"][1]),
                    "Co": final_co(REPLAY / f"fluid_{sid:04d}.stdout"), "adapter_final_event": trace_final(sid)}
    breach_comparison = {sid: compare(raw[int(sid)]["structure_receive"]["sum_force_xy_N"][0], value)
                         for sid, value in breaches.items()}

    items = contract["slices"]["items"]
    length, elements = float(contract["ANCF"]["length_m"]), int(contract["ANCF"]["elements"])
    partition = bounded_midpoint_voronoi([item["s_ref_m"] for item in items], contract["slices"]["represented_interval_m"])
    definitions = tuple(SliceDefinition(int(item["slice_id"]), float(item["s_ref_m"]), right-left,
                                        float(item["unit_span_m"])) for item, (left, _, right) in zip(items, partition))
    manifest = SliceManifest("0.2.1", str(contract["case_id"]), length, length, definitions)
    H = build_H_for_manifest(manifest, tuple(length * index / elements for index in range(elements + 1)))
    loads = {sid: LoadRecord.from_conversion(case_id=str(contract["case_id"]), step=10, time_s=0.05,
             slice_definition=definitions[sid], unit_span_m=definitions[sid].unit_span_m,
             openfoam_force_N=(raw[sid]["structure_receive"]["sum_force_xy_N"][0],
                               raw[sid]["structure_receive"]["sum_force_xy_N"][1], 0.0),
             cfd_time_step_s=DT) for sid in range(3)}
    checkpoint = json.loads((SOURCE / "checkpoints/window_000010_checkpoint.json").read_text(encoding="utf-8"))
    current_q = checkpoint["physical"]["adapter_state"]["q"]
    predictor_q = payloads["full_predictor_state_sha256"]
    # The full q vector is intentionally not repeated in payloads; it is
    # recomputed in the preflight worker segment and attested by its exact hash.
    mapping = map_integrated_slice_forces(manifest, H, loads)
    all_numeric = all(value["pass"] for row in raw.values() for name, value in row.items()
                      if name.startswith("fluid_to_structure"))
    all_breach = all(value["pass"] for value in breach_comparison.values())
    result = {"schema_version": "window10-predictor-force-identity-replay-audit-v1",
              "transaction_id": payloads["transaction_id"], "preflight_status": preflight["status"],
              "comparator": {"abs_tolerance_N": ABS_TOL_N, "relative_tolerance": REL_TOL,
                  "governance": "POST_EXECUTION_AUDIT_ONLY; not present in preflight.json"},
              "prediction_identity": {key: payloads[key] for key in ("original_prediction_response_hash",
                  "regenerated_prediction_response_hash", "full_predictor_state_sha256", "predictor_payload_sha256",
                  "projection_contract")},
              "cross_channel": raw, "original_containment_breach_comparison": breach_comparison,
              "original_fluid_log_time_label_limit": "The formal run terminated after Structure containment; its ordinary .150 cylinderForces log is a different functionObject phase and is not used as the force delivered to Structure.",
              "force_contract_loads": {str(sid): loads[sid].to_dict() for sid in range(3)},
              "generalized_force_formal_N": list(mapping.generalized_force),
              "generalized_force_mapping_v2": "NOT_EVALUABLE_NO_ANCF_CORRECTION_AUTHORIZED",
              "unused_checkpoint_current_q_sha256": canonical(current_q),
              "unused_predictor_q_sha256": predictor_q,
              "participant_local_final_commits_only": True,
              "CROSS_CHANNEL_FORCE_IDENTITY_NUMERIC_OBSERVATION": "PASS" if all_numeric and all_breach else "FAIL",
              "WINDOW10_FORCE_RESPONSE_NUMERIC_OBSERVATION": "REPRODUCIBLE" if all_numeric and all_breach else "NOT_REPRODUCIBLE",
              "CROSS_CHANNEL_FORCE_IDENTITY": "NOT_EVALUABLE_STRICT_PREDECLARED_TOLERANCE_MISSING",
              "WINDOW10_FORCE_RESPONSE": "NOT_EVALUABLE_STRICT_PREDECLARED_TOLERANCE_MISSING",
              "next_implicit_0p05s": "NOT_AUTHORIZED", "next_long_viv": "NOT_AUTHORIZED"}
    put_json(OUT / "window10_predictor_force_identity_replay_audit.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
