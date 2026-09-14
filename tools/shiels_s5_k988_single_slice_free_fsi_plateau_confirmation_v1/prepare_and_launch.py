"""Prepare one 100.155--130.155 s plateau-confirmation continuation.

The module is intentionally an offline launcher wrapper around the already
qualified continuation participant.  It copies only the final accepted CFD
state, changes only OpenFOAM write frequency, and never starts a solver during
``prepare`` or ``preflight``.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_plateau_confirmation_v1_run_001"
RESULTS = ROOT / "results/shiels_s5_k988_single_slice_free_fsi_plateau_confirmation_v1_run_001"
PARENT_RUNTIME = ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_long_development_resume_v4_run_001"
PARENT_CASE = PARENT_RUNTIME / "precice_displacementLaplacian"
PARTICIPANT = ROOT / "tools/shiels_s5_k988_single_slice_free_fsi_long_development_resume_v4/sdof_precice_continuation_participant.py"
V4 = ROOT / "tools/shiels_s5_k988_single_slice_free_fsi_long_development_resume_v4/run_long_development_resume_v4.py"
START = 100.155
DT = 0.005
STEPS = 6000
END = 130.155
VERTEX_COUNT = 40
FINAL_PARENT_DIR = "100.154999999982"
ADAPTER_SHA256 = "c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17"
OF_PREFIX_WSL = "/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/owner_diagnostic_abi_build_001/openfoam10"
ADAPTER_LIB_WSL = "/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/adapter_owner_diagnostic_build_001/lib"
ENV_SCRIPT_WSL = "/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/tools/of10_owned_atomic_mesh_history_restore_prototype_v1/prototype_env.sh"


def load_v4():
    spec = importlib.util.spec_from_file_location("shiels_v4_launcher", V4)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load qualified v4 launcher")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def wsl(path: Path) -> str:
    raw = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + raw[0].lower() + raw[2:]


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Python versions before 3.10 do not expose ``newline`` on
    # Path.write_text; use an explicit text handle for deterministic LF files.
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_json(path: Path, obj):
    write(path, json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def parent_final_commit():
    path = PARENT_RUNTIME / "structure/events.jsonl"
    last = None
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            if e.get("event") == "window_commit":
                last = e
    if last is None or abs(float(last["physical_time_s"]) - START) > 1e-5:
        raise RuntimeError("parent final jointly accepted state is not 100.155 s")
    return last


def parent_force():
    files = list(PARENT_CASE.rglob("forces.dat"))
    if not files:
        raise RuntimeError("parent cylinderForces file is missing")
    best = None
    for line in files[0].read_text(encoding="utf-8", errors="replace").splitlines():
        nums = [float(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", line)]
        if len(nums) >= 7:
            d = abs(nums[0] - START)
            if best is None or d < best[0]:
                best = (d, nums)
    if best is None or best[0] > 1e-5:
        raise RuntimeError("no force row at the accepted 100.155 s boundary")
    nums = best[1]
    return {"time_s": nums[0], "pressure_x_N": nums[1], "pressure_y_N": nums[2], "viscous_x_N": nums[4], "viscous_y_N": nums[5], "total_x_N": nums[1] + nums[4], "total_y_N": nums[2] + nums[5]}


def source_hashes():
    names = ("U", "p", "phi", "Uf", "meshPhi", "pointDisplacement", "cellDisplacement", "polyMesh/points", "uniform/time")
    base = PARENT_CASE / FINAL_PARENT_DIR
    missing = [n for n in names if not (base / n).is_file()]
    if missing:
        raise RuntimeError(f"accepted 100.155 s fields missing: {missing}")
    return {n: sha256(base / n) for n in names}


def make_contract(commit, hashes, force):
    st = commit["accepted_state"]
    return {
        "schema_version": "shiels-s5-k988-single-slice-free-fsi-plateau-confirmation-v1",
        "execution_policy": "one controlled continuation only from jointly accepted 100.155 s to 130.155 s; no automatic extension or rerun",
        "physical_contract": {"Re": 100, "D_m": 1.0, "U_mps": 1.0, "rho_kgpm3": 1000.0, "nu_m2ps": 0.01, "span_m": 1.0, "m_star_shiels": 5.0, "k_star_shiels": 9.88, "b_star_shiels": 0.0, "M_kg": 2500.0, "K_Npm": 4940.0, "C_Nspm": 0.0, "equation": "M*y_ddot + K*y = Fy_total; transverse only; x=0", "force_definition": "total pressure plus viscous cylinder force over the 1 m computational span"},
        "restart": {"parent_runtime": str(PARENT_RUNTIME), "parent_status": "completed resume_v4; restart source is only its final jointly accepted 100.155 s state", "physical_time_s": START, "sdof_state": st, "previous_accepted_force_y_N": float(commit["force_y_total_N"]), "initial_interface_y_m": float(commit["final_input_y_m"]), "interface_structure_residual_m": abs(float(st["y_m"]) - float(commit["final_input_y_m"])), "prior_accepted_windows": 20010, "cumulative_fluid_work_J": float(commit["cumulative_fluid_work_J"]), "cumulative_energy_balance_defect_J": float(commit["cumulative_energy_balance_defect_J"]), "force_components_N": force, "naturally_persisted_fields": hashes, "counterfactual_Uf_used": False},
        "coupling": {"scheme": "parallel-implicit", "dt_s": DT, "start_of_time_s": START, "end_of_time_s": END, "accepted_window_limit": STEPS, "min_iterations": 2, "max_iterations": 8, "acceleration": "none", "displacement_abs_limit_m": 1e-8, "displacement_rel_limit": 1e-5, "force_abs_limit_N": 1e-3, "force_rel_limit": 1e-5, "time_layer_contract": "initial data equals accepted parent interface y(t0=100.155); each trial writes candidate y(t_n), reads Force(t_n), and restores only the same current-window checkpoint"},
        "output_policy": {"full_field_write_control": "adjustableRunTime", "full_field_write_interval_s": 0.1, "force_and_structure_sampling_dt_s": DT, "time_step_unchanged": True, "cylinderForces_write_interval_steps": 1},
        "legacy_containment": {"status": "LEGACY_SMALL_MOTION_CONTAINMENT_GATE_NOT_APPLICABLE_TO_LARGE_AMPLITUDE_SHIELS_VALIDATION", "historical_y_gate_m": 0.05, "historical_v_gate_mps": 0.5, "historical_first_crossings_s": {"y": 37.88, "v": 56.645}, "not_used_as_current_literature_pass_fail": True},
        "emergency_run_protection": {"enabled": False, "reason": "no new emergency threshold added; only existing numerical hard failures stop this run"},
        "numerical_hard_stops": ["NaN/Inf/FPE", "negative volume or mesh fatal", "preCICE non-convergence beyond 8 iterations", "solver fatal", "Co or global continuity hard failure", "clearly nonphysical runaway growth"],
        "frozen_binary": {"of_prefix_wsl": OF_PREFIX_WSL, "adapter_lib_wsl": ADAPTER_LIB_WSL, "adapter_sha256": ADAPTER_SHA256},
        "prohibited": ["150 s extension", "dt/mesh/PIMPLE change", "parameter tuning", "ANCF", "three-slice", "automatic rerun"],
    }


def control_dict(mod):
    # The qualified v4 helpers are parameterized through module globals.
    # Patch those globals before rendering so the new case ends at 130.155 s
    # and its preCICE horizon is exactly 6000 windows.
    mod.START = START
    mod.DT = DT
    mod.STEPS = STEPS
    mod.END = END
    text = mod.control_dict()
    # Replace only the top-level field-output control.  The cylinderForces
    # function-object must keep per-step sampling for the 0.005 s force
    # history, even though complete fields are written every 0.1 s.
    text = text.replace("writeControl timeStep; writeInterval 1;", "writeControl adjustableRunTime; writeInterval 0.1;", 1)
    return text


def precice_xml(mod, exchange):
    mod.START = START
    mod.DT = DT
    mod.STEPS = STEPS
    mod.END = END
    return mod.precice_xml(exchange)


def prepare():
    # A prior invocation may have failed during setup before writing the
    # contract/manifest (the known Path.write_text compatibility failure).
    # Remove only that empty, uncommitted setup so the single authorized run
    # can be prepared; any manifest or execution evidence remains immutable.
    if RUNTIME.exists() and not (RUNTIME / "manifest.json").exists() and not (RUNTIME / "returns.txt").exists():
        shutil.rmtree(RUNTIME)
    if RESULTS.exists() and not any(RESULTS.iterdir()):
        shutil.rmtree(RESULTS)
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("runtime/results already exist; retry and automatic rerun are forbidden")
    commit = parent_final_commit(); hashes = source_hashes(); force = parent_force()
    parent_case = PARENT_CASE / FINAL_PARENT_DIR
    case = RUNTIME / "precice_displacementLaplacian"
    RUNTIME.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    # Copy only restart-essential files, not the parent's 4+ GB full history.
    shutil.copytree(PARENT_CASE / "constant", case / "constant")
    shutil.copytree(PARENT_CASE / "system", case / "system")
    shutil.copytree(parent_case, case / FINAL_PARENT_DIR)
    mod = load_v4()
    write(case / "system/controlDict", control_dict(mod))
    exchange = RUNTIME / "precice-sockets"; exchange.mkdir(parents=True)
    write(case / "precice-config.xml", precice_xml(mod, exchange))
    contract = make_contract(commit, hashes, force)
    write_json(RUNTIME / "contract.json", contract)
    write_json(RUNTIME / "manifest.json", {"schema_version": "shiels-s5-k988-single-slice-free-fsi-plateau-confirmation-v1", "case": str(case), "participant": str(PARTICIPANT), "participant_sha256": sha256(PARTICIPANT), "contract_sha256": sha256(RUNTIME / "contract.json"), "parent_runtime": str(PARENT_RUNTIME), "parent_final_time_directory": FINAL_PARENT_DIR, "parent_final_commit_time_s": START, "parent_final_commit_event": commit, "parent_field_hashes": hashes, "restart_force": force, "only_changed_numeric_setting": "OpenFOAM full-field write frequency: adjustableRunTime 0.1 s; solver deltaT remains 0.005 s"})
    print(json.dumps({"status": "PREPARED", "runtime": str(RUNTIME), "parent_time": START, "end_time": END, "steps": STEPS, "full_field_write_interval_s": 0.1}, ensure_ascii=False))


def preflight():
    if not (RUNTIME / "manifest.json").is_file():
        raise RuntimeError("prepare must complete first")
    mod = load_v4()
    # abi_preflight() writes its diagnostic script under mod.RUNTIME; point it
    # at this independent runtime so no historical runtime is touched.
    mod.RUNTIME = RUNTIME
    mod.RESULTS = RESULTS
    mod.START = START
    mod.DT = DT
    mod.STEPS = STEPS
    mod.END = END
    mod.PARTICIPANT = PARTICIPANT
    unit_path = RESULTS / "continuation_wrapper_unit.json"
    RESULTS.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(["python", str(PARTICIPANT), "--self-test", "--output", str(unit_path)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    unit = json.loads(unit_path.read_text(encoding="utf-8")) if unit_path.is_file() and done.returncode == 0 else {}
    abi = mod.abi_preflight()
    hashes = source_hashes()
    copied = all(sha256((RUNTIME / "precice_displacementLaplacian" / FINAL_PARENT_DIR / n)) == h for n, h in hashes.items())
    outcome = {"status": "PASS" if unit.get("status") == "PASS" and abi.get("status") == "PASS" and copied else "FAIL_CLOSED", "continuation_wrapper_unit": unit, "unit_stdout": done.stdout, "unit_stderr": done.stderr, "abi": abi, "copied_final_field_identity": copied, "parent_final_time_s": START, "output_policy_check": {"controlDict_contains_adjustableRunTime": "writeControl adjustableRunTime; writeInterval 0.1;" in (RUNTIME / "precice_displacementLaplacian/system/controlDict").read_text(encoding="utf-8")}}
    write_json(RUNTIME / "preflight.json", outcome)
    if outcome["status"] != "PASS":
        raise RuntimeError("plateau continuation preflight failed; launch forbidden")
    print(json.dumps({"status": "PREFLIGHT_PASS", "runtime": str(RUNTIME), "abi": abi.get("status"), "field_identity": copied}, ensure_ascii=False))


def launch_script():
    mod = load_v4(); mod.RUNTIME = RUNTIME; mod.RESULTS = RESULTS; mod.START = START; mod.DT = DT; mod.STEPS = STEPS; mod.END = END; mod.PARTICIPANT = PARTICIPANT
    # The qualified launcher only resolves its paths/constants through globals.
    return mod.launcher()


def launch_detached():
    if not json.loads((RUNTIME / "preflight.json").read_text(encoding="utf-8")).get("status") == "PASS":
        raise RuntimeError("preflight is not PASS")
    if (RUNTIME / "returns.txt").exists() or (RUNTIME / "launcher_return.json").exists():
        raise RuntimeError("execution evidence already exists; rerun forbidden")
    write(RUNTIME / "launch.sh", launch_script())
    # Run under a separate Windows process.  The user can leave Codex after the
    # process-survival check; this is not a service and does not auto-retry.
    command = ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(RUNTIME / "launch.sh")]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    proc = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    write_json(RUNTIME / "launcher_process.json", {"pid": proc.pid, "detached": True, "command": command})
    print(json.dumps({"status": "LAUNCHED_DETACHED", "pid": proc.pid, "runtime": str(RUNTIME)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("prepare", "preflight", "launch_detached")); args = parser.parse_args()
    {"prepare": prepare, "preflight": preflight, "launch_detached": launch_detached}[args.command]()


if __name__ == "__main__":
    main()
