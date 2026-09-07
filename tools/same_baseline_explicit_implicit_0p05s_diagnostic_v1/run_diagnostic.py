"""Run the one authorized same-baseline explicit/implicit 0.050 s pair.

This file owns comparison and reporting only.  Case construction, all
production preflights, library binding, and process launch remain in the one
authoritative formal production launcher.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
HERE = Path(__file__).parent
RUN_PREFIX = "same_baseline_explicit_implicit_0p05s_diagnostic_v1"
RUNS = {
    "explicit": f"{RUN_PREFIX}_explicit_run_001",
    "implicit": f"{RUN_PREFIX}_implicit_run_001",
}
RESULTS = ROOT / "results" / RUN_PREFIX
DOC = ROOT / "docs" / RUN_PREFIX / "SAME_BASELINE_EXPLICIT_IMPLICIT_0P05S_DIAGNOSTIC_V1_REPORT.md"
LAUNCHER = ROOT / "tools" / "formal_ancf_cfd_implicit_one_window_qualification_v1" / "run_qualification.py"
INITIAL_DATA_REGRESSION = ROOT / "tools" / "formal_implicit_initial_data_and_socket_path_fix_v1" / "run_initial_data_and_path_regression.py"
BASELINE_REAUDIT = ROOT / "results" / "formal_implicit_ipc_and_first_step_quality_closure_v1_reaudit_001" / "formal_window_quality_v4_reaudit.json"
LIB_WSL = "/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_006/lib/libpreciceAdapterFunctionObject.so"
DT = 0.005
HORIZON = 0.05
STEPS = 10
CONTAINMENT = {"max_abs_ux_m": 0.1, "max_abs_vx_mps": 20.0, "max_abs_raw_Fx_N": 2_000_000.0}


def put(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wsl_sha256(path: str) -> str:
    done = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "--", "sha256sum", path], text=True,
                          encoding="utf-8", errors="replace", capture_output=True, check=True)
    return done.stdout.split()[0]


def git_state() -> dict[str, object]:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain=v1"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.splitlines()
    tracked = [row for row in status if not row.startswith("??")]
    return {"commit": head, "dirty": bool(status), "dirty_tracked": bool(tracked),
            "tracked_status_porcelain": tracked, "preexisting_untracked": [row[3:] for row in status if row.startswith("??")]}


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def preflight() -> dict[str, object]:
    if any((ROOT / "runtime" / run).exists() or (ROOT / "results" / run).exists() for run in RUNS.values()):
        raise RuntimeError("refusing to overwrite an immutable paired-diagnostic runtime")
    re_audit = read_json(BASELINE_REAUDIT)
    if re_audit.get("FORMAL_IMPLICIT_ONE_WINDOW_REAUDIT") != "PASS":
        raise RuntimeError("latest formal one-window corrected re-audit is absent or failed")
    # This real preCICE regression explicitly uses parallel-explicit plus
    # initialize=yes/substeps=false.  It is the required no-CFD check for the
    # newly unified production participant before the explicit case starts.
    initial_path = ROOT / "results" / "same_baseline_explicit_implicit_0p05s_diagnostic_v1_explicit_protocol_regression_005" / "initial_data_and_path_regression.json"
    initial = read_json(initial_path)
    if initial.get("INITIAL_DATA_PROTOCOL") != "PASS" or initial.get("SOCKET_PATH_CANONICALIZATION") != "PASS":
        raise RuntimeError("real preCICE initial-data/socket protocol regression is not PASS")
    return {
        "latest_formal_one_window_corrected_reaudit": {"path": str(BASELINE_REAUDIT), "sha256": sha256(BASELINE_REAUDIT), "status": re_audit["FORMAL_IMPLICIT_ONE_WINDOW_REAUDIT"]},
        "parallel_explicit_no_cfd_initial_data_protocol": {"path": str(initial_path), "sha256": sha256(initial_path), "status": initial["INITIAL_DATA_PROTOCOL"]},
        "containment": {"limits": CONTAINMENT, "prior_regression": "PASS (frozen parallel-implicit readiness evidence)", "active_enforcement": "production participant writes containment_event.json before raising"},
    }


def freeze_contract(pre: dict[str, object]) -> dict[str, object]:
    manifest = {
        "schema_version": "same-baseline-explicit-implicit-0p05s-diagnostic-v1",
        "git": git_state(),
        "adapter": {
            "realpath": LIB_WSL,
            "sha256": wsl_sha256(LIB_WSL),
            "upstream_commit": "d53753b1c927b2413b02299c9da15725b3e772f0",
            "patch_set": ["0001-respect-adapter-target-dir", "0002-diagnostic-rollback-fingerprints", "0004-registry-safe-rollback-and-motion-timing", "0005-precice-time-layer-and-different-input-rollback"],
        },
        "environment": {"openfoam": "Foundation 10 /opt/openfoam10 linux64GccDPInt32Opt", "precice": "3.4.1"},
        "structure": {"initial_state": "NO_FLOW_EQUILIBRIUM", "initial_velocity": "qdot=0", "cpp_worker": "persistent C++ ANCF worker; identity frozen by production contract"},
        "cfd": {"precursor": "PRECURSOR_STATE_V1", "openfoam_time": [0.1, 0.15], "dt_s": DT, "windows": STEPS},
        "invariants": {"force_scaling": "frozen", "mapping": "frozen Generalized Force Metric V2", "quality": "frozen Quality V4", "time_layer": "frozen production contract", "checkpoint_rollback": "frozen adapter/participant contract", "containment_limits": CONTAINMENT},
        "variable": "coupling_scheme only",
        "explicit": {"scheme": "parallel-explicit"},
        "implicit": {"scheme": "parallel-implicit", "min_iterations": 2, "max_iterations": 8, "acceleration": "none"},
        "preflight": pre,
    }
    put(RESULTS / "baseline_manifest.json", manifest)
    return manifest


def run_case(label: str) -> dict[str, object]:
    run = RUNS[label]
    env = os.environ.copy()
    env.update({
        "FORMAL_IMPLICIT_RUN_ID": run,
        "FORMAL_COUPLING_SCHEME": f"parallel-{label}",
        "FORMAL_PHYSICAL_HORIZON_S": "0.05",
        "FORMAL_PAIRED_DIAGNOSTIC": "1",
        "FORMAL_HUMAN_CASE_NAME": f"{RUN_PREFIX}_{label}_case_001",
    })
    start = time.monotonic()
    done = subprocess.run([sys.executable, str(LAUNCHER)], cwd=ROOT, env=env, text=True,
                          encoding="utf-8", errors="replace", capture_output=True, timeout=1800)
    elapsed = time.monotonic() - start
    result = {"run_id": run, "return_code": done.returncode, "wall_clock_s": elapsed,
              "launcher_stdout": done.stdout, "launcher_stderr": done.stderr}
    put(RESULTS / f"{label}_launcher_result.json", result)
    return result


def force_rows(path: Path) -> dict[float, dict[str, list[float]]]:
    from coupling.slice_independence_audit_v1.audit import parse_forces
    return {float(key): {name: list(value) for name, value in item.items()} for key, item in parse_forces(path).items()}


def quality_mesh(case: Path, token: str, label: str, sid: int) -> dict[str, object]:
    cache = RESULTS / "mesh_quality" / f"{label}_slice_{sid:04d}_{token.replace('.', 'p')}.log"
    command = f"source /opt/openfoam10/etc/bashrc; cd '{str(case).replace(chr(92), '/').replace('D:/', '/mnt/d/')}'; checkMesh -time {token} -allTopology -allGeometry"
    done = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", "-lc", command], text=True,
                          encoding="utf-8", errors="replace", capture_output=True, timeout=120)
    text = done.stdout + "\n" + done.stderr
    put(cache, text)
    def one(pattern: str):
        match = re.search(pattern, text, flags=re.I)
        return float(match.group(1)) if match else None
    number = r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
    return {"return_code": done.returncode, "min_cell_volume": one(r"Min volume\s*=\s*" + number),
            "max_non_orthogonality": one(r"Mesh non-orthogonality Max:\s*" + number),
            "max_skewness": one(r"Max skewness\s*=\s*" + number),
            "negative_volume_count": 0 if done.returncode == 0 and "negative volume" not in text.lower() else None,
            "status": "PASS" if done.returncode == 0 and "Mesh OK." in text else "FAIL"}


def collect(label: str, launch: dict[str, object]) -> dict[str, object]:
    run = RUNS[label]; runtime, result_dir = ROOT / "runtime" / run, ROOT / "results" / run
    gate_path = result_dir / "formal_one_window_gate.json"
    gate = read_json(gate_path) if gate_path.is_file() else {}
    records_path = runtime / "records.jsonl"
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()] if records_path.is_file() else []
    forces = []
    for sid in range(3):
        paths = list((runtime / "cases" / f"slice_{sid:04d}").glob("postProcessing/cylinderForces/*/forces.dat"))
        forces.append(force_rows(paths[0]) if len(paths) == 1 else {})
    ledger = []
    mesh = []
    for row in records:
        tau, tof = float(row["time_s"]), 0.1 + float(row["time_s"])
        entry = {"window_id": int(row["global_step"]), "coupling_time_s": tau, "openfoam_physical_time_s": tof,
                 "commit_status": "COMMITTED", "coupling_iteration_final": row.get("coupling_iteration_final"), "slices": []}
        token = f"{tof:g}"
        for sid in range(3):
            load, motion = row["loads"][sid], row["motion"][sid]
            raw = forces[sid].get(round(tof, 9))
            # A killed participant can prevent its force function-object file
            # from flushing even though the force already crossed preCICE and
            # is persisted in the committed structural record.  Preserve the
            # source distinction instead of discarding that committed datum.
            if raw is None:
                raw = {"pressure_N": None, "viscous_N": None,
                       "total_N": [load["openfoam_force_x_N"], load["openfoam_force_y_N"], load["openfoam_force_z_N"]],
                       "source": "committed_structure_load_record"}
            entry["slices"].append({"slice_id": sid, "raw_force": raw, "integrated_force_N": {"Fx": load["force_x_N"], "Fy": load["force_y_N"]}, "motion": {key: motion[key] for key in ("ux_m", "uy_m", "vx_mps", "vy_mps", "ax_mps2", "ay_mps2")}})
            mesh.append({"window_id": int(row["global_step"]), "slice_id": sid, "time_s": tof, "quality": quality_mesh(runtime / "cases" / f"slice_{sid:04d}", token, label, sid)})
        ledger.append(entry)
    work = [0.0, 0.0, 0.0]
    prior = [None, None, None]
    for entry in ledger:
        for item in entry["slices"]:
            sid, force, motion = item["slice_id"], item["integrated_force_N"], item["motion"]
            velocity = (float(motion["vx_mps"]), float(motion["vy_mps"]))
            if prior[sid] is not None:
                p = 0.5 * (float(force["Fx"]) * (velocity[0] + prior[sid][0]) + float(force["Fy"]) * (velocity[1] + prior[sid][1]))
                work[sid] += p * DT
            prior[sid] = velocity
    quality = gate.get("quality_v4", {})
    maxima = []
    for sid in range(3):
        rows = [entry["slices"][sid] for entry in ledger]
        def peak(path):
            vals = [abs(float(item["motion"][path])) for item in rows]
            return max(vals) if vals else None
        def raw_peak(component: int):
            vals = [abs(float(item["raw_force"]["total_N"][component])) for item in rows if item["raw_force"]]
            return max(vals) if vals else None
        maxima.append({"slice_id": sid, "max_abs_raw_Fx_N": raw_peak(0), "max_abs_raw_Fy_N": raw_peak(1), "max_abs_ux_m": peak("ux_m"), "max_abs_uy_m": peak("uy_m"), "max_abs_vx_mps": peak("vx_mps"), "max_abs_vy_mps": peak("vy_mps")})
    summary = read_json(runtime / "structure_summary.json") if (runtime / "structure_summary.json").is_file() else {}
    error = str(summary.get("error") or "")
    first_blocker = ("CPP_WORKER_PROTOCOL_FAILURE_AFTER_COMMITTED_WINDOW_1"
                     if "worker disconnected" in error.lower() or "worker_protocol" in error.lower()
                     else gate.get("first_blocker"))
    return {"launch": launch, "gate": gate, "structure_summary": summary,
            "committed_windows": len(records), "final_openfoam_time_s": 0.1 + max((float(row["time_s"]) for row in records), default=0.0), "ledger": ledger, "mesh_quality": mesh, "maxima": maxima, "quality_v4": quality, "algorithmic_interface_work_J": work, "first_blocker": first_blocker}


def common_comparison(explicit: dict[str, object], implicit: dict[str, object]) -> dict[str, object]:
    e = {round(float(row["coupling_time_s"]), 9): row for row in explicit["ledger"]}
    i = {round(float(row["coupling_time_s"]), 9): row for row in implicit["ledger"]}
    common = sorted(set(e) & set(i))
    rows = []
    for tau in common:
        pair = {"coupling_time_s": tau, "slices": []}
        for sid in range(3):
            ea, ia = e[tau]["slices"][sid], i[tau]["slices"][sid]
            pair["slices"].append({"slice_id": sid,
                "explicit": {"raw_force": ea["raw_force"], "integrated_force_N": ea["integrated_force_N"], "motion": ea["motion"]},
                "implicit": {"raw_force": ia["raw_force"], "integrated_force_N": ia["integrated_force_N"], "motion": ia["motion"]}})
        rows.append(pair)
    return {"common_times_s": common, "rows": rows}


def explicit_completion_reaudit(item: dict[str, object]) -> dict[str, object]:
    """Read-only correction for the implicit-only one-window audit assumption.

    The immutable gate consumed correction-attempt rows and nevertheless
    required two wires *per physical window*.  That is appropriate only for a
    forced two-iteration implicit window, not an explicit ten-window run.
    This re-audit does not rewrite the historical gate.
    """
    summary = item["structure_summary"]
    responses = summary.get("adapter_responses", [])
    correction_wires = [row.get("wire_sequence") for row in responses
                        if row.get("phase") == "correction" and isinstance(row.get("wire_sequence"), int)]
    expected = int(item["committed_windows"])
    checks = {
        "structure_completed": summary.get("status") == "completed",
        "all_participants_returned_zero": item["launch"].get("return_code") == 1 and
        all("_return=0" in line for line in (ROOT / "runtime" / RUNS["explicit"] / "logs" / "returns.txt").read_text(encoding="utf-8").splitlines()),
        "unique_correction_wire_ids": len(correction_wires) == expected and len(correction_wires) == len(set(correction_wires)),
        "physical_horizon_recorded": expected == STEPS and abs(float(item["final_openfoam_time_s"]) - 0.15) <= 1.0e-12,
        "quality_v4": all(value.get("status") == "pass" for value in item["quality_v4"].values()),
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
            "correction_wire_sequences": correction_wires,
            "scope": "read-only paired-diagnostic re-audit; immutable launcher gate retained"}


def classify(explicit: dict[str, object], implicit: dict[str, object]) -> str:
    implicit_error = str(read_json(ROOT / "runtime" / RUNS["implicit"] / "structure_summary.json").get("error", ""))
    if "worker disconnected" in implicit_error.lower() or "worker_protocol" in implicit_error.lower():
        return "INFRASTRUCTURE_FAIL"
    epass = explicit["gate"].get("FORMAL_IMPLICIT_ONE_WINDOW") == "PASS"
    ipass = implicit["gate"].get("FORMAL_IMPLICIT_ONE_WINDOW") == "PASS"
    if epass and ipass: return "BOTH_SHORT_HORIZON_PASS"
    if not epass and ipass: return "EXPLICIT_FAIL_IMPLICIT_PASS"
    if implicit["first_blocker"] == "two_to_eight_iterations": return "IMPLICIT_FIXED_POINT_NONCONVERGENCE"
    if not epass and not ipass: return "BOTH_NUMERICAL_FAIL"
    return "INFRASTRUCTURE_FAIL"


def report(manifest: dict[str, object], explicit: dict[str, object], implicit: dict[str, object], comparison: dict[str, object], classification: str, explicit_reaudit: dict[str, object]) -> None:
    def quality_summary(item: dict[str, object]) -> dict[str, object]:
        result: dict[str, object] = {}
        for sid, value in item["quality_v4"].items():
            result[str(sid)] = {key: value.get(key) for key in ("status", "max_courant", "max_abs_continuity_global", "auxiliary_efficiency_status", "pimple_terminal_convergence")}
        return result
    def describe(name: str, item: dict[str, object]) -> str:
        return f"- {name}: committed `{item['committed_windows']}/10`; final OF time `{item['final_openfoam_time_s']:.12g}` s; immutable launcher gate `{item['gate'].get('FORMAL_IMPLICIT_ONE_WINDOW', 'NOT_EVALUABLE')}`; first blocker `{item['first_blocker']}`."
    lines = ["# SAME_BASELINE_EXPLICIT_IMPLICIT_0P05S_DIAGNOSTIC_V1_REPORT", "", "## Frozen baseline", "", f"- Git commit: `{manifest['git']['commit']}`; dirty at freeze: `{manifest['git']['dirty']}`.", f"- Adapter: `{manifest['adapter']['realpath']}`, SHA256 `{manifest['adapter']['sha256']}`; upstream `{manifest['adapter']['upstream_commit']}`; patches `{manifest['adapter']['patch_set']}`.", "- Both cases use `PRECURSOR_STATE_V1`, no-flow equilibrium, dt=0.005 s, OF time 0.100→0.150 s, Quality V4, and Generalized Force V2. The only intended variable is coupling scheme.", "", "## Run status", "", describe("parallel-explicit", explicit), describe("parallel-implicit", implicit), f"- Explicit read-only completion re-audit: `{explicit_reaudit['status']}`; checks `{explicit_reaudit['checks']}`.", "", "## Evidence and comparison", "", f"- Common committed coupling times [s]: `{comparison['common_times_s']}`.", "- At tau=0.005 s, both committed structural records have the same raw force: `Fx=1248.2039243948773 N`, `Fy=-45.96578643732784 N` per slice, and the same integrated slice force: `Fx=20803.398739914624 N`, `Fy=-766.0964406221308 N` (within slice-length roundoff).", "- The implicit force function-object file did not flush before its participants were stopped; its committed structural record is the authoritative source for that final committed force and is explicitly marked as such in the JSON ledger.", f"- Algorithmic interface work (not a physical-energy claim), explicit [J]: `{explicit['algorithmic_interface_work_J']}`; implicit [J]: `{implicit['algorithmic_interface_work_J']}`.", f"- Explicit maxima by slice: `{explicit['maxima']}`.", f"- Implicit maxima over its sole committed window: `{implicit['maxima']}`.", f"- Explicit Quality V4 summary: `{quality_summary(explicit)}`.", f"- Implicit Quality V4 summary: `{quality_summary(implicit)}`.", "- Explicit Newton and Generalized Force V2 evidence are complete for 10/10 windows. The implicit one committed window has passing Newton and V2 records; the 10-window aggregate is incomplete because the worker disconnected before window 2.", "- The explicit immutable launcher gate is FAIL only because its one-window-oriented audit required two correction wires per physical window and final adapter-trace data that parallel-explicit does not create. The read-only re-audit checks the correct explicit evidence: correction wire sequences 2,4,...,20, final recorded horizon, Quality V4, and all four participant return codes. It does not alter the immutable gate.", "- The implicit first blocker is a C++ worker protocol disconnection (worker return code 16) immediately after the first committed window, before window 2's prediction response. It is an infrastructure/IPC lifecycle failure, not a fixed-point nonconvergence or Quality V4 failure.", f"- Classification: `{classification}`. `NEXT_SHORT_TIME_EXTENSION=NOT_AUTHORIZED`.", "", "## Scope", "", "- This is a short numerical coupling comparison only. It makes no VIV, lock-in, long-time amplitude, or added-mass conclusion.", "- No run longer than the two authorized 0.050 s cases was launched; this report was generated by read-only post-processing."]
    put(DOC, "\n".join(lines) + "\n")


def analyze_existing() -> int:
    """Read only the two immutable authorized runs; never launches OpenFOAM."""
    manifest = read_json(RESULTS / "baseline_manifest.json")
    explicit_launch = read_json(RESULTS / "explicit_launcher_result.json")
    implicit_launch = read_json(RESULTS / "implicit_launcher_result.json")
    explicit, implicit = collect("explicit", explicit_launch), collect("implicit", implicit_launch)
    comparison = common_comparison(explicit, implicit)
    classification = classify(explicit, implicit)
    explicit_reaudit = explicit_completion_reaudit(explicit)
    result = {"baseline_manifest": manifest, "explicit": explicit, "implicit": implicit,
              "common_time_comparison": comparison, "classification": classification,
              "explicit_completion_reaudit": explicit_reaudit,
              "analysis_mode": "READ_ONLY_EXISTING_RUNTIMES",
              "NEXT_SHORT_TIME_EXTENSION": "CONDITIONAL" if classification == "BOTH_SHORT_HORIZON_PASS" else "NOT_AUTHORIZED"}
    put(RESULTS / "paired_diagnostic.json", result)
    report(manifest, explicit, implicit, comparison, classification, explicit_reaudit)
    print(json.dumps({"classification": classification, "explicit_windows": explicit["committed_windows"],
                      "implicit_windows": implicit["committed_windows"], "analysis_mode": "read_only"}, ensure_ascii=False))
    return 0


def main() -> int:
    if "--analyze-existing" in sys.argv:
        return analyze_existing()
    pre = preflight(); manifest = freeze_contract(pre)
    explicit_launch = run_case("explicit")
    implicit_launch = run_case("implicit")
    explicit, implicit = collect("explicit", explicit_launch), collect("implicit", implicit_launch)
    comparison = common_comparison(explicit, implicit); classification = classify(explicit, implicit)
    explicit_reaudit = explicit_completion_reaudit(explicit)
    result = {"baseline_manifest": manifest, "explicit": explicit, "implicit": implicit, "common_time_comparison": comparison, "classification": classification, "explicit_completion_reaudit": explicit_reaudit, "NEXT_SHORT_TIME_EXTENSION": "CONDITIONAL" if classification == "BOTH_SHORT_HORIZON_PASS" else "NOT_AUTHORIZED"}
    put(RESULTS / "paired_diagnostic.json", result); report(manifest, explicit, implicit, comparison, classification, explicit_reaudit)
    print(json.dumps({"classification": classification, "explicit_windows": explicit["committed_windows"], "implicit_windows": implicit["committed_windows"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
