"""Prepare a fresh 80 s restart with state and CFD boundaries on one clock."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUNTIME = ROOT / "runtime/stage341_dt005_long_convergence_v1"
SOURCE_STATE = SOURCE_RUNTIME / "logs/structure_participant.json"
DIAGNOSTICS = SOURCE_RUNTIME / "logs/mapping_diagnostics.jsonl"
BOOTSTRAP = ROOT / "results/350_restart_bootstrap_velocity_v1/restart_bootstrap_state.json"
RUNTIME = ROOT / "runtime/stage356_restart_bootstrap_boundary_alignment_v1_fresh"
RESULTS = ROOT / "results/356_restart_bootstrap_boundary_alignment_v1"
DT = 0.005
TARGET_STEP = 16000
TARGET_TIME = 80.0
POSITIONS = (8.333333333333334, 25.0, 41.666666666666664)

spec = importlib.util.spec_from_file_location(
    "stage352_prepare", ROOT / "tools/stage352_restart_boundary_v1/prepare_boundary_aligned_restart.py"
)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load binary field preparation helper")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
sys_path = ROOT / "src"
import sys
if str(sys_path) not in sys.path:
    sys.path.insert(0, str(sys_path))
from coupling.stage303_interface_mapping_repair_v1 import canonical_h_row, project_interface  # noqa: E402


def digest(values: list[float]) -> str:
    return hashlib.sha256(struct.pack("<" + "d" * len(values), *values)).hexdigest()


def align(values: list[float], target: list[list[float]], projected, label: str) -> tuple[list[float], float]:
    for index, row_target in enumerate(target):
        row = canonical_h_row(POSITIONS[index])
        for component in (0, 1):
            delta = float(row_target[component]) - float(projected[index][component])
            pivot = next(i for i, value in enumerate(row) if i % 6 == component and abs(value) > 1.0e-14)
            values[pivot] += delta / row[pivot]
    if label == "q":
        after = project_interface(values, [0.0] * len(values))[0]
    else:
        after = project_interface([0.0] * len(values), values)[1]
    error = max(((a[0] - t[0]) ** 2 + (a[1] - t[1]) ** 2) ** 0.5 for a, t in zip(after, target))
    return values, error


def main() -> int:
    source = json.loads(SOURCE_STATE.read_text(encoding="utf-8"))
    bootstrap = json.loads(BOOTSTRAP.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in DIAGNOSTICS.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_step = {int(row["global_step"]): row for row in rows}
    if source.get("finalized") is not True or source.get("target_global_step") != TARGET_STEP:
        raise RuntimeError("protected Stage341 source is not finalized at step 16000")
    if TARGET_STEP not in by_step or TARGET_STEP - 1 not in by_step:
        raise RuntimeError("diagnostics must contain steps 15999 and 16000")
    if bootstrap.get("state_time_s") != 79.995 or bootstrap.get("source_global_step") != TARGET_STEP:
        raise RuntimeError("Stage350 bootstrap identity is not the expected lag-1 source")
    if RUNTIME.exists() and any(RUNTIME.iterdir()):
        raise RuntimeError(f"refusing to reuse non-empty runtime: {RUNTIME}")

    target = by_step[TARGET_STEP]
    previous = by_step[TARGET_STEP - 1]
    q = list(bootstrap["q"])
    qdot = list(bootstrap["qdot"])
    qddot = list(bootstrap["qddot"])
    q, q_error = align(q, target["interface_positions_xy"], project_interface(q, qdot)[0], "q")
    qdot, v_error = align(qdot, target["interface_velocities_xy"], project_interface(q, qdot)[1], "qdot")
    acceleration = [[
        (float(target["interface_velocities_xy"][i][c]) - float(previous["interface_velocities_xy"][i][c])) / DT
        for c in (0, 1)
    ] for i in range(3)]
    qddot, a_error = align(qddot, acceleration, project_interface([0.0] * len(qddot), qddot)[1], "qddot")
    if max(q_error, v_error, a_error) > 1.0e-10:
        raise RuntimeError(f"state alignment exceeds tolerance: q={q_error}, v={v_error}, a={a_error}")

    patched = []
    for index, xy in enumerate(target["interface_positions_xy"]):
        source_case = SOURCE_RUNTIME / f"slice_{index:04d}"
        destination = RUNTIME / f"slice_{index:04d}"
        shutil.copytree(source_case, destination)
        for child in list(destination.iterdir()):
            if child.name not in {"80", "constant", "system"}:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        field = destination / "80"
        patched.append(helper.patch_cylinder_value(field / "pointDisplacement", (float(xy[0]), float(xy[1]), 0.0)))
        patched.append(helper.patch_cylinder_value(field / "cellDisplacement", (float(xy[0]), float(xy[1]), 0.0)))
        control = destination / "system/controlDict"
        text = control.read_text(encoding="utf-8")
        text = helper.re.sub(r"startFrom\s+[^;]+;", "startFrom       latestTime;", text)
        text = helper.re.sub(r"startTime\s+[^;]+;", "startTime       80;", text)
        text = helper.re.sub(r"endTime\s+[^;]+;", "endTime         80.2;", text)
        text = helper.re.sub(r"purgeWrite\s+[^;]+;", "purgeWrite      1;", text)
        control.write_text(text, encoding="utf-8")

    (RUNTIME / "logs").mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1, "stage_id": "stage4f_d_restart_bootstrap_boundary_alignment_v1",
        "source_global_step": TARGET_STEP, "source_time_s": TARGET_TIME, "state_time_s": TARGET_TIME,
        "q": q, "qdot": qdot, "qddot": qddot,
        "q_sha256": digest(q), "qdot_sha256": digest(qdot), "qddot_sha256": digest(qddot),
        "alignment": {"from_state_time_s": 79.995, "displacement_error_m": q_error,
                       "velocity_error_m_per_s": v_error, "acceleration_error_m_per_s2": a_error},
        "direct_final_q_rejected": True,
    }
    state_path = RUNTIME / "logs/initial_state.json"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "schema_version": 1, "stage_id": "stage4f_d_restart_bootstrap_boundary_alignment_v1",
        "source_stage": "stage341_dt005_long_convergence_v1", "source_global_step": TARGET_STEP,
        "field_time_s": TARGET_TIME, "state_time_s": TARGET_TIME,
        "target_interface_positions_xy": target["interface_positions_xy"], "patched": patched,
        "state_sha256": {"initial_state": digest(q) + ":" + digest(qdot) + ":" + digest(qddot)},
        "checks": {"source_runtime_read_only": True, "state_boundary_clock_equal": True,
                   "kinematic_alignment": max(q_error, v_error, a_error) <= 1.0e-10,
                   "point_and_cell_boundaries_patched": len(patched) == 6,
                   "matlab_starts": 0, "openfoam_starts": 0, "wsl_starts": 0,
                   "cfd_starts": 0, "owned_residual": 0},
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "restart_bootstrap_boundary_alignment.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gate = dict(report, gate_id="STAGE4F_D_RESTART_BOOTSTRAP_BOUNDARY_ALIGNMENT_V1_GATE", status="pass",
                next_action="request a new one-shot real Smoke; no continuation")
    (RESULTS / "stage4f_d_restart_bootstrap_boundary_alignment_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": "pass", "state_time_s": TARGET_TIME, "patched_files": len(patched), "external_starts": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
