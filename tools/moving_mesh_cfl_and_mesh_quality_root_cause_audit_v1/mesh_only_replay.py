"""Mesh-only replay of the persisted coupled displacement history; no CFD."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAILED = ROOT / "runtime/generalized_force_metric_v2_0p1s_micro_smoke_v1_run_001"
RUNTIME = ROOT / "runtime/moving_mesh_replay_v1_run_003"
RESULTS = ROOT / "results/moving_mesh_replay_v1_run_003"
DT = 0.005
END = 0.07


def wsl(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def table(rows: list[dict], sid: int) -> str:
    values = [(0.0, (0.0, 0.0, 0.0))]
    # A fluid mesh at n*dt carries the displacement received in the preceding
    # explicit window: at 0.05 it was structure step 9, as observed directly.
    for index, row in enumerate(rows, start=1):
        m = row["motion"][sid]
        values.append(((index + 1) * DT, (float(m["ux_m"]), float(m["uy_m"]), 0.0)))
    return " ".join(f"({time:.12g} ({x:.17g} {y:.17g} {z:.17g}))" for time, (x, y, z) in values)


def field(kind: str, values: str) -> str:
    cls = "pointVectorField" if kind == "pointDisplacement" else "volVectorField"
    return f'''FoamFile {{ format ascii; class {cls}; location "0"; object {kind}; }}
dimensions [0 1 0 0 0 0 0];
internalField uniform (0 0 0);
boundaryField {{
 inlet {{ type fixedValue; value uniform (0 0 0); }} outlet {{ type fixedValue; value uniform (0 0 0); }}
 lower {{ type symmetryPlane; }} upper {{ type symmetryPlane; }}
 cylinder {{ type uniformFixedValue; uniformValue table ({values}); }}
 front {{ type empty; }} back {{ type empty; }}
}}
'''


def main() -> int:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to reuse mesh-only replay paths")
    rows = [json.loads(line) for line in (FAILED / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    if len(rows) != 13:
        raise RuntimeError("persisted history is incomplete")
    commands = ["source /opt/openfoam10/etc/bashrc", "set -e"]
    for sid in range(3):
        source = FAILED / "cases" / f"slice_{sid:04d}"; case = RUNTIME / f"slice_{sid:04d}"
        for name in ("0", "constant", "system"):
            shutil.copytree(source / name, case / name)
        values = table(rows, sid)
        (case / "0/pointDisplacement").write_text(field("pointDisplacement", values), encoding="utf-8")
        (case / "0/cellDisplacement").write_text(field("cellDisplacement", values), encoding="utf-8")
        (case / "system/controlDict").write_text(
            f'FoamFile {{ format ascii; class dictionary; object controlDict; }}\napplication moveMesh;\nstartFrom startTime; startTime 0; stopAt endTime; endTime {END}; deltaT {DT};\nwriteControl timeStep; writeInterval 1; purgeWrite 0; writeFormat ascii; writePrecision 12; timeFormat general; timePrecision 12; runTimeModifiable false;\n', encoding="utf-8")
        commands.append(f"(cd '{wsl(case)}' && moveMesh > moveMesh.stdout 2> moveMesh.stderr)")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    launcher = RUNTIME / "launch.sh"
    with launcher.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(commands) + "\n")
    done = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(launcher)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    (RUNTIME / "launcher.stdout").write_text(done.stdout, encoding="utf-8")
    (RUNTIME / "launcher.stderr").write_text(done.stderr, encoding="utf-8")
    result = {"MOVING_MESH_REPLAY_V1": "PASS" if done.returncode == 0 else "FAIL", "return_code": done.returncode,
              "history_source": str((FAILED / "records.jsonl").relative_to(ROOT)), "duration_s": END,
              "CFD_equations": "not run"}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "gate.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
