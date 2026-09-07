"""Real preCICE initial-data and socket-path regression; no CFD or ANCF."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.precice_path_v1 import canonical_wsl_path, socket_directory_preflight


REGRESSION_ID = os.environ.get(
    "FORMAL_IMPLICIT_INITIAL_DATA_REGRESSION_ID",
    "formal_implicit_initial_data_and_socket_path_fix_v1_regression_001",
)
RUN = ROOT / "runtime" / REGRESSION_ID
RESULTS = ROOT / "results" / REGRESSION_ID
DT = 0.005


def put(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def xml(socket: Path) -> str:
    return "\n".join((
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">',
        '<data:vector name="Displacement" waveform-degree="0"/>',
        '<mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement"/></mesh><mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement"/></mesh>',
        f'<m2n:sockets acceptor="Structure" connector="Fluid" exchange-directory="{canonical_wsl_path(socket)}"/>',
        '<participant name="Structure"><provide-mesh name="Structure-Mesh"/><write-data name="Displacement" mesh="Structure-Mesh"/></participant>',
        '<participant name="Fluid"><receive-mesh name="Structure-Mesh" from="Structure"/><provide-mesh name="Fluid-Mesh"/><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent"/><read-data name="Displacement" mesh="Fluid-Mesh"/></participant>',
        '<coupling-scheme:parallel-explicit><participants first="Structure" second="Fluid"/><time-window-size value="0.005"/><max-time value="0.005"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure" to="Fluid" initialize="yes" substeps="false"/></coupling-scheme:parallel-explicit>',
        '</precice-configuration>',
    ))


def role_code() -> str:
    return r'''from __future__ import annotations
import json, sys
from pathlib import Path
import precice
role, config_s, output_s, value_s, missing_s = sys.argv[1:6]
config, output, value = Path(config_s), Path(output_s), float(value_s)
missing = missing_s == "1"
p=precice.Participant(role,str(config),0,1)
mesh_name="Structure-Mesh" if role=="Structure" else "Fluid-Mesh"
ids=p.set_mesh_vertices(mesh_name,[(0.0,0.0)])
row={"role":role,"value":value,"requires_initial_data":p.requires_initial_data()}
if role=="Structure" and row["requires_initial_data"] and missing:
    raise RuntimeError("fail-closed: required initial Displacement was intentionally omitted")
if role=="Structure" and row["requires_initial_data"] and not missing:
    payload=[[0.0,value]]
    p.write_data(mesh_name,"Displacement",ids,payload)
    row["initial_payload"]=payload
p.initialize()
if role=="Fluid":
    received=p.read_data(mesh_name,"Displacement",ids,0.0)
    row["received_initial"]=received.tolist() if hasattr(received,"tolist") else received
if p.is_coupling_ongoing():
    if role=="Structure": p.write_data(mesh_name,"Displacement",ids,[[0.0,value]])
    p.advance(0.005)
p.finalize()
output.write_text(json.dumps(row,indent=2)+"\n",encoding="utf-8")
'''


def execute_case(name: str, value: float, missing: bool = False) -> dict:
    directory = RUN / name
    directory.mkdir(parents=True)
    (directory / "sockets").mkdir()
    put(directory / "precice-config.xml", xml(directory / "sockets"))
    put(directory / "role.py", role_code())
    if missing:
        # The project-level fail-closed check happens immediately after the
        # real API reports requires_initial_data(), before initialize() opens
        # any coupling transport.  Keep this negative test single-sided so a
        # peer cannot wait indefinitely after the deliberate rejection.
        call = ["python3", str(directory / "role.py"), "Structure", str(directory / "precice-config.xml"), str(directory / "structure.json"), str(value), "1"]
        done = subprocess.run(call, text=True, capture_output=True, timeout=10)
        put(directory / "stdout", done.stdout); put(directory / "stderr", done.stderr)
        return {"return_code": done.returncode, "fluid": None, "structure_stderr": done.stderr,
                "received_matches": False,
                "expected_fail": bool(done.returncode != 0 and "required initial Displacement" in done.stderr)}
    commands = []
    for role in ("Structure", "Fluid"):
        missing_flag = "1" if missing and role == "Structure" else "0"
        cmd = f"python3 '{directory / 'role.py'}' {role} '{directory / 'precice-config.xml'}' '{directory / (role.lower()+'.json')}' {value} {missing_flag} > '{directory / (role.lower()+'.stdout')}' 2> '{directory / (role.lower()+'.stderr')}' & {role.lower()}_pid=$!"
        commands.append(cmd)
    commands += ["wait $structure_pid; sr=$?", "wait $fluid_pid; fr=$?", "exit $((sr || fr))"]
    launcher = directory / "launch.sh"; put(launcher, "\n".join(commands) + "\n")
    try:
        done = subprocess.run(["bash", str(launcher)], text=True, capture_output=True, timeout=30, start_new_session=True)
    except subprocess.TimeoutExpired as exc:
        os.killpg(exc.pid, signal.SIGTERM)
        raise RuntimeError(f"{name} participant fixture timed out") from exc
    put(directory / "launcher.stdout", done.stdout); put(directory / "launcher.stderr", done.stderr)
    fluid = json.loads((directory / "fluid.json").read_text(encoding="utf-8")) if (directory / "fluid.json").is_file() else None
    structure_stderr = (directory / "structure.stderr").read_text(encoding="utf-8") if (directory / "structure.stderr").is_file() else ""
    return {"return_code": done.returncode, "fluid": fluid, "structure_stderr": structure_stderr,
            "received_matches": bool(fluid and abs(float(fluid["received_initial"][0][1]) - value) <= 1e-15),
            "expected_fail": bool(missing and done.returncode != 0 and "required initial Displacement" in structure_stderr)}


def main() -> int:
    if RUN.exists() or RESULTS.exists():
        raise RuntimeError("refusing to overwrite initial-data regression")
    RUN.mkdir(parents=True)
    path_cases = {
        "windows_drive": canonical_wsl_path(r"D:\work\socket"),
        "wsl_mount": canonical_wsl_path("/mnt/d/work/socket"),
        "linux_absolute": canonical_wsl_path("/home/machao/socket"),
        "invalid_empty": "FAIL" if _raises(lambda: canonical_wsl_path("")) else "UNEXPECTED_PASS",
        "missing_parent": socket_directory_preflight("/tmp/formal_implicit_missing_parent_zz/socket"),
        "unwritable_parent": socket_directory_preflight("/proc/precice.sock"),
    }
    zero = execute_case("zero", 0.0)
    nonzero = execute_case("nonzero", 0.002)
    missing = execute_case("missing", 0.0, missing=True)
    result = {"path_cases": path_cases, "zero_initial": zero, "nonzero_initial": nonzero, "missing_initial": missing,
              "INITIAL_DATA_PROTOCOL": "PASS" if zero["return_code"] == 0 and zero["received_matches"] and nonzero["return_code"] == 0 and nonzero["received_matches"] and missing["expected_fail"] else "FAIL",
              "SOCKET_PATH_CANONICALIZATION": "PASS" if path_cases["windows_drive"] == "/mnt/d/work/socket" and path_cases["wsl_mount"] == "/mnt/d/work/socket" and path_cases["linux_absolute"] == "/home/machao/socket" and path_cases["invalid_empty"] == "FAIL" and path_cases["missing_parent"]["status"] == "FAIL" and path_cases["unwritable_parent"]["status"] == "FAIL" else "FAIL"}
    RESULTS.mkdir(parents=True); put(RESULTS / "initial_data_and_path_regression.json", json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("INITIAL_DATA_PROTOCOL", "SOCKET_PATH_CANONICALIZATION")}))
    return 0 if result["INITIAL_DATA_PROTOCOL"] == result["SOCKET_PATH_CANONICALIZATION"] == "PASS" else 1


def _raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
