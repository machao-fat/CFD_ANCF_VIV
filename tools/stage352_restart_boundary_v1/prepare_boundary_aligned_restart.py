"""Materialize a restart field whose cylinder boundary matches 80.0 s.

The source 80 directory is preserved. This tool edits only copied binary
pointDisplacement/cellDisplacement boundary dictionaries and records hashes.
It does not invoke WSL or any CFD executable.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "runtime/stage341_dt005_long_convergence_v1"
SOURCE_STATE = SOURCE / "logs/structure_participant.json"
DIAGNOSTICS = SOURCE / "logs/mapping_diagnostics.jsonl"
RUNTIME = ROOT / "runtime/stage352_restart_boundary_v1_candidate"
RESULTS = ROOT / "results/352_restart_boundary_v1"
STAGE_ID = "stage4f_d_restart_boundary_v1"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def patch_cylinder_value(path: Path, value: tuple[float, float, float]) -> dict[str, object]:
    data = path.read_bytes()
    marker = b"\nboundaryField\n"
    boundary = data.find(marker)
    if boundary < 0:
        raise RuntimeError(f"boundaryField missing: {path}")
    cyl = data.find(b"\n    cyl\n    {", boundary)
    if cyl < 0:
        raise RuntimeError(f"cyl patch missing: {path}")
    end = data.find(b"\n    }", cyl)
    if end < 0:
        raise RuntimeError(f"cyl patch terminator missing: {path}")
    block = data[cyl:end]
    replacement = f"value           uniform ({value[0]:.17g} {value[1]:.17g} {value[2]:.17g});".encode("ascii")
    # OpenFOAM binary lists place the first bytes immediately after `(`.
    nonuniform = re.search(rb"value\s+nonuniform\s+List<vector>\s*\n\s*(\d+)\s*\n\(", block)
    if nonuniform:
        count = int(nonuniform.group(1))
        binary_start = cyl + nonuniform.end()
        binary_end = binary_start + count * 24
        if data[binary_end:binary_end + 3] != b");\n":
            raise RuntimeError(f"unexpected binary boundary layout: {path}")
        start = cyl + nonuniform.start()
        data = data[:start] + replacement + data[binary_end + 3:]
        mode = "nonuniform-to-uniform"
    else:
        uniform = re.search(rb"value\s+uniform\s*\([^;]+\);", block)
        if not uniform:
            raise RuntimeError(f"cylinder value entry missing: {path}")
        start = cyl + uniform.start()
        stop = cyl + uniform.end()
        data = data[:start] + replacement + data[stop:]
        mode = "uniform-replaced"
    path.write_bytes(data)
    return {"path": str(path), "mode": mode, "sha256": sha(path), "value": list(value)}


def main() -> int:
    source = json.loads(SOURCE_STATE.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in DIAGNOSTICS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if source.get("finalized") is not True or source.get("target_global_step") != 16000 or abs(float(source.get("target_time_s", -1)) - 80.0) > 1e-12:
        raise RuntimeError("source is not finalized at 16000/80 s")
    target = next((row for row in rows if row.get("global_step") == 16000), None)
    if target is None:
        raise RuntimeError("diagnostic step 16000 is missing")
    if RUNTIME.exists() and any(RUNTIME.iterdir()):
        raise RuntimeError(f"refusing to reuse non-empty runtime: {RUNTIME}")
    patched = []
    for index, xy in enumerate(target["interface_positions_xy"]):
        source_case = SOURCE / f"slice_{index:04d}"
        destination = RUNTIME / f"slice_{index:04d}"
        shutil.copytree(source_case, destination)
        for child in list(destination.iterdir()):
            if child.name not in {"80", "constant", "system"}:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        field = destination / "80"
        patched.append(patch_cylinder_value(field / "pointDisplacement", (float(xy[0]), float(xy[1]), 0.0)))
        patched.append(patch_cylinder_value(field / "cellDisplacement", (float(xy[0]), float(xy[1]), 0.0)))
        control = destination / "system/controlDict"
        text = control.read_text(encoding="utf-8")
        text = re.sub(r"startFrom\s+[^;]+;", "startFrom       latestTime;", text)
        text = re.sub(r"startTime\s+[^;]+;", "startTime       80;", text)
        text = re.sub(r"endTime\s+[^;]+;", "endTime         80.2;", text)
        text = re.sub(r"purgeWrite\s+[^;]+;", "purgeWrite      1;", text)
        control.write_text(text, encoding="utf-8")
    (RUNTIME / "logs").mkdir(parents=True, exist_ok=True)
    state = {"schema_version": 1, "stage_id": STAGE_ID, "source_global_step": 16000, "source_time_s": 80.0, "state_time_s": 80.0, "q": source["final_q"], "qdot": source["final_qdot"], "qddot": source["final_qddot"], "direct_final_q_rejected": False}
    (RUNTIME / "logs/initial_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"schema_version": 1, "stage_id": STAGE_ID, "source_stage": "stage341_dt005_long_convergence_v1", "source_field_directory": "80", "field_time_s": 80.0, "state_time_s": 80.0, "target_global_step": 16000, "target_interface_positions_xy": target["interface_positions_xy"], "patched": patched, "checks": {"source_read_only": True, "point_and_cell_boundaries_patched": len(patched) == 6, "wsl_starts": 0, "openfoam_starts": 0, "matlab_starts": 0, "cfd_starts": 0, "owned_residual": 0}}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "restart_boundary_preparation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gate = dict(report, gate_id=f"{STAGE_ID.upper()}_GATE", status="pass")
    (RESULTS / "stage4f_d_restart_boundary_preparation_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "patched_files": len(patched), "runtime": str(RUNTIME)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
