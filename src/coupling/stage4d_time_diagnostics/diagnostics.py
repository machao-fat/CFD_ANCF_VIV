"""Offline state, Newmark, force-replay and initialization diagnostics.

This module deliberately contains no OpenFOAM launcher, mesh utility or
setFields call.  The only external numerical run is the checked-in MATLAB
ANCF core through ``ancf_diagnostic_replay.m``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = PROJECT_ROOT / "results" / "07_stage4d_c_time_diagnostics"
COARSE_ROOT = PROJECT_ROOT / "results" / "06_stage4d_medium_run" / "stage4d_b_formal100_20260811T044351Z_7e8682bdbf"
FINE_ROOT = PROJECT_ROOT / "results" / "07_stage4d_c_convergence" / "stage4d_c_time_dt00125_nelem2_20260811T063528Z_b309b67168"
ANCF_ROOT = PROJECT_ROOT / "src" / "structure_ancf_matlab"
DIAGNOSTIC_ROOT = PROJECT_ROOT / "src" / "coupling" / "stage4d_time_diagnostics"
MATLAB_EXE = Path(r"D:\Matlab\bin\matlab.exe")
DT_VALUES = (0.0025, 0.00125, 0.000625, 0.0003125)
DURATION_S = 0.25
SCHEMA_VERSION = "0.2.1"
MANIFEST_HASH = "d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite(value: Any, path: str = "value") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _finite(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _finite(item, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} contains NaN/Inf")


def _responses(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    result = []
    for path in sorted((root / "matlab_worker" / "responses").glob("response_*.json")):
        payload = _read(path)
        result.append((path, payload))
    return result


def _action_map(root: Path) -> dict[str, list[tuple[Path, dict[str, Any]]]]:
    result: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for item in _responses(root):
        result.setdefault(str(item[1].get("action", "unknown")), []).append(item)
    return result


def _vector(payload: Mapping[str, Any], key: str) -> np.ndarray:
    return np.asarray(payload[key], dtype=float).reshape(-1)


def _max_abs(a: np.ndarray) -> tuple[float, int]:
    flat = np.abs(np.asarray(a, dtype=float).reshape(-1))
    index = int(np.argmax(flat)) if flat.size else -1
    return (float(flat[index]) if flat.size else 0.0, index)


def _state_semantics_for_run(root: Path, dt: float, steps: int) -> dict[str, Any]:
    actions = _action_map(root)
    initialize = [payload for _, payload in actions.get("initialize", [])]
    if len(initialize) != 1:
        raise RuntimeError(f"{root}: expected one initialize response")
    init = initialize[0]
    predicts = {int(payload["staged_step"]): payload for _, payload in actions.get("predict", []) if payload.get("status") == "complete"}
    corrects = {int(payload["staged_step"]): payload for _, payload in actions.get("correct", []) if payload.get("status") == "complete"}
    finalizes = {int(payload["step"]): payload for _, payload in actions.get("finalize_commit", []) if payload.get("status") == "complete"}
    staged_saves = {int(payload["staged_step"]): payload for _, payload in actions.get("save_checkpoint", []) if payload.get("status") == "complete" and int(payload.get("staged_step", -1)) >= 0}
    committed_get_states = {}
    for _, payload in actions.get("get_state", []):
        if payload.get("status") == "complete" and int(payload.get("staged_step", -1)) < 0 and int(payload.get("step", -2)) >= 0:
            committed_get_states.setdefault(int(payload["step"]), payload)

    timestamp_rows = []
    qv_residuals = []
    qa_residuals = []
    checkpoint_errors = []
    duplicate_command_ids = []
    command_ids = []
    for _, payload in _responses(root):
        command_id = payload.get("command_id")
        if command_id in command_ids:
            duplicate_command_ids.append(command_id)
        command_ids.append(command_id)

    previous = init
    if float(init.get("time_s", math.nan)) != 0.0 or int(init.get("global_step", -99)) != -1:
        raise RuntimeError(f"{root}: invalid initialize time/step")
    for step in range(steps):
        target = (step + 1) * dt
        p = predicts.get(step); c = corrects.get(step); f = finalizes.get(step); s = staged_saves.get(step)
        if not all((p, c, f, s)):
            raise RuntimeError(f"{root}: missing staged response at step {step}")
        for label, payload in (("predict", p), ("correct", c)):
            timestamp_rows.append({"step": step, "action": label, "response_step": payload.get("step"), "global_step": payload.get("global_step"), "time_s": payload.get("time_s"), "staged_step": payload.get("staged_step"), "staged_time_s": payload.get("staged_time_s"), "expected_target_time_s": target, "time_error_s": abs(float(payload["time_s"]) - target)})
            if int(payload.get("step", -99)) != step - 1 or int(payload.get("global_step", -99)) != step - 1 or int(payload.get("staged_step", -99)) != step:
                raise RuntimeError(f"{root}: {label} state labels invalid at step {step}")
        if int(f.get("step", -99)) != step or int(f.get("global_step", -99)) != step or int(f.get("staged_step", -99)) != -1:
            raise RuntimeError(f"{root}: finalize labels invalid at step {step}")
        if abs(float(f["time_s"]) - target) > 1.0e-12:
            raise RuntimeError(f"{root}: finalize time invalid at step {step}")
        if int(s.get("step", -99)) != step - 1 or int(s.get("global_step", -99)) != step - 1 or int(s.get("staged_step", -99)) != step:
            raise RuntimeError(f"{root}: staged checkpoint labels invalid at step {step}")
        q0 = _vector(previous, "q"); q1 = _vector(c, "q")
        qd0 = _vector(previous, "qdot"); qd1 = _vector(c, "qdot")
        qdd0 = _vector(previous, "qddot"); qdd1 = _vector(c, "qddot")
        qv = q1 - q0 - 0.5 * dt * (qd0 + qd1)
        qa = qd1 - qd0 - 0.5 * dt * (qdd0 + qdd1)
        qv_max, qv_index = _max_abs(qv); qa_max, qa_index = _max_abs(qa)
        qv_residuals.append({"step": step, "max_abs_residual": qv_max, "dof_1based": qv_index + 1, "rms_residual": float(np.sqrt(np.mean(qv * qv)))})
        qa_residuals.append({"step": step, "max_abs_residual": qa_max, "dof_1based": qa_index + 1, "rms_residual": float(np.sqrt(np.mean(qa * qa)))})
        checkpoint_errors.append({"step": step, "save_checkpoint_vs_correct_q_max_abs": _max_abs(_vector(s, "q") - q1)[0], "finalize_vs_correct_q_max_abs": _max_abs(_vector(f, "q") - q1)[0], "finalize_vs_get_state_q_max_abs": _max_abs(_vector(f, "q") - _vector(committed_get_states.get(step, f, ), "q"))[0] if step in committed_get_states else None})
        previous = f

    _finite({"qv": qv_residuals, "qa": qa_residuals})
    return {
        "run_id": root.name,
        "dt_s": dt,
        "steps": steps,
        "action_counts": {key: len(value) for key, value in actions.items()},
        "state_semantics": {"initialize": {"step": init.get("step"), "global_step": init.get("global_step"), "time_s": init.get("time_s"), "staged_step": init.get("staged_step"), "staged_time_s": init.get("staged_time_s")}, "predict_and_correct_target": "staged_step=k, staged_time_s=(k+1)dt, state time_s=(k+1)dt", "finalize_committed": "step=global_step=k, staged_step=-1, time_s=(k+1)dt"},
        "timestamp_rows": timestamp_rows,
        "newmark_qv": {"max_abs_residual": max(row["max_abs_residual"] for row in qv_residuals), "rms_residual": float(np.sqrt(np.mean([row["rms_residual"] ** 2 for row in qv_residuals]))), "worst_step": max(qv_residuals, key=lambda row: row["max_abs_residual"])},
        "newmark_qa": {"max_abs_residual": max(row["max_abs_residual"] for row in qa_residuals), "rms_residual": float(np.sqrt(np.mean([row["rms_residual"] ** 2 for row in qa_residuals]))), "worst_step": max(qa_residuals, key=lambda row: row["max_abs_residual"])},
        "checkpoint_state_consistency": {"max_save_vs_correct_q_abs": max(row["save_checkpoint_vs_correct_q_max_abs"] for row in checkpoint_errors), "max_finalize_vs_correct_q_abs": max(row["finalize_vs_correct_q_max_abs"] for row in checkpoint_errors), "max_finalize_vs_get_state_q_abs": max((row["finalize_vs_get_state_q_max_abs"] or 0.0) for row in checkpoint_errors)},
        "duplicate_command_ids": duplicate_command_ids,
        "finite": True,
    }


def _summary(root: Path) -> dict[str, Any]:
    candidates = [root / "campaign_summary.json", root / "convergence_run_summary.json"]
    for path in candidates:
        if path.is_file():
            return _read(path).get("summary", _read(path))
    raise FileNotFoundError(root)


def prepare_force_input() -> dict[str, Any]:
    payload = _read(FINE_ROOT / "convergence_run_summary.json")
    summary = payload["summary"]
    rows = summary["step_results"]
    initial = np.asarray(summary["initial_force_audit"]["integrated_force_N"], dtype=float)
    times = [0.0] + [float(row["time_s"]) for row in rows]
    values = [initial.reshape(-1).tolist()] + [[float(row["integrated_slice_forces_N"][str(sid)][component]) for sid in range(3) for component in range(3)] for row in rows]
    result = {"schema_version": "stage4d-c-a-v2-force-input-1", "duration_s": DURATION_S, "dt_values_s": list(DT_VALUES), "source": {"run_id": payload["run_id"], "summary_path": str(FINE_ROOT / "convergence_run_summary.json"), "summary_sha256": _sha256(FINE_ROOT / "convergence_run_summary.json"), "manifest_sha256": summary["slice_manifest_sha256"], "config_sha256": summary["config_sha256"]}, "interpolation_rule": "piecewise_linear; original samples exact; t=0 explicitly uses initial integrated force; no filtering or smoothing", "force": {"times_s": times, "values_N": values, "initial_force_N": initial.tolist()}, "source_sample_count": len(rows), "target_source_hash": _sha256(FINE_ROOT / "convergence_run_summary.json")}
    _write(RESULTS_ROOT / "force_replay_input.json", result)
    return result


def _matlab_code(input_path: Path, output_path: Path) -> str:
    def quote(path: Path) -> str:
        return str(path).replace("\\", "/").replace("'", "''")
    return f"addpath('{quote(ANCF_ROOT)}'); addpath('{quote(DIAGNOSTIC_ROOT)}'); ancf_diagnostic_replay('{quote(input_path)}','{quote(output_path)}');"


def run_matlab_replay(input_path: Path, output_path: Path) -> dict[str, Any]:
    log_path = RESULTS_ROOT / "matlab_diagnostic_replay.log"
    result = subprocess.run([str(MATLAB_EXE), "-batch", _matlab_code(input_path, output_path)], capture_output=True, text=False, timeout=900)
    stdout = result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else str(result.stdout or "")
    stderr = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else str(result.stderr or "")
    log_path.write_text(stdout + stderr, encoding="utf-8")
    if result.returncode != 0 or not output_path.is_file():
        raise RuntimeError(f"MATLAB replay failed: {stderr[-2000:]}")
    replay = _read(output_path)
    _finite(replay)
    return replay


def _nrmse(reference: np.ndarray, candidate: np.ndarray, floor: float = 1.0e-12) -> float:
    a = np.asarray(reference, dtype=float); b = np.asarray(candidate, dtype=float)
    return float(np.sqrt(np.mean((a - b) ** 2)) / max(float(np.sqrt(np.mean(a * a))), floor))


def _align_replay(a: Mapping[str, Any], b: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    da = float(a["dt_s"]); db = float(b["dt_s"])
    if da < db:
        a, b = b, a; da, db = db, da
    ratio = da / db
    if abs(ratio - round(ratio)) > 1.0e-10:
        raise ValueError("Replay time steps are not integer-aligned")
    ratio_i = int(round(ratio))
    return dict(a), {"ratio": ratio_i, "fine": dict(b)}


def _pair_metrics(coarse: Mapping[str, Any], fine: Mapping[str, Any], phi: np.ndarray, M: np.ndarray, q_static: np.ndarray) -> dict[str, Any]:
    coarse_dt = float(coarse["dt_s"]); fine_dt = float(fine["dt_s"])
    ratio = int(round(coarse_dt / fine_dt))
    idx = np.arange(0, len(fine["time_s"]), ratio, dtype=int)
    if len(idx) != len(coarse["time_s"]):
        raise ValueError("Replay alignment count mismatch")
    q_c = np.asarray(coarse["q"], dtype=float); q_f = np.asarray(fine["q"], dtype=float)[idx]
    qd_c = np.asarray(coarse["qdot"], dtype=float); qd_f = np.asarray(fine["qdot"], dtype=float)[idx]
    qdd_c = np.asarray(coarse["qddot"], dtype=float); qdd_f = np.asarray(fine["qddot"], dtype=float)[idx]
    qstat = np.asarray(q_static, dtype=float).reshape(1, -1)
    dq_c = q_c - qstat; dq_f = q_f - qstat
    free = np.asarray(coarse["free_indices_1based"], dtype=int) - 1
    pos_idx = np.array([i for n in range(3) for i in (6*n, 6*n+1)], dtype=int)
    slope_idx = np.array([i for n in range(3) for i in (6*n+3, 6*n+4)], dtype=int)
    def motion_metric(key: str, components: tuple[int, ...]) -> dict[str, float]:
        c = np.asarray(coarse[key], dtype=float).reshape(-1, 3, 3)[:, :, list(components)]
        f = np.asarray(fine[key], dtype=float)[idx].reshape(-1, 3, 3)[:, :, list(components)]
        return {"nrmse": _nrmse(c, f), "rms_relative_change": abs(float(np.sqrt(np.mean(f*f))) - float(np.sqrt(np.mean(c*c)))) / max(float(np.sqrt(np.mean(c*c))), 1.0e-12), "peak_relative_change": abs(float(np.max(np.abs(f))) - float(np.max(np.abs(c)))) / max(float(np.max(np.abs(c))), 1.0e-12)}
    eta_c = dq_c @ M @ phi; eta_f = dq_f @ M @ phi
    etad_c = qd_c @ M @ phi; etad_f = qd_f @ M @ phi
    etadd_c = qdd_c @ M @ phi; etadd_f = qdd_f @ M @ phi
    dm = dq_c - dq_f
    mass_error = math.sqrt(max(0.0, float(np.sum(np.einsum("ti,ij,tj->t", dm, M, dm))))) / max(math.sqrt(max(0.0, float(np.sum(np.einsum("ti,ij,tj->t", dq_f, M, dq_f))))), 1.0e-12)
    modal = {"displacement_nrmse": _nrmse(eta_f, eta_c), "velocity_nrmse": _nrmse(etad_f, etad_c, 1.0e-10), "acceleration_nrmse": _nrmse(etadd_f, etadd_c, 1.0e-8), "amplitude_relative_change": abs(float(np.max(np.abs(eta_c))) - float(np.max(np.abs(eta_f)))) / max(float(np.max(np.abs(eta_f))), 1.0e-12), "rms_relative_change": abs(float(np.sqrt(np.mean(eta_c*eta_c))) - float(np.sqrt(np.mean(eta_f*eta_f)))) / max(float(np.sqrt(np.mean(eta_f*eta_f))), 1.0e-12)}
    return {"coarse_dt_s": coarse_dt, "fine_dt_s": fine_dt, "alignment_ratio": ratio, "q_dynamic_free_nrmse": _nrmse(dq_f[:, free], dq_c[:, free]), "q_dynamic_transverse_position_nrmse": _nrmse(dq_f[:, pos_idx], dq_c[:, pos_idx]), "q_dynamic_transverse_slope_nrmse": _nrmse(dq_f[:, slope_idx], dq_c[:, slope_idx]), "qdot_free_nrmse": _nrmse(qd_f[:, free], qd_c[:, free], 1.0e-10), "qddot_free_nrmse": _nrmse(qdd_f[:, free], qdd_c[:, free], 1.0e-8), "mass_weighted_eM": mass_error, "slice_displacement": motion_metric("motion_position", (0,1)), "slice_velocity": motion_metric("motion_velocity", (0,1)), "slice_acceleration": motion_metric("motion_acceleration", (0,1)), "modal": modal, "source_samples": len(coarse["time_s"])}


def _modal_projection(run: Mapping[str, Any], q_static: np.ndarray, M: np.ndarray, phi: np.ndarray) -> np.ndarray:
    q = np.asarray(run["q"], dtype=float) - np.asarray(q_static, dtype=float).reshape(1, -1)
    return q @ M @ phi


def _phase_metric(reference: Sequence[float], candidate: Sequence[float], dt: float, max_shift: int = 20) -> dict[str, Any]:
    ref = np.asarray(reference, dtype=float); cand = np.asarray(candidate, dtype=float)
    raw = _nrmse(ref, cand, 1.0e-12)
    options = []
    for shift in range(-max_shift, max_shift + 1):
        if shift >= 0:
            a = ref[shift:]; b = cand[:len(ref)-shift]
        else:
            a = ref[:len(ref)+shift]; b = cand[-shift:]
        if len(a) > 4:
            options.append((float(_nrmse(a,b,1.0e-12)), shift))
    best, shift = min(options)
    return {"raw_nrmse": raw, "best_shift_samples_diagnostic_only": shift, "best_shift_s": shift * dt, "best_shift_nrmse_diagnostic_only": best, "used_for_gate": False}


def dynamic_metric_reanalysis(replay: Mapping[str, Any], semantics: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    coarse_summary = _summary(COARSE_ROOT); fine_summary = _summary(FINE_ROOT)
    release_audit = replay["routes"]["release"]["dt_0_00125"]
    q_static = np.asarray(release_audit["q_static"], dtype=float)
    M = np.asarray(release_audit["mass_matrix"], dtype=float)
    phi = np.asarray(release_audit["modal_phi"], dtype=float)
    def arr(summary: Mapping[str, Any], key: str) -> np.ndarray:
        return np.asarray([row[key] for row in summary["step_results"]], dtype=float)
    c_q = arr(coarse_summary, "q"); f_q = arr(fine_summary, "q")[1::2]
    c_qd = arr(coarse_summary, "qdot"); f_qd = arr(fine_summary, "qdot")[1::2]
    c_qdd = arr(coarse_summary, "qddot"); f_qdd = arr(fine_summary, "qddot")[1::2]
    free = np.asarray(release_audit["free_indices_1based"], dtype=int)-1
    pos_idx = np.array([i for n in range(3) for i in (6*n,6*n+1)])
    slope_idx = np.array([i for n in range(3) for i in (6*n+3,6*n+4)])
    c_dq=c_q-q_static; f_dq=f_q-q_static
    c_eta=c_dq@M@phi; f_eta=f_dq@M@phi
    c_etad=c_qd@M@phi; f_etad=f_qd@M@phi
    c_etadd=c_qdd@M@phi; f_etadd=f_qdd@M@phi
    metrics = {"static_q_source": "worker initialize response / MATLAB ancf_initialize", "full_q_nrmse_not_used": _nrmse(f_q,c_q), "dynamic_free_q_nrmse": _nrmse(f_dq[:,free],c_dq[:,free]), "dynamic_transverse_position_nrmse": _nrmse(f_dq[:,pos_idx],c_dq[:,pos_idx]), "dynamic_transverse_slope_nrmse": _nrmse(f_dq[:,slope_idx],c_dq[:,slope_idx]), "dynamic_qdot_free_nrmse": _nrmse(f_qd[:,free],c_qd[:,free],1.0e-10), "dynamic_qddot_free_nrmse": _nrmse(f_qdd[:,free],c_qdd[:,free],1.0e-8), "mass_weighted_eM": math.sqrt(max(0.0,float(np.sum(np.einsum('ti,ij,tj->t',f_dq-c_dq,M,f_dq-c_dq)))))/max(math.sqrt(max(0.0,float(np.sum(np.einsum('ti,ij,tj->t',f_dq,M,f_dq))))),1.0e-12), "modal_displacement_nrmse": _nrmse(f_eta,c_eta), "modal_velocity_nrmse": _nrmse(f_etad,c_etad,1.0e-10), "modal_acceleration_nrmse": _nrmse(f_etadd,c_etadd,1.0e-8), "modal_amplitude_relative_change": abs(float(np.max(np.abs(c_eta)))-float(np.max(np.abs(f_eta))))/max(float(np.max(np.abs(f_eta))),1.0e-12), "modal_rms_relative_change": abs(float(np.sqrt(np.mean(c_eta*c_eta)))-float(np.sqrt(np.mean(f_eta*f_eta))))/max(float(np.sqrt(np.mean(f_eta*f_eta))),1.0e-12), "free_indices_1based": (free+1).tolist(), "modal_frequency_Hz": release_audit["modal_frequency_Hz"]}
    motions = {}
    # Use the stored corrected_motion fields explicitly; no temporal shift.
    for sid in range(3):
        c = coarse_summary["step_results"]; f = fine_summary["step_results"][1::2]
        def series(rows: Sequence[Mapping[str, Any]], key: str, field: str) -> np.ndarray:
            return np.asarray([row[key][str(sid)][field] for row in rows], dtype=float)
        motions[str(sid)] = {"displacement_xy_nrmse": _nrmse(np.column_stack([series(f,"corrected_motion","ux_m"),series(f,"corrected_motion","uy_m")]),np.column_stack([series(c,"corrected_motion","ux_m"),series(c,"corrected_motion","uy_m")])), "velocity_xy_nrmse": _nrmse(np.column_stack([series(f,"corrected_motion","vx_mps"),series(f,"corrected_motion","vy_mps")]),np.column_stack([series(c,"corrected_motion","vx_mps"),series(c,"corrected_motion","vy_mps")]),1.0e-10), "acceleration_xy_nrmse": _nrmse(np.column_stack([series(f,"corrected_motion","ax_mps2"),series(f,"corrected_motion","ay_mps2")]),np.column_stack([series(c,"corrected_motion","ax_mps2"),series(c,"corrected_motion","ay_mps2")]),1.0e-8)}
    metrics["slice_center_metrics"] = motions
    phase = {str(sid): _phase_metric([row["corrected_motion"][str(sid)]["uy_m"] for row in fine_summary["step_results"][1::2]], [row["corrected_motion"][str(sid)]["uy_m"] for row in coarse_summary["step_results"]], 0.0025) for sid in range(3)}
    return metrics, phase


def newmark_dispersion() -> dict[str, Any]:
    rows=[]
    for freq in (27.50934575579332,109.26854598696481):
        omega=2*math.pi*freq
        values=[]
        for dt in DT_VALUES:
            wt=2/dt*math.atan(omega*dt/2)
            n=int(round(DURATION_S/dt)); t=np.arange(n+1)*dt
            x=np.cos(omega*t); xn=np.cos(wt*t); v=-omega*np.sin(omega*t); vn=-omega*np.sin(wt*t); a=-omega**2*np.cos(omega*t); an=-omega**2*np.cos(wt*t)
            values.append({"dt_s":dt,"steps_per_period":1/(freq*dt),"numerical_frequency_Hz":wt/(2*math.pi),"frequency_ratio":wt/omega,"cumulative_phase_error_rad":(wt-omega)*DURATION_S,"cumulative_phase_error_cycles":(wt-omega)*DURATION_S/(2*math.pi),"displacement_nrmse":_nrmse(x,xn,1e-12),"velocity_nrmse":_nrmse(v,vn,1e-12),"acceleration_nrmse":_nrmse(a,an,1e-12)})
        for i in range(len(values)-1):
            for key in ("displacement_nrmse","velocity_nrmse","acceleration_nrmse"):
                values[i][f"{key}_observed_order_to_next"] = math.log(max(values[i][key],1e-300)/max(values[i+1][key],1e-300),2)
        rows.append({"frequency_Hz":freq,"omega_radps":omega,"formula":"w_tilde=(2/dt)*atan(w*dt/2)","time_steps":values})
    return {"duration_s":DURATION_S,"method":"Newmark average acceleration / trapezoidal analytical cross-check","frequencies":rows,"interpretation":"phase dispersion accumulates over 0.25 s; no time shift was used for Gate metrics"}


def replay_comparisons(replay: Mapping[str, Any], route: str) -> dict[str, Any]:
    route_data = replay["routes"][route]
    qstatic = np.asarray(route_data["dt_0_0003125"]["q_static"], dtype=float)
    M = np.asarray(route_data["dt_0_0003125"]["mass_matrix"], dtype=float)
    phi = np.asarray(route_data["dt_0_0003125"]["modal_phi"], dtype=float)
    pairs=[]
    for coarse_dt, fine_dt in zip(DT_VALUES[:-1], DT_VALUES[1:]):
        def field(dt: float) -> Mapping[str, Any]: return route_data["dt_"+str(dt).replace('.','_')]
        pairs.append(_pair_metrics(field(coarse_dt),field(fine_dt),phi,M,qstatic))
    recommendation=[]
    for pair in pairs:
        passed=pair["slice_displacement"]["nrmse"]<=.05 and pair["slice_velocity"]["nrmse"]<=.05 and pair["modal"]["velocity_nrmse"]<=.05 and pair["modal"]["acceleration_nrmse"]<=.10 and pair["slice_displacement"]["peak_relative_change"]<=.05 and pair["slice_velocity"]["rms_relative_change"]<=.05
        pair["diagnostic_recommendation_thresholds_passed"]=passed
        if passed: recommendation.append([pair["coarse_dt_s"],pair["fine_dt_s"]])
    return {"route":route,"pairs":pairs,"recommended_pair":recommendation[-1] if recommendation else None,"thresholds":{"displacement_nrmse":.05,"slice_velocity_nrmse":.05,"modal_velocity_nrmse":.05,"modal_acceleration_nrmse":.10,"displacement_peak":.05,"velocity_rms":.05}}


def initialization_comparison(replay: Mapping[str, Any]) -> dict[str, Any]:
    result={}
    for route in ("release","preload"):
        route_data=replay["routes"][route]
        base=route_data["dt_0_00125"]
        qstat=np.asarray(base["q_static"],dtype=float)
        static_motion=np.asarray(base["static_motion_position"],dtype=float).reshape(3,3)
        route_result={"static_q_norm":float(np.linalg.norm(qstat)),"static_motion_position_m":static_motion.tolist(),"static_diagnostics":base["static_diagnostics"],"initial_qdot_norm":float(np.linalg.norm(base["qdot_initial"])),"initial_qddot_norm":float(np.linalg.norm(base["qddot_initial"])),"dt":{}}
        for field,run in route_data.items():
            if not field.startswith("dt_"): continue
            motion=np.asarray(run["motion_position"],dtype=float).reshape(-1,3,3)
            y=motion[:,:,1]
            n=min(len(y),max(1,int(round(.05/float(run["dt_s"])))))
            t=np.asarray(run["time_s"],dtype=float)
            amp=[]
            for sid in range(3):
                sig=y[:n,sid]-static_motion[sid,1]
                X=np.column_stack([np.ones(n),np.cos(2*np.pi*27.50934598696481*t[:n]),np.sin(2*np.pi*27.50934598696481*t[:n])])
                coef=np.linalg.lstsq(X,sig,rcond=None)[0]
                amp.append(float(math.hypot(coef[1],coef[2])))
            route_result["dt"][field]={"startup_0_05s_28Hz_amplitude_m":amp,"max_dynamic_y_m":float(np.max(np.abs(y-static_motion[None,:,1]))),"mean_dynamic_y_m":float(np.mean(y-static_motion[None,:,1]))}
        result[route]=route_result
    result["interpretation"]="preload is an offline candidate only; no formal CFD mesh or persistent-worker coupling was modified"
    return result


def run_all() -> dict[str, Any]:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    force_input=prepare_force_input()
    replay_path=RESULTS_ROOT/"ancf_replay_raw.json"
    replay=run_matlab_replay(RESULTS_ROOT/"force_replay_input.json",replay_path)
    coarse_sem=_state_semantics_for_run(COARSE_ROOT,0.0025,100)
    fine_sem=_state_semantics_for_run(FINE_ROOT,0.00125,200)
    state_result={"schema_version":"stage4d-c-a-v2-state-semantics-1","protocol_version":SCHEMA_VERSION,"manifest_sha256":MANIFEST_HASH,"runs":{"coarse":coarse_sem,"fine":fine_sem},"raw_response_roots":{"coarse":str(COARSE_ROOT/"matlab_worker"/"responses"),"fine":str(FINE_ROOT/"matlab_worker"/"responses")},"time_label_error_found":False}
    dynamic,phase=dynamic_metric_reanalysis(replay, state_result)
    disp=newmark_dispersion()
    release=replay_comparisons(replay,"release"); preload=replay_comparisons(replay,"preload")
    init=initialization_comparison(replay)
    source={"run_id":force_input["source"]["run_id"],"source_summary_sha256":force_input["source"]["summary_sha256"],"source_manifest_sha256":force_input["source"]["manifest_sha256"],"source_config_sha256":force_input["source"]["config_sha256"],"sample_count":force_input["source_sample_count"],"interpolation_rule":force_input["interpolation_rule"],"original_samples_exact":True,"filtering":False,"smoothing":False}
    _write(RESULTS_ROOT/"state_semantics_audit.json",state_result)
    _write(RESULTS_ROOT/"dynamic_metric_reanalysis.json",dynamic)
    _write(RESULTS_ROOT/"phase_drift_audit.json",phase)
    _write(RESULTS_ROOT/"newmark_dispersion_audit.json",disp)
    _write(RESULTS_ROOT/"release_force_replay.json",release)
    _write(RESULTS_ROOT/"preload_force_replay.json",preload)
    _write(RESULTS_ROOT/"initialization_comparison.json",init)
    _write(RESULTS_ROOT/"force_replay_source_audit.json",source)
    recommendation={"recommended_release_real_dt_pair":release["recommended_pair"],"recommended_preload_real_dt_pair":preload["recommended_pair"],"thresholds":release["thresholds"],"time_shift_not_used_for_recommendation":True,"sol_choice_required":True}
    _write(RESULTS_ROOT/"real_dt_pair_recommendation.json",recommendation)
    candidate={"status":"completed","stage":"Stage 4D-C-A-v2","diagnostic_only":True,"new_real_openfoam_campaign":False,"openfoam_invoked":False,"checkMesh_invoked":False,"setFields_invoked":False,"state_semantics_passed":not state_result["time_label_error_found"],"newmark_dispersion_written":True,"release_replay_written":True,"preload_replay_written":True,"recommended_release_real_dt_pair":release["recommended_pair"],"recommended_preload_real_dt_pair":preload["recommended_pair"],"stage4d_c_a_gate_redecision":"not_performed","free_viv_claim":False,"sol_decision_required":True}
    _write(RESULTS_ROOT/"stage4d_c_a_v2_candidate_summary.json",candidate)
    return candidate


def main() -> int:
    run_all()
    print(json.dumps({"status":"completed","results_root":str(RESULTS_ROOT)},ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
