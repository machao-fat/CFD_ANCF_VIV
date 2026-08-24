"""Offline all-mode participation, bandwidth, and physical-scale audit.

The audit reads the existing nElem=2 release replay and uses one MATLAB
helper to rebuild the complete linearized modal basis from the same ANCF
static state, mass matrix, tangent, constraints, and H mapping.  It never
launches OpenFOAM, checkMesh, setFields, or a production coupling runner.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = PROJECT_ROOT / "results" / "07_stage4d_c_modal_bandwidth_audit_v3"
INPUT_ROOT = PROJECT_ROOT / "results" / "07_stage4d_c_time_diagnostics"
RAW_PATH = INPUT_ROOT / "ancf_replay_raw.json"
ANCF_ROOT = PROJECT_ROOT / "src" / "structure_ancf_matlab"
AUDIT_ROOT = PROJECT_ROOT / "src" / "coupling" / "stage4d_modal_bandwidth_audit"
MATLAB_EXE = Path(r"D:\Matlab\bin\matlab.exe")
MANIFEST_HASH = "d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3"
PROTOCOL_VERSION = "0.2.1"
DT_VALUES = (0.0025, 0.00125, 0.000625, 0.0003125, 0.00015625, 0.000078125)
DURATION_S = 0.25
SHEDDING = {
    "re80": {"U_mps": 0.8, "Re": 80.0, "frequency_Hz": 0.10733640842189707},
    "re100": {"U_mps": 1.0, "Re": 100.0, "frequency_Hz": 0.14149994022481596},
    "re120": {"U_mps": 1.2, "Re": 120.0, "frequency_Hz": 0.17832790498556134},
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite(value: Any, label: str = "value") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            finite(item, f"{label}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            finite(item, f"{label}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{label} contains NaN/Inf")


def arr(value: Any) -> np.ndarray:
    return np.asarray(value, dtype=float)


def nrmse(reference: np.ndarray, candidate: np.ndarray, floor: float = 1.0e-12) -> float:
    ref = np.asarray(reference, dtype=float)
    cand = np.asarray(candidate, dtype=float)
    return float(np.sqrt(np.mean((ref - cand) ** 2)) / max(float(np.sqrt(np.mean(ref * ref))), floor))


def rel_l2(reference: np.ndarray, candidate: np.ndarray, floor: float = 1.0e-30) -> float:
    ref = np.asarray(reference, dtype=float)
    cand = np.asarray(candidate, dtype=float)
    return float(np.linalg.norm(ref - cand) / max(float(np.linalg.norm(ref)), floor))


def _matlab_command(input_path: Path, output_path: Path) -> str:
    def quote(path: Path) -> str:
        return str(path).replace("\\", "/").replace("'", "''")

    return (
        f"addpath('{quote(ANCF_ROOT)}');"
        f"addpath('{quote(AUDIT_ROOT)}');"
        f"ancf_full_modal_system('{quote(input_path)}','{quote(output_path)}');"
    )


def build_modal_system() -> dict[str, Any]:
    input_path = RESULTS_ROOT / "modal_system_input.json"
    output_path = RESULTS_ROOT / "modal_system_from_matlab.json"
    write_json(input_path, {"schema_version": "stage4d-c-a-v3-modal-input-1", "dt_s": 0.00125, "nElem": 2})
    result = subprocess.run(
        [str(MATLAB_EXE), "-batch", _matlab_command(input_path, output_path)],
        capture_output=True,
        text=False,
        timeout=900,
    )
    stdout = result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else str(result.stdout or "")
    stderr = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else str(result.stderr or "")
    (RESULTS_ROOT / "matlab_modal_system.log").write_text(stdout + stderr, encoding="utf-8")
    if result.returncode != 0 or not output_path.is_file():
        raise RuntimeError(f"MATLAB modal system failed: {stderr[-2000:]}")
    data = read_json(output_path)
    finite(data, "modal_system")
    return data


def input_hash_audit() -> dict[str, Any]:
    paths = {
        "sol_review_json": INPUT_ROOT / "stage4d_c_a_v2_sol_review.json",
        "state_semantics_json": INPUT_ROOT / "state_semantics_audit.json",
        "dynamic_metrics_json": INPUT_ROOT / "dynamic_metric_reanalysis.json",
        "newmark_v2_json": INPUT_ROOT / "newmark_dispersion_audit.json",
        "release_replay_json": INPUT_ROOT / "release_force_replay.json",
        "preload_replay_json": INPUT_ROOT / "preload_force_replay.json",
        "raw_replay_json": RAW_PATH,
        "force_input_json": INPUT_ROOT / "force_replay_input.json",
        "force_source_audit_json": INPUT_ROOT / "force_replay_source_audit.json",
        "v3_developed_flow_bank": PROJECT_ROOT / "results" / "06_developed_flow_v3" / "developed_flow_bank_v3.json",
        "diagnostic_python": PROJECT_ROOT / "src" / "coupling" / "stage4d_time_diagnostics" / "diagnostics.py",
        "diagnostic_matlab": PROJECT_ROOT / "src" / "coupling" / "stage4d_time_diagnostics" / "ancf_diagnostic_replay.m",
    }
    entries = []
    for label, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(path)
        entries.append({"label": label, "sha256": sha256(path), "size_bytes": path.stat().st_size})
    source = read_json(paths["sol_review_json"])
    if source["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("Protocol mismatch")
    if source.get("free_viv_claim"):
        raise ValueError("Unexpected free-VIV claim in Sol review")
    canonical = {"protocol_version": PROTOCOL_VERSION, "manifest_sha256": MANIFEST_HASH, "inputs": [(x["label"], x["sha256"]) for x in entries]}
    identity = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    result = {
        "schema_version": "stage4d-c-a-v3-input-hash-audit-1",
        "protocol_version": PROTOCOL_VERSION,
        "manifest_sha256": MANIFEST_HASH,
        "identity_hash_excludes_absolute_paths": True,
        "source_inputs": entries,
        "identity_hash": identity,
        "raw_replay_route_used": "release",
        "preload_used_as_recommendation": False,
    }
    write_json(RESULTS_ROOT / "input_hash_audit.json", result)
    return result


def modal_system_audit(system: Mapping[str, Any], raw_release: Mapping[str, Any]) -> dict[str, Any]:
    if int(system.get("nElem", -1)) != 2:
        raise ValueError("This audit accepts only the nElem=2 release modal system")
    M = arr(system["mass_matrix"])
    K = arr(system["tangent_stiffness"])
    Mff = arr(system["mass_free"])
    Kff = arr(system["tangent_stiffness_free"])
    free = np.asarray(system["free_indices_1based"], dtype=int) - 1
    fixed = np.asarray(system["fixed_indices_1based"], dtype=int) - 1
    phi = arr(system["modal_phi_free"])
    phi_full = arr(system["modal_phi_full"])
    lam = arr(system["eigenvalues"]).reshape(-1)
    freq = arr(system["frequencies_Hz"]).reshape(-1)
    if phi.shape != (len(free), len(free)) or len(lam) != len(free):
        raise ValueError("Complete modal basis does not match free DOF count")
    morth = phi.T @ Mff @ phi - np.eye(len(free))
    kdiag = phi.T @ Kff @ phi - np.diag(lam)
    fixed_modal = phi_full[fixed, :]
    H = arr(system["mapping_H3"])
    dof_names = ("x_position", "y_position", "z_position", "x_slope", "y_slope", "z_slope")
    modes = []
    for j in range(len(freq)):
        column = phi_full[:, j]
        top = np.argsort(np.abs(column))[::-1][:4]
        slice_amplitude = np.linalg.norm((H @ column).reshape(3, 3), axis=1)
        modes.append({
            "mode_index_1based": j + 1,
            "eigenvalue": float(lam[j]),
            "frequency_Hz": float(freq[j]),
            "dominant_dofs_1based": [int(i + 1) for i in top],
            "dominant_dof_descriptions": [f"node_{int(i // 6) + 1}_{dof_names[int(i % 6)]}" for i in top],
            "dominant_dof_amplitudes": [float(abs(column[i])) for i in top],
            "slice_participation_norm_xyz": slice_amplitude.tolist(),
        })
    # The release replay was independently initialized by the same core.
    qstatic_ref = arr(raw_release["q_static"])
    result = {
        "schema_version": "stage4d-c-a-v3-modal-system-audit-1",
        "protocol_version": PROTOCOL_VERSION,
        "nElem": int(system["nElem"]),
        "ndof": int(system["ndof"]),
        "free_dof_count": int(len(free)),
        "mode_count": int(len(freq)),
        "all_free_modes_retained": bool(len(freq) == len(free)),
        "fixed_indices_1based": (fixed + 1).tolist(),
        "free_indices_1based": (free + 1).tolist(),
        "frequencies_Hz": freq.tolist(),
        "eigenvalues": lam.tolist(),
        "M_orthogonality_max_abs": float(np.max(np.abs(morth))),
        "M_orthogonality_frobenius": float(np.linalg.norm(morth)),
        "K_diagonalization_max_abs": float(np.max(np.abs(kdiag))),
        "K_diagonalization_frobenius": float(np.linalg.norm(kdiag)),
        "K_diagonal_relative_error": float(np.linalg.norm(kdiag) / max(np.linalg.norm(np.diag(lam)), 1.0e-30)),
        "fixed_modal_max_abs": float(np.max(np.abs(fixed_modal))),
        "mass_min_eigenvalue": float(np.min(np.linalg.eigvalsh(Mff))),
        "stiffness_min_eigenvalue": float(np.min(lam)),
        "q_static_source_relative_error": rel_l2(qstatic_ref, arr(system["q_static"])),
        "modes": modes,
        "mapping_shape": list(H.shape),
    }
    finite(result, "modal_system_audit")
    write_json(RESULTS_ROOT / "modal_system_audit.json", result)
    return result


def load_run(raw: Mapping[str, Any], dt: float, route: str = "release") -> dict[str, Any]:
    key = "dt_" + str(dt).replace(".", "_")
    return raw["routes"][route][key]


def run_arrays(run: Mapping[str, Any], system: Mapping[str, Any]) -> dict[str, Any]:
    Mff = arr(system["mass_free"])
    H = arr(system["mapping_H3"])
    free = np.asarray(system["free_indices_1based"], dtype=int) - 1
    phi = arr(system["modal_phi_free"])
    q = arr(run["q"])
    qd = arr(run["qdot"])
    qdd = arr(run["qddot"])
    qstatic = arr(run["q_static"])
    dq = q - qstatic.reshape(1, -1)
    eta = dq[:, free] @ Mff @ phi
    etad = qd[:, free] @ Mff @ phi
    etadd = qdd[:, free] @ Mff @ phi
    dq_recon_free = eta @ phi.T
    qd_recon_free = etad @ phi.T
    qdd_recon_free = etadd @ phi.T
    dq_recon = np.zeros_like(dq); dq_recon[:, free] = dq_recon_free
    qd_recon = np.zeros_like(qd); qd_recon[:, free] = qd_recon_free
    qdd_recon = np.zeros_like(qdd); qdd_recon[:, free] = qdd_recon_free
    force = arr(run["force_integrated_N"]).reshape(-1, 9)
    Q = force @ H
    P = Q[:, free] @ phi
    motion_q = q @ H.T
    motion_delta_q = dq @ H.T
    velocity_q = qd @ H.T
    acceleration_q = qdd @ H.T
    motion_raw = arr(run["motion_position"])
    velocity_raw = arr(run["motion_velocity"])
    acceleration_raw = arr(run["motion_acceleration"])
    # Per-mode slice velocity contribution, in protocol [slice xyz] order.
    phi_full = arr(system["modal_phi_full"])
    v_mode = np.stack([etad[:, j, None] * (H @ phi_full[:, j])[None, :] for j in range(phi.shape[1])], axis=1)
    v_xy_idx = np.array([0, 1, 3, 4, 6, 7], dtype=int)
    v_xy = velocity_q[:, v_xy_idx]
    v_mode_xy = v_mode[:, :, v_xy_idx]
    dt = float(run["dt_s"])
    power_direct = np.sum(force * velocity_raw, axis=1)
    power_H = np.sum(Q * qd, axis=1)
    power_modal = np.sum(P * etad, axis=1)
    work_mode = P * etad * dt
    T_mode = 0.5 * etad * etad
    V_mode = 0.5 * (arr(system["frequencies_Hz"]).reshape(1, -1) * 2.0 * math.pi) ** 2 * eta * eta
    return {
        "dt_s": dt,
        "time": arr(run["time_s"]).reshape(-1),
        "q": q,
        "qd": qd,
        "qdd": qdd,
        "qstatic": qstatic,
        "dq": dq,
        "dq_recon": dq_recon,
        "qd_recon": qd_recon,
        "qdd_recon": qdd_recon,
        "eta": eta,
        "etad": etad,
        "etadd": etadd,
        "force": force,
        "Q": Q,
        "P": P,
        "motion_q": motion_q,
        "motion_delta_q": motion_delta_q,
        "velocity_q": velocity_q,
        "acceleration_q": acceleration_q,
        "motion_raw": motion_raw,
        "velocity_raw": velocity_raw,
        "acceleration_raw": acceleration_raw,
        "v_mode_xy": v_mode_xy,
        "v_xy": v_xy,
        "power_direct": power_direct,
        "power_H": power_H,
        "power_modal": power_modal,
        "work_mode": work_mode,
        "T_mode": T_mode,
        "V_mode": V_mode,
    }


def reconstruction_audit(data: Mapping[str, Any]) -> dict[str, Any]:
    rows = {}
    for key, item in data.items():
        rows[key] = {
            "q_dynamic_relative_l2": rel_l2(item["dq"], item["dq_recon"]),
            "qdot_relative_l2": rel_l2(item["qd"], item["qd_recon"]),
            "qddot_relative_l2": rel_l2(item["qdd"], item["qdd_recon"]),
            "q_dynamic_max_abs": float(np.max(np.abs(item["dq"] - item["dq_recon"]))),
            "qdot_max_abs": float(np.max(np.abs(item["qd"] - item["qd_recon"]))),
            "qddot_max_abs": float(np.max(np.abs(item["qdd"] - item["qdd_recon"]))),
            "slice_position_H_reconstruction_relative_l2": rel_l2(item["motion_delta_q"], item["dq_recon"] @ arr(SYSTEM["mapping_H3"]).T),
            "slice_velocity_H_reconstruction_relative_l2": rel_l2(item["velocity_q"], item["qd_recon"] @ arr(SYSTEM["mapping_H3"]).T),
            "slice_acceleration_H_reconstruction_relative_l2": rel_l2(item["acceleration_q"], item["qdd_recon"] @ arr(SYSTEM["mapping_H3"]).T),
            "slice_position_raw_vs_H_relative_l2": rel_l2(item["motion_raw"], item["motion_q"]),
            "slice_velocity_raw_vs_H_relative_l2": rel_l2(item["velocity_raw"], item["velocity_q"]),
            "slice_acceleration_raw_vs_H_relative_l2": rel_l2(item["acceleration_raw"], item["acceleration_q"]),
            "fixed_dynamic_max_abs": float(np.max(np.abs(item["dq"][:, np.asarray(SYSTEM["fixed_indices_1based"], dtype=int) - 1]))),
        }
    result = {
        "schema_version": "stage4d-c-a-v3-full-reconstruction-1",
        "reconstruction_basis": "all nElem=2 free modes, mass normalized",
        "acceptance_threshold": 1.0e-9,
        "runs": rows,
        "all_pass": all(max(row[k] for row in rows.values()) <= 1.0e-9 for k in (
            "q_dynamic_relative_l2", "qdot_relative_l2", "qddot_relative_l2",
            "slice_velocity_H_reconstruction_relative_l2", "slice_acceleration_H_reconstruction_relative_l2")),
    }
    finite(result, "full_reconstruction")
    write_json(RESULTS_ROOT / "full_modal_reconstruction.json", result)
    return result


def mode_work_energy(item: Mapping[str, Any], system: Mapping[str, Any]) -> dict[str, Any]:
    freq = arr(system["frequencies_Hz"]).reshape(-1)
    eta = item["eta"]; etad = item["etad"]; etadd = item["etadd"]
    T = item["T_mode"]; V = item["V_mode"]; work = item["work_mode"]
    vmode = item["v_mode_xy"]
    kinetic_total = float(np.sum(T)); strain_total = float(np.sum(V)); work_abs_total = float(np.sum(np.abs(work)))
    total_xy_rms_sq = float(np.mean(item["v_xy"] * item["v_xy"]))
    modes = []
    for j, f in enumerate(freq):
        w = work[:, j]
        positive = float(np.sum(np.maximum(w, 0.0)))
        negative = float(np.sum(np.minimum(w, 0.0)))
        mode_rms = float(np.sqrt(np.mean(vmode[:, j, :] ** 2)))
        modes.append({
            "mode_index_1based": j + 1,
            "frequency_Hz": float(f),
            "eta_rms": float(np.sqrt(np.mean(eta[:, j] ** 2))),
            "eta_dot_rms": float(np.sqrt(np.mean(etad[:, j] ** 2))),
            "eta_ddot_rms": float(np.sqrt(np.mean(etadd[:, j] ** 2))),
            "max_abs_eta": float(np.max(np.abs(eta[:, j]))),
            "kinetic_energy_mean_J": float(np.mean(T[:, j])),
            "linearized_strain_energy_proxy_mean_J": float(np.mean(V[:, j])),
            "displacement_mass_fraction": float(np.sum(eta[:, j] ** 2) / max(np.sum(eta * eta), 1.0e-30)),
            "kinetic_energy_fraction": float(np.sum(T[:, j]) / max(kinetic_total, 1.0e-30)),
            "linearized_strain_energy_fraction": float(np.sum(V[:, j]) / max(strain_total, 1.0e-30)),
            "slice_velocity_rms_xy_mps": mode_rms,
            "slice_velocity_rms_squared_fraction": float(np.mean(vmode[:, j, :] ** 2) / max(total_xy_rms_sq, 1.0e-30)),
            "signed_work_J": float(np.sum(w)),
            "absolute_work_J": float(np.sum(np.abs(w))),
            "positive_work_J": positive,
            "negative_work_J": negative,
            "absolute_work_fraction": float(np.sum(np.abs(w)) / max(work_abs_total, 1.0e-30)),
        })
    direct_work = item["power_direct"] * item["dt_s"]
    H_work = item["power_H"] * item["dt_s"]
    modal_work = item["power_modal"] * item["dt_s"]
    result = {
        "dt_s": item["dt_s"],
        "steps": int(len(item["time"])),
        "modes": modes,
        "totals": {
            "mean_total_kinetic_energy_J": float(np.mean(T.sum(axis=1))),
            "mean_total_linearized_strain_energy_proxy_J": float(np.mean(V.sum(axis=1))),
            "signed_direct_Fv_work_J": float(np.sum(direct_work)),
            "absolute_direct_Fv_work_J": float(np.sum(np.abs(direct_work))),
            "positive_direct_Fv_work_J": float(np.sum(np.maximum(direct_work, 0.0))),
            "negative_direct_Fv_work_J": float(np.sum(np.minimum(direct_work, 0.0))),
            "signed_modal_work_J": float(np.sum(modal_work)),
            "absolute_modal_work_J": float(np.sum(np.abs(modal_work))),
            "signed_Ht_work_J": float(np.sum(H_work)),
        },
        "power_consistency": {
            "max_abs_direct_minus_H_W": float(np.max(np.abs(item["power_direct"] - item["power_H"]))),
            "max_abs_H_minus_modal_W": float(np.max(np.abs(item["power_H"] - item["power_modal"]))),
            "relative_direct_minus_H_work": rel_l2(direct_work, H_work),
            "relative_H_minus_modal_work": rel_l2(H_work, modal_work),
        },
    }
    return result


def modal_energy_work_audit(data: Mapping[str, Any], system: Mapping[str, Any]) -> dict[str, Any]:
    runs = {key: mode_work_energy(item, system) for key, item in data.items()}
    result = {
        "schema_version": "stage4d-c-a-v3-modal-energy-work-1",
        "linearized_strain_energy_definition": "0.5*omega_j^2*eta_j^2; static-state linear proxy, not full nonlinear ANCF strain energy",
        "force_mapping": "Q = H^T F with integrated_N slice forces; no second slice-length multiplication",
        "primary_release_run": "dt_0_0003125",
        "runs": runs,
        "all_power_consistency_pass": all(v["power_consistency"]["relative_direct_minus_H_work"] <= 1.0e-9 and v["power_consistency"]["relative_H_minus_modal_work"] <= 1.0e-9 for v in runs.values()),
    }
    finite(result, "modal_energy_work")
    write_json(RESULTS_ROOT / "modal_energy_work_audit.json", result)
    return result


def align_pair(coarse: Mapping[str, Any], fine: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    ct = coarse["time"]; ft = fine["time"]
    indices = []
    errors = []
    for t in ct:
        index = int(np.argmin(np.abs(ft - t)))
        indices.append(index); errors.append(abs(float(ft[index] - t)))
    if max(errors) > 1.0e-12:
        raise ValueError("Time grids cannot be aligned without interpolation")
    return np.arange(len(ct), dtype=int), np.asarray(indices, dtype=int)


def velocity_band(item: Mapping[str, Any], modes: Sequence[int]) -> np.ndarray:
    if not modes:
        return np.zeros_like(item["v_xy"])
    return np.sum(item["v_mode_xy"][:, list(modes), :], axis=1)


def velocity_attribution(data: Mapping[str, Any], energy: Mapping[str, Any], system: Mapping[str, Any]) -> dict[str, Any]:
    mode_count = int(system["mode_count"])
    bands = {
        "modes_1_2": list(range(min(2, mode_count))),
        "modes_3_5": list(range(2, min(5, mode_count))),
        "modes_6_plus": list(range(min(5, mode_count), mode_count)),
        "all_modes": list(range(mode_count)),
    }
    pair_specs = [(0.0025, 0.00125), (0.00125, 0.000625), (0.000625, 0.0003125)]
    pairs = []
    for coarse_dt, fine_dt in pair_specs:
        c = data["dt_" + str(coarse_dt).replace(".", "_")]
        f = data["dt_" + str(fine_dt).replace(".", "_")]
        ci, fi = align_pair(c, f)
        full_c = c["v_xy"][ci]
        full_f = f["v_xy"][fi]
        modes = []
        for j in range(mode_count):
            c_mode = c["v_mode_xy"][ci, j]
            f_mode = f["v_mode_xy"][fi, j]
            modes.append({
                "mode_index_1based": j + 1,
                "frequency_Hz": float(arr(system["frequencies_Hz"])[j]),
                "eta_dot_nrmse": nrmse(f["etad"][fi, j], c["etad"][ci, j], 1.0e-10),
                "velocity_difference_rms_mps": float(np.sqrt(np.mean((f_mode - c_mode) ** 2))),
                "velocity_difference_rms_fraction_of_full_fine": float(np.sqrt(np.mean((f_mode - c_mode) ** 2)) / max(float(np.sqrt(np.mean(full_f * full_f))), 1.0e-12)),
                "velocity_rms_fine_mps": float(np.sqrt(np.mean(f_mode * f_mode))),
                "velocity_rms_change": float(abs(np.sqrt(np.mean(f_mode * f_mode)) - np.sqrt(np.mean(c_mode * c_mode))) / max(np.sqrt(np.mean(f_mode * f_mode)), 1.0e-12)),
            })
        band_rows = {}
        for label, indices in bands.items():
            c_band = velocity_band(c, indices)[ci]
            f_band = velocity_band(f, indices)[fi]
            band_rows[label] = {
                "mode_indices_1based": [i + 1 for i in indices],
                "timestamp_aligned_pair_velocity_nrmse": nrmse(f_band, c_band, 1.0e-10),
                "fine_full_velocity_vs_fine_band_truncation_nrmse": nrmse(full_f, f_band, 1.0e-10),
                "coarse_full_vs_fine_band_nrmse": nrmse(full_f, c_band, 1.0e-10),
                "fine_band_velocity_rms_mps": float(np.sqrt(np.mean(f_band * f_band))),
            }
        full_error = band_rows["all_modes"]["timestamp_aligned_pair_velocity_nrmse"]
        # A non-linear leave-one-mode-out ranking, in addition to per-mode RMS.
        loo = []
        for j in range(mode_count):
            keep = [i for i in range(mode_count) if i != j]
            c_loo = velocity_band(c, keep)[ci]
            f_loo = velocity_band(f, keep)[fi]
            error_without = nrmse(f_loo, c_loo, 1.0e-10)
            loo.append({"mode_index_1based": j + 1, "error_without_mode": error_without, "absolute_change_in_pair_error": abs(full_error - error_without), "signed_change_in_pair_error": full_error - error_without})
        loo.sort(key=lambda row: row["absolute_change_in_pair_error"], reverse=True)
        pairs.append({
            "coarse_dt_s": coarse_dt,
            "fine_dt_s": fine_dt,
            "time_alignment_max_abs_error_s": 0.0,
            "timestamp_aligned_full_slice_velocity_nrmse": full_error,
            "frozen_v2_reported_slice_velocity_nrmse": {"0.0025/0.00125": 0.17777164284355298, "0.00125/0.000625": 0.07168040482737578, "0.000625/0.0003125": 0.07126413802276343}[f"{coarse_dt}/{fine_dt}"],
            "modal_metrics": modes,
            "frequency_bands": band_rows,
            "largest_five_leave_one_mode_changes": loo[:5],
        })
    result = {
        "schema_version": "stage4d-c-a-v3-slice-velocity-attribution-1",
        "alignment_rule": "match exact common physical times; no interpolation or phase shift",
        "bands": {key: [i + 1 for i in value] for key, value in bands.items()},
        "pairs": pairs,
        "interpretation": "The frozen v2 metric is retained for traceability; v3 additionally reports strict timestamp-aligned replay comparison because each dt history starts at its own first step.",
    }
    finite(result, "velocity_attribution")
    write_json(RESULTS_ROOT / "slice_velocity_error_attribution.json", result)
    return result


def required_dt_for_phase(freq_hz: float, duration_s: float = DURATION_S, phase_limit: float = 0.05) -> float:
    omega = 2.0 * math.pi * freq_hz
    def phase(dt: float) -> float:
        return abs((2.0 / dt * math.atan(omega * dt / 2.0) - omega) * duration_s)
    low = 0.0; high = 0.01
    while phase(high) <= phase_limit:
        high *= 2.0
    for _ in range(100):
        mid = 0.5 * (low + high)
        if phase(mid) <= phase_limit:
            low = mid
        else:
            high = mid
    return low


def newmark_all_mode_dispersion(system: Mapping[str, Any], energy: Mapping[str, Any]) -> dict[str, Any]:
    frequencies = arr(system["frequencies_Hz"]).reshape(-1)
    significant = []
    primary = energy["runs"]["dt_0_0003125"]["modes"]
    for mode in primary:
        significant.append(mode["displacement_mass_fraction"] >= 1.0e-4 or mode["kinetic_energy_fraction"] >= 1.0e-4 or mode["absolute_work_fraction"] >= 1.0e-4)
    modes = []
    for j, freq in enumerate(frequencies):
        omega = 2.0 * math.pi * float(freq)
        rows = []
        for dt in DT_VALUES:
            wt = (2.0 / dt) * math.atan(omega * dt / 2.0)
            phase = (wt - omega) * DURATION_S
            rows.append({
                "dt_s": dt,
                "steps_per_period": 1.0 / (float(freq) * dt),
                "global_steps_for_0p25s": int(round(DURATION_S / dt)),
                "openfoam_slice_executions_for_3_slices": int(round(DURATION_S / dt)) * 3,
                "numerical_frequency_Hz": wt / (2.0 * math.pi),
                "frequency_ratio": wt / omega,
                "cumulative_phase_error_rad": phase,
                "phase_limit_0p05_rad_satisfied": abs(phase) <= 0.05,
            })
        required = required_dt_for_phase(float(freq))
        modes.append({
            "mode_index_1based": j + 1,
            "frequency_Hz": float(freq),
            "significant_energy_or_work_contribution": bool(significant[j]),
            "required_dt_for_0p25s_phase_error_le_0p05_rad_s": required,
            "required_global_steps_ceiling": int(math.ceil(DURATION_S / required)),
            "required_three_slice_openfoam_executions": int(math.ceil(DURATION_S / required)) * 3,
            "time_steps": rows,
        })
    result = {
        "schema_version": "stage4d-c-a-v3-newmark-all-mode-dispersion-1",
        "method": "w_tilde=(2/dt)*atan(w*dt/2)",
        "duration_s": DURATION_S,
        "nElem": int(system["nElem"]),
        "mode_count": int(system["mode_count"]),
        "phase_requirement": "absolute cumulative phase error <= 0.05 rad over 0.25 s",
        "modes": modes,
        "campaign_estimate_is_theoretical_only": True,
    }
    finite(result, "newmark_all_mode_dispersion")
    write_json(RESULTS_ROOT / "newmark_all_mode_dispersion.json", result)
    return result


def engineering_bandwidth(data: Mapping[str, Any], energy: Mapping[str, Any], system: Mapping[str, Any]) -> dict[str, Any]:
    primary_key = "dt_0_0003125"
    item = data[primary_key]
    mode_rows = energy["runs"][primary_key]["modes"]
    nmode = int(system["mode_count"])
    full_v = item["v_xy"]
    total_disp = sum(row["displacement_mass_fraction"] for row in mode_rows)
    total_t = sum(row["kinetic_energy_fraction"] for row in mode_rows)
    total_w = sum(row["absolute_work_fraction"] for row in mode_rows)
    candidates = []
    for n in range(1, nmode + 1):
        modes = list(range(n))
        band_v = velocity_band(item, modes)
        disp = sum(mode_rows[j]["displacement_mass_fraction"] for j in modes) / max(total_disp, 1.0e-30)
        kinetic = sum(mode_rows[j]["kinetic_energy_fraction"] for j in modes) / max(total_t, 1.0e-30)
        work = sum(mode_rows[j]["absolute_work_fraction"] for j in modes) / max(total_w, 1.0e-30)
        candidates.append({
            "retained_mode_count": n,
            "highest_retained_frequency_Hz": float(arr(system["frequencies_Hz"])[n - 1]),
            "retained_modes_1based": [j + 1 for j in modes],
            "displacement_mass_norm_cumulative_fraction": disp,
            "kinetic_energy_cumulative_fraction": kinetic,
            "slice_velocity_rms_reconstruction_error": nrmse(full_v, band_v, 1.0e-12),
            "absolute_work_cumulative_fraction": work,
            "all_thresholds_met": bool(disp >= 0.99 and kinetic >= 0.99 and nrmse(full_v, band_v, 1.0e-12) <= 0.01 and work >= 0.99),
        })
    valid = [x for x in candidates if x["all_thresholds_met"]]
    result = {
        "schema_version": "stage4d-c-a-v3-engineering-bandwidth-1",
        "source_run": primary_key,
        "thresholds": {"displacement_mass_norm_fraction": 0.99, "kinetic_energy_fraction": 0.99, "slice_velocity_rms_reconstruction_error": 0.01, "absolute_work_fraction": 0.99},
        "candidates": candidates,
        "candidate": min(valid, key=lambda x: x["retained_mode_count"]) if valid else None,
        "status": "candidate_not_frozen" if valid else "effective_bandwidth_not_frozen",
        "does_not_lower_existing_5_percent_time_step_gate": True,
    }
    finite(result, "engineering_bandwidth")
    write_json(RESULTS_ROOT / "engineering_bandwidth_candidate.json", result)
    return result


def physical_scaling(system: Mapping[str, Any]) -> dict[str, Any]:
    freq = arr(system["frequencies_Hz"]).reshape(-1)
    D = 1.0; L = 10.0; U_values = [0.8, 1.0, 1.2]
    rho_s = 7850.0; rho_flow = 1000.0; rho_model_fluid = 1025.0
    area = math.pi * (D * D - 0.9 * 0.9) / 4.0
    displaced_area = math.pi * D * D / 4.0
    mass_per_length = rho_s * area
    displaced_mass_per_length = rho_flow * displaced_area
    displaced_mass_per_length_1025 = rho_model_fluid * displaced_area
    EA = 2.07e11 * area
    EI = 2.07e11 * math.pi * (D ** 4 - 0.9 ** 4) / 64.0
    mode_scaling = []
    for j, f in enumerate(freq):
        mode_scaling.append({
            "mode_index_1based": j + 1,
            "frequency_Hz": float(f),
            "frequency_to_shedding_ratio": {key: float(f / value["frequency_Hz"]) for key, value in SHEDDING.items()},
            "reduced_velocity_U_over_fnD": {key: float(value["U_mps"] / (f * D)) for key, value in SHEDDING.items()},
        })
    first = float(freq[0])
    target_ranges = []
    for flow_id, value in SHEDDING.items():
        f_low = value["U_mps"] / (10.0 * D)
        f_high = value["U_mps"] / (3.0 * D)
        target_ranges.append({"flow_id": flow_id, "U_mps": value["U_mps"], "target_fn_Hz_for_Ur_3_to_10": [f_low, f_high], "current_first_mode_Hz": first, "current_first_mode_Ur": value["U_mps"] / (first * D)})
    result = {
        "schema_version": "stage4d-c-a-v3-viv-physical-scaling-1",
        "current_model": {"L_m": L, "D_m": D, "E_Pa": 2.07e11, "top_tension_N": 1.0e7, "nElem": 2, "damping": "zero"},
        "structural_frequencies_Hz": freq.tolist(),
        "shedding_frequencies": SHEDDING,
        "structural_to_shedding_ratio_first_mode": {key: first / value["frequency_Hz"] for key, value in SHEDDING.items()},
        "first_mode_reduced_velocity": {key: value["U_mps"] / (first * D) for key, value in SHEDDING.items()},
        "mass_and_stiffness_scales": {
            "structural_mass_per_length_kgpm": mass_per_length,
            "displaced_mass_per_length_kgpm_rho1000": displaced_mass_per_length,
            "displaced_mass_per_length_kgpm_rho1025": displaced_mass_per_length_1025,
            "mass_ratio_without_added_mass_rho1000": mass_per_length / displaced_mass_per_length,
            "mass_ratio_without_added_mass_rho1025": mass_per_length / displaced_mass_per_length_1025,
            "added_mass_included": False,
            "axial_stiffness_EA_N": EA,
            "bending_stiffness_EI_Nm2": EI,
            "top_tension_N": 1.0e7,
        },
        "mode_scaling": mode_scaling,
        "target_first_frequency_ranges_for_Ur_3_to_10": target_ranges,
        "baseline_classification": {"engineering_coupling_baseline": True, "viv_physical_validation_baseline": False},
        "physical_conclusion": "Current first structural frequency is approximately 155-257 times the developed-flow shedding frequency; the present parameter set is not a VIV lock-in physical baseline.",
    }
    finite(result, "physical_scaling")
    write_json(RESULTS_ROOT / "viv_physical_scaling_audit.json", result)
    return result


def run_all() -> dict[str, Any]:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    raw = read_json(RAW_PATH)
    finite(raw, "ancf_replay_raw")
    hashes = input_hash_audit()
    system = build_modal_system()
    release_reference = raw["routes"]["release"]["dt_0_00125"]
    system_audit = modal_system_audit(system, release_reference)
    global SYSTEM
    SYSTEM = system
    data = {"dt_" + str(dt).replace(".", "_"): run_arrays(load_run(raw, dt), system) for dt in (0.0025, 0.00125, 0.000625, 0.0003125)}
    reconstruction = reconstruction_audit(data)
    energy = modal_energy_work_audit(data, system)
    attribution = velocity_attribution(data, energy, system)
    dispersion = newmark_all_mode_dispersion(system, energy)
    bandwidth = engineering_bandwidth(data, energy, system)
    scaling = physical_scaling(system)
    candidate = {
        "status": "completed",
        "stage": "Stage 4D-C-A-v3",
        "diagnostic_only": True,
        "protocol_version": PROTOCOL_VERSION,
        "manifest_sha256": MANIFEST_HASH,
        "openfoam_invoked": False,
        "checkMesh_invoked": False,
        "setFields_invoked": False,
        "nElem": int(system["nElem"]),
        "free_dof_count": int(system["free_dof_count"]),
        "mode_count": int(system["mode_count"]),
        "full_reconstruction_passed": reconstruction["all_pass"],
        "power_consistency_passed": energy["all_power_consistency_pass"],
        "engineering_bandwidth_status": bandwidth["status"],
        "timestamp_aligned_finest_pair_velocity_nrmse": attribution["pairs"][-1]["timestamp_aligned_full_slice_velocity_nrmse"],
        "frozen_v2_finest_pair_velocity_nrmse": attribution["pairs"][-1]["frozen_v2_reported_slice_velocity_nrmse"],
        "viv_physical_validation_baseline": False,
        "new_real_cfd_campaign_authorized": False,
        "stage4d_c_gate_redecision": "not_performed",
        "sol_decision_required": True,
    }
    finite(candidate, "candidate")
    write_json(RESULTS_ROOT / "stage4d_c_a_v3_candidate_summary.json", candidate)
    return candidate


SYSTEM: Mapping[str, Any] = {}


if __name__ == "__main__":
    print(json.dumps(run_all(), ensure_ascii=False))
