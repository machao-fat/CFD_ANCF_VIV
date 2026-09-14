"""Prepare and launch one bounded continuation from the last persisted field.

The 130.155 s accepted state of the plateau run was not written as a complete
OpenFOAM time directory.  This independent continuation therefore starts at
the last complete, accepted field (130.1 s) and runs exactly 20 s to 150.1 s.
The earlier plateau runtime is read-only and is never overwritten.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_resume_130p1_to_150p1_v1_run_001"
RESULTS = ROOT / "results/shiels_s5_k988_single_slice_free_fsi_resume_130p1_to_150p1_v1_run_001"
PARENT_RUNTIME = ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_plateau_confirmation_v1_run_001"
PARENT_CASE = PARENT_RUNTIME / "precice_displacementLaplacian"
PARENT_TIME_DIR = "130.09999999995478"
PARTICIPANT = ROOT / "tools/shiels_s5_k988_single_slice_free_fsi_long_development_resume_v4/sdof_precice_continuation_participant.py"
V4 = ROOT / "tools/shiels_s5_k988_single_slice_free_fsi_long_development_resume_v4/run_long_development_resume_v4.py"
START = 130.1
DT = 0.005
STEPS = 4000
END = 150.1
VERTEX_COUNT = 40
ADAPTER_SHA256 = "c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17"
OF_PREFIX_WSL = "/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/owner_diagnostic_abi_build_001/openfoam10"
ADAPTER_LIB_WSL = "/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/adapter_owner_diagnostic_build_001/lib"
ENV_SCRIPT_WSL = "/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/tools/of10_owned_atomic_mesh_history_restore_prototype_v1/prototype_env.sh"


def load_v4():
    spec = importlib.util.spec_from_file_location("qualified_v4_launcher", V4)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load qualified continuation launcher")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wsl(path: Path) -> str:
    raw = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + raw[0].lower() + raw[2:]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def write_json(path: Path, payload) -> None:
    write(path, json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def parent_commit() -> dict:
    events = PARENT_RUNTIME / "structure/events.jsonl"
    found = None
    with events.open("r", encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            if event.get("event") == "window_commit" and abs(float(event.get("physical_time_s", -1.0)) - START) < 1.0e-8:
                found = event
    if found is None:
        raise RuntimeError("no accepted parent event at persisted 130.1 s")
    return found


def parent_force() -> dict[str, float]:
    files = list(PARENT_CASE.rglob("forces.dat"))
    if not files:
        raise RuntimeError("parent cylinderForces forces.dat is missing")
    best = None
    for line in files[0].read_text(encoding="utf-8", errors="replace").splitlines():
        nums = [float(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", line)]
        if len(nums) >= 7:
            candidate = (abs(nums[0] - START), nums)
            if best is None or candidate[0] < best[0]:
                best = candidate
    if best is None or best[0] > 1.0e-5:
        raise RuntimeError("no parent force row at 130.1 s")
    nums = best[1]
    return {"time_s": nums[0], "pressure_x_N": nums[1], "pressure_y_N": nums[2],
            "viscous_x_N": nums[4], "viscous_y_N": nums[5],
            "total_x_N": nums[1] + nums[4], "total_y_N": nums[2] + nums[5]}


def field_names() -> tuple[str, ...]:
    return ("U", "p", "phi", "Uf", "meshPhi", "pointDisplacement", "cellDisplacement",
            "polyMesh/points", "uniform/time")


def source_hashes() -> dict[str, str]:
    base = PARENT_CASE / PARENT_TIME_DIR
    missing = [name for name in field_names() if not (base / name).is_file()]
    if missing:
        raise RuntimeError(f"persisted 130.1 s fields missing: {missing}")
    return {name: sha256(base / name) for name in field_names()}


def configure_v4():
    module = load_v4()
    module.START = START
    module.DT = DT
    module.STEPS = STEPS
    module.END = END
    return module


def control_dict() -> str:
    module = configure_v4()
    text = module.control_dict()
    # Keep per-step force sampling; change only complete-field output cadence.
    return text.replace("writeControl timeStep; writeInterval 1;", "writeControl adjustableRunTime; writeInterval 0.1;", 1)


def precice_xml(exchange: Path) -> str:
    return configure_v4().precice_xml(exchange)


def make_contract(commit: dict, hashes: dict[str, str], force: dict[str, float]) -> dict:
    state = commit["accepted_state"]
    return {
        "schema_version": "shiels-s5-k988-single-slice-free-fsi-resume-130p1-to-150p1-v1",
        "execution_policy": "one controlled continuation from the last complete accepted 130.1 s field to 150.1 s; no automatic rerun or extension",
        "restart": {
            "parent_runtime": str(PARENT_RUNTIME),
            "parent_time_directory": PARENT_TIME_DIR,
            "parent_commit_time_s": START,
            "parent_commit_window_index": commit["window_index"],
            "restart_gap_from_unpersisted_parent_accept_s": 0.055,
            "physical_time_s": START,
            "sdof_state": state,
            "previous_accepted_force_y_N": float(commit["force_y_total_N"]),
            "initial_interface_y_m": float(commit["final_input_y_m"]),
            "interface_structure_residual_m": abs(float(state["y_m"]) - float(commit["final_input_y_m"])),
            "prior_accepted_windows": 20010 + int(commit["window_index"]),
            "cumulative_fluid_work_J": float(commit["cumulative_fluid_work_J"]),
            "cumulative_energy_balance_defect_J": float(commit["cumulative_energy_balance_defect_J"]),
            "force_components_N": force,
            "naturally_persisted_fields": hashes,
            "counterfactual_Uf_used": False,
        },
        "physical_contract": {
            "Re": 100, "D_m": 1.0, "U_mps": 1.0, "rho_kgpm3": 1000.0,
            "nu_m2ps": 0.01, "span_m": 1.0, "m_star_shiels": 5.0,
            "k_star_shiels": 9.88, "b_star_shiels": 0.0,
            "M_kg": 2500.0, "K_Npm": 4940.0, "C_Nspm": 0.0,
            "equation": "M*y_ddot + K*y = Fy_total; transverse only; x=0",
            "force_definition": "total pressure plus viscous cylinder force over the 1 m computational span",
        },
        "coupling": {
            "scheme": "parallel-implicit", "dt_s": DT, "start_of_time_s": START,
            "end_of_time_s": END, "accepted_window_limit": STEPS,
            "min_iterations": 2, "max_iterations": 8, "acceleration": "none",
            "displacement_abs_limit_m": 1e-8, "displacement_rel_limit": 1e-5,
            "force_abs_limit_N": 1e-3, "force_rel_limit": 1e-5,
            "time_layer_contract": "initial data equals the persisted accepted 130.1 s interface; each trial writes y(t_n), reads Force(t_n), and restores only the same current-window SDOF checkpoint",
        },
        "output_policy": {
            "full_field_write_control": "adjustableRunTime", "full_field_write_interval_s": 0.1,
            "force_and_structure_sampling_dt_s": DT, "cylinderForces_write_interval_steps": 1,
            "time_step_unchanged": True,
        },
        "legacy_containment": {
            "status": "LEGACY_SMALL_MOTION_CONTAINMENT_GATE_NOT_APPLICABLE_TO_LARGE_AMPLITUDE_SHIELS_VALIDATION",
            "historical_y_gate_m": 0.05, "historical_v_gate_mps": 0.5,
            "historical_first_crossings_s": {"y": 37.88, "v": 56.645},
            "not_used_as_current_literature_pass_fail": True,
        },
        "numerical_hard_stops": ["NaN/Inf/FPE", "negative volume or mesh fatal",
                                  "preCICE non-convergence beyond 8 iterations", "solver fatal",
                                  "Co or global continuity hard failure", "clearly nonphysical runaway growth"],
        "frozen_binary": {"of_prefix_wsl": OF_PREFIX_WSL, "adapter_lib_wsl": ADAPTER_LIB_WSL,
                           "adapter_sha256": ADAPTER_SHA256},
        "prohibited": ["automatic rerun", "150.1 s extension", "dt/mesh/PIMPLE change",
                       "parameter tuning", "ANCF", "three-slice", "counterfactual Uf"],
    }


def prepare() -> None:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("new continuation runtime/results already exist; rerun forbidden")
    commit = parent_commit()
    hashes = source_hashes()
    force = parent_force()
    source_case = PARENT_CASE / PARENT_TIME_DIR
    case = RUNTIME / "precice_displacementLaplacian"
    shutil.copytree(PARENT_CASE / "constant", case / "constant")
    shutil.copytree(PARENT_CASE / "system", case / "system")
    shutil.copytree(source_case, case / PARENT_TIME_DIR)
    write(case / "system/controlDict", control_dict())
    exchange = RUNTIME / "precice-sockets"
    exchange.mkdir(parents=True, exist_ok=True)
    write(case / "precice-config.xml", precice_xml(exchange))
    RUNTIME.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    contract = make_contract(commit, hashes, force)
    write_json(RUNTIME / "contract.json", contract)
    write_json(RUNTIME / "manifest.json", {
        "schema_version": "shiels-s5-k988-single-slice-free-fsi-resume-130p1-to-150p1-v1",
        "case": str(case), "participant": str(PARTICIPANT), "participant_sha256": sha256(PARTICIPANT),
        "contract_sha256": sha256(RUNTIME / "contract.json"), "parent_runtime": str(PARENT_RUNTIME),
        "parent_time_directory": PARENT_TIME_DIR, "parent_commit_event": commit,
        "parent_field_hashes": hashes, "restart_force": force,
        "only_changed_setting": "new independent runtime starts from persisted 130.1 s; complete fields every 0.1 s",
    })
    print(json.dumps({"status": "PREPARED", "runtime": str(RUNTIME), "restart_time_s": START,
                      "end_time_s": END, "steps": STEPS}, ensure_ascii=False))


def preflight() -> None:
    if not (RUNTIME / "manifest.json").is_file():
        raise RuntimeError("prepare must complete first")
    module = configure_v4()
    module.RUNTIME = RUNTIME
    module.RESULTS = RESULTS
    module.PARTICIPANT = PARTICIPANT
    unit_path = RESULTS / "continuation_wrapper_unit.json"
    done = subprocess.run([sys.executable, str(PARTICIPANT), "--self-test", "--output", str(unit_path)],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    unit = json.loads(unit_path.read_text(encoding="utf-8")) if done.returncode == 0 and unit_path.is_file() else {}
    abi = module.abi_preflight()
    hashes = source_hashes()
    copied = all(sha256(RUNTIME / "precice_displacementLaplacian" / PARENT_TIME_DIR / name) == digest
                 for name, digest in hashes.items())
    control = (RUNTIME / "precice_displacementLaplacian/system/controlDict").read_text(encoding="utf-8")
    outcome = {"status": "PASS" if unit.get("status") == "PASS" and abi.get("status") == "PASS" and copied else "FAIL_CLOSED",
               "continuation_wrapper_unit": unit, "unit_stdout": done.stdout, "unit_stderr": done.stderr,
               "abi": abi, "copied_persisted_130p1_field_identity": copied,
               "output_policy": {"adjustableRunTime_0p1s": "writeControl adjustableRunTime; writeInterval 0.1;" in control},
               "restart_contract": {"start_s": START, "end_s": END, "steps": STEPS,
                                    "source_time_directory": PARENT_TIME_DIR}}
    write_json(RUNTIME / "preflight.json", outcome)
    if outcome["status"] != "PASS":
        raise RuntimeError("resume preflight failed; launch forbidden")
    print(json.dumps({"status": "PREFLIGHT_PASS", "runtime": str(RUNTIME), "abi": abi.get("status"),
                      "field_identity": copied}, ensure_ascii=False))


def launch_detached() -> None:
    preflight_path = RUNTIME / "preflight.json"
    if not preflight_path.is_file() or json.loads(preflight_path.read_text(encoding="utf-8")).get("status") != "PASS":
        raise RuntimeError("preflight is not PASS")
    if (RUNTIME / "returns.txt").exists() or (RUNTIME / "launcher_return.json").exists():
        raise RuntimeError("execution evidence exists; rerun forbidden")
    module = configure_v4()
    module.RUNTIME = RUNTIME
    module.RESULTS = RESULTS
    module.PARTICIPANT = PARTICIPANT
    write(RUNTIME / "launch.sh", module.launcher())
    command = ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(RUNTIME / "launch.sh")]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    write_json(RUNTIME / "launcher_process.json", {"pid": process.pid, "detached": True, "command": command,
                                                    "start_s": START, "end_s": END, "steps": STEPS})
    print(json.dumps({"status": "LAUNCHED_DETACHED", "pid": process.pid, "runtime": str(RUNTIME)}, ensure_ascii=False))


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"prepare", "preflight", "launch_detached"}:
        raise SystemExit("usage: prepare_and_launch.py {prepare|preflight|launch_detached}")
    {"prepare": prepare, "preflight": preflight, "launch_detached": launch_detached}[sys.argv[1]]()


if __name__ == "__main__":
    main()
