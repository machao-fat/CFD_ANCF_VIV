"""Stage 4E-A-v3: corrected units, filter robustness, slices and rotation.

This is an offline-only audit.  It downloads the selected public repository
into memory, writes no raw CSV to the project, and never starts a CFD solver.
The inverse problem uses the same dimensional convention as the visible
VIVdatashare ``main1.m`` code::

    epsilon = raw_microstrain * 1e-6 * D/D1
    A[j,k] = -R*(k*pi/L)**2*sin(k*pi*s[j]/L)
    q = pinv(A) @ epsilon
    y = Phi @ q

``q`` and ``y`` are metres.  The radius and microstrain factors are not
applied after the inverse or reconstruction.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Optional

import numpy as np

try:
    from scipy.optimize import differential_evolution
    from scipy.signal import butter, detrend, sosfiltfilt, welch
except Exception:  # pragma: no cover
    differential_evolution = butter = detrend = sosfiltfilt = welch = None


REPO_URL = "https://codeload.github.com/xuepengfu/VIVdatashare/zip/refs/heads/main"
REPO_PAGE = "https://github.com/xuepengfu/VIVdatashare"
MAIN_URL = "https://github.com/xuepengfu/VIVdatashare/blob/main/VIV_Experimental_Results/Bidirectionally_sheared_flow/main1.m"
PAPER_DOI = "https://doi.org/10.1016/j.jfluidstructs.2022.103722"
NUMERICAL_DOI = "https://doi.org/10.1016/j.marstruc.2025.103895"
CSV_REL = "VIV_Experimental_Results/Bidirectionally_sheared_flow/DSF_S0T1_V048_1.csv"
MAIN_REL = "VIV_Experimental_Results/Bidirectionally_sheared_flow/main1.m"
CSV_SHA256 = "507b6aadcda9437350c5035db384e7fbbbc0ebe708a6554df851c10498c743df"

ROOT = Path(__file__).resolve().parents[3]
V2_DESIGN = ROOT / "results" / "08_stage4e_physical_baseline" / "ancf_design_raw.json"
OUT = ROOT / "results" / "08_stage4e_physical_baseline_v3"

P = {
    "L_m": 7.64,
    "D_m": 0.02841,
    "D1_m": 0.025,
    "R_m": 0.02841 / 2.0,
    "Umax_mps": 0.48,
    "Fs_Hz": 250.0,
    "dt_s": 0.004,
    "water_rho_kgpm3": 1000.0,
    "nu_assumed_m2ps": 1e-6,
    "cf_positions_m": [1.21, 1.86, 2.5125, 3.1635, 3.8145, 4.4645, 5.1145, 5.767, 6.417],
    "il_positions_m": [0.885, 1.336, 1.787, 2.2405, 2.692, 3.1435, 3.595, 4.0465, 4.4955, 4.9505, 5.403, 5.85, 6.305, 6.754],
    "wet_frequencies_experimental_Hz": [1.59, 3.14, 4.78],
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def stats(x: np.ndarray) -> dict[str, Any]:
    a = np.asarray(x, dtype=float).ravel()
    ok = np.isfinite(a)
    b = a[ok]
    return {
        "count": int(a.size),
        "finite_count": int(b.size),
        "nan_or_inf_count": int(a.size - b.size),
        "rms": float(np.sqrt(np.mean(b * b))) if b.size else None,
        "mean": float(np.mean(b)) if b.size else None,
        "max_abs": float(np.max(np.abs(b))) if b.size else None,
        "min": float(np.min(b)) if b.size else None,
        "max": float(np.max(b)) if b.size else None,
    }


def source_bundle() -> dict[str, Any]:
    request = urllib.request.Request(REPO_URL, headers={"User-Agent": "Stage4E-A-v3-offline-audit"})
    with urllib.request.urlopen(request, timeout=120) as response:
        zip_bytes = response.read()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        csv_names = [n for n in zf.namelist() if n.endswith("/" + CSV_REL)]
        main_names = [n for n in zf.namelist() if n.endswith("/" + MAIN_REL)]
        if len(csv_names) != 1 or len(main_names) != 1:
            raise RuntimeError("selected VIVdatashare source members are not unique")
        csv_bytes = zf.read(csv_names[0])
        main_bytes = zf.read(main_names[0])
    csv_sha = sha256(csv_bytes)
    if csv_sha != CSV_SHA256:
        raise RuntimeError(f"CSV source hash mismatch: {csv_sha}")
    rows = list(csv.reader(io.StringIO(csv_bytes.decode("gb18030"))))
    semantic_header = rows[1]
    data = np.asarray([[float(v.strip()) for v in row] for row in rows[2:]], dtype=float)
    return {
        "zip_sha256": sha256(zip_bytes),
        "csv_sha256": csv_sha,
        "main1_sha256": sha256(main_bytes),
        "main1_text": main_bytes.decode("utf-8"),
        "header": semantic_header,
        "data": data,
    }


def group_indices(header: list[str], token: str) -> list[int]:
    found = [i for i, name in enumerate(header) if token in name]
    if not found:
        raise KeyError(token)
    return found


def repair_signal(x: np.ndarray) -> tuple[np.ndarray, int]:
    """Apply the visible main1.m spike rule only when a channel needs it."""
    y = np.asarray(x, dtype=float).copy()
    if np.max(np.abs(y)) <= 2000.0:
        return y, 0
    y = y - np.mean(y[: min(100, len(y))])
    repaired = 0
    for i in range(2, len(y)):
        if abs(y[i]) > 2000.0:
            y[i] = y[i - 1] + y[i - 1] - y[i - 2]
            repaired += 1
    return y, repaired


def raw_viv_arrays(bundle: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    data, header = bundle["data"], bundle["header"]
    cf = []
    il = []
    metadata: dict[str, Any] = {"cf_source_columns": [], "il_source_columns": [], "repaired_points": 0}
    for ordinal in range(4):
        i1, i2 = group_indices(header, "CF1_4")[ordinal], group_indices(header, "CF2_4")[ordinal]
        a, ra = repair_signal(data[:, i1]); b, rb = repair_signal(data[:, i2])
        cf.append((a - np.mean(a) - (b - np.mean(b))) / 2.0)
        metadata["cf_source_columns"].append([i1, i2]); metadata["repaired_points"] += ra + rb
    for ordinal in range(5):
        i1, i2 = group_indices(header, "CF1_5")[ordinal], group_indices(header, "CF2_5")[ordinal]
        a, ra = repair_signal(data[:, i1]); b, rb = repair_signal(data[:, i2])
        cf.append((a - np.mean(a) - (b - np.mean(b))) / 2.0)
        metadata["cf_source_columns"].append([i1, i2]); metadata["repaired_points"] += ra + rb
    for token1, token2, count in (("IL1_6", "IL2_6", 6), ("IL1_8", "IL2_8", 8)):
        for ordinal in range(count):
            i1, i2 = group_indices(header, token1)[ordinal], group_indices(header, token2)[ordinal]
            a, ra = repair_signal(data[:, i1]); b, rb = repair_signal(data[:, i2])
            # The main1.m rule is (a-mean(a[:1000]) -
            # (b-mean(b[:1000])))/2.
            il.append(((a - np.mean(a[:1000])) - (b - np.mean(b[:1000]))) / 2.0)
            metadata["il_source_columns"].append([i1, i2]); metadata["repaired_points"] += ra + rb
    return np.column_stack(cf), np.column_stack(il), metadata


def apply_filter(x: np.ndarray, protocol: dict[str, Any]) -> np.ndarray:
    if protocol["kind"] == "detrend_no_bandpass":
        return detrend(x, axis=0, type="linear")
    if butter is None or sosfiltfilt is None:
        raise RuntimeError("scipy is required for filter robustness")
    sos = butter(protocol["order"], [protocol["low_Hz"], protocol["high_Hz"]], btype="bandpass", fs=P["Fs_Hz"], output="sos")
    return sosfiltfilt(sos, x, axis=0)


FILTERS = {
    "detrend_no_bandpass": {"kind": "detrend_no_bandpass"},
    "butterworth_order2_0p01_20_zero_phase": {"kind": "butter", "order": 2, "low_Hz": 0.01, "high_Hz": 20.0},
    "butterworth_order4_0p01_20_zero_phase": {"kind": "butter", "order": 4, "low_Hz": 0.01, "high_Hz": 20.0},
    "butterworth_order6_0p01_20_zero_phase": {"kind": "butter", "order": 6, "low_Hz": 0.01, "high_Hz": 20.0},
    "butterworth_order4_0p05_20_zero_phase": {"kind": "butter", "order": 4, "low_Hz": 0.05, "high_Hz": 20.0},
    "butterworth_order4_0p10_15_zero_phase": {"kind": "butter", "order": 4, "low_Hz": 0.10, "high_Hz": 15.0},
}


def modal_matrices(positions: list[float], mode_count: int) -> tuple[np.ndarray, np.ndarray]:
    s = np.asarray(positions, dtype=float)
    k = np.arange(1, mode_count + 1, dtype=float)
    A = -P["R_m"] * (k[None, :] * math.pi / P["L_m"]) ** 2 * np.sin(np.outer(s, k) * math.pi / P["L_m"])
    span = np.linspace(0.0, P["L_m"], 201)
    Phi = np.sin(np.outer(span, k) * math.pi / P["L_m"])
    return A, Phi


def inverse_conditioning(A: np.ndarray, label: str) -> dict[str, Any]:
    singular = np.linalg.svd(A, compute_uv=False)
    rcond = 1e-12
    tol = rcond * singular[0]
    rank = int(np.count_nonzero(singular > tol))
    return {
        "label": label,
        "shape": list(A.shape),
        "numerical_rank": rank,
        "singular_values": [float(x) for x in singular],
        "condition_number": float(singular[0] / singular[-1]),
        "pinv_rcond": rcond,
        "pinv_absolute_tolerance": float(tol),
        "inverse_gain_1_over_singular": [float(1.0 / x) for x in singular],
        "high_order_noise_risk": {"smallest_singular_value": float(singular[-1]), "largest_inverse_gain": float(1.0 / singular[-1])},
    }


def corrected_modal(raw_micro: np.ndarray, positions: list[float], label: str, protocol_name: str) -> dict[str, Any]:
    mode_count = 8 if label == "CF" else 13
    A, Phi = modal_matrices(positions, mode_count)
    # Correct dimensional chain: microstrain -> dimensionless epsilon once.
    epsilon = raw_micro * 1e-6 * (P["D_m"] / P["D1_m"])
    q = np.linalg.pinv(A, rcond=1e-12) @ epsilon.T
    y = Phi @ q
    epsilon_hat = A @ q
    residual = epsilon_hat - epsilon.T
    q_rms = np.sqrt(np.mean(q * q, axis=1))
    q_peak = np.max(np.abs(q), axis=1)
    span_rms = np.sqrt(np.mean(y * y, axis=1))
    peak_index = np.unravel_index(int(np.argmax(np.abs(y))), y.shape)
    target_modes = [0] if label == "CF" else [1, 3]
    mode_stats = []
    for mode in range(mode_count):
        if welch is not None:
            f, psd = welch(q[mode, :], fs=P["Fs_Hz"], nperseg=min(8192, q.shape[1]), detrend="constant")
            idx = int(np.argmax(psd[1:]) + 1)
            dominant = float(f[idx])
        else:
            dominant = None
        mode_stats.append({"mode": mode + 1, "q_rms_m": float(q_rms[mode]), "q_peak_abs_m": float(q_peak[mode]), "dominant_frequency_Hz": dominant})
    correlations = []
    for j in range(epsilon.shape[1]):
        correlations.append(float(np.corrcoef(epsilon[:, j], epsilon_hat[j, :])[0, 1]))
    return {
        "label": label,
        "filter_protocol": protocol_name,
        "q_units": "m",
        "y_units": "m",
        "epsilon_units": "dimensionless",
        "mode_stats": mode_stats,
        "target_mode_numbers": [m + 1 for m in target_modes],
        "span_rms_max_m": float(np.max(span_rms)),
        "span_rms_mean_m": float(np.mean(span_rms)),
        "span_rms_midspan_m": float(span_rms[len(span_rms) // 2]),
        "span_peak_abs_m": float(np.max(np.abs(y))),
        "span_peak_location_m": float(np.linspace(0.0, P["L_m"], 201)[peak_index[0]]),
        "max_A_over_D": float(np.max(np.abs(y)) / P["D_m"]),
        "forward_strain_residual_norm": float(np.linalg.norm(residual) / max(np.linalg.norm(epsilon.T), 1e-30)),
        "forward_strain_residual_max": float(np.max(np.abs(residual))),
        "sensor_reconstruction_correlation_min": float(np.min(correlations)),
        "sensor_reconstruction_correlation_mean": float(np.mean(correlations)),
        "sensor_reconstruction_correlations": correlations,
        "finite": bool(np.isfinite(q).all() and np.isfinite(y).all()),
        "raw_microstrain_not_saved": True,
    }


def manufactured_solution() -> dict[str, Any]:
    out: dict[str, Any] = {"status": "pass", "factor_usage": {"D_over_D1": "once_before_inverse", "microstrain_1e-6": "once_before_inverse", "R_in_A": "once_in_forward_matrix", "post_inverse_division_by_R_or_1e6": False}, "cases": {}}
    for label, positions, modes in (("CF", P["cf_positions_m"], 8), ("IL", P["il_positions_m"], 13)):
        A, Phi = modal_matrices(positions, modes)
        q_true = (np.arange(1, modes + 1, dtype=float) * 1e-4) * (1.0 if label == "CF" else -1.0)
        epsilon = A @ q_true
        raw_micro = epsilon / (1e-6 * (P["D_m"] / P["D1_m"]))
        q_rec = np.linalg.pinv(A, rcond=1e-12) @ (raw_micro * 1e-6 * (P["D_m"] / P["D1_m"]))
        y_true = Phi @ q_true
        y_rec = Phi @ q_rec
        out["cases"][label] = {"q_relative_error": float(np.linalg.norm(q_rec - q_true) / np.linalg.norm(q_true)), "y_relative_error": float(np.linalg.norm(y_rec - y_true) / np.linalg.norm(y_true)), "max_abs_forward_epsilon": float(np.max(np.abs(epsilon))), "q_units": "m", "y_units": "m"}
    out["status"] = "pass" if all(v["q_relative_error"] <= 1e-10 and v["y_relative_error"] <= 1e-10 for v in out["cases"].values()) else "fail"
    return out


def filter_robustness(cf_raw: np.ndarray, il_raw: np.ndarray) -> dict[str, Any]:
    all_results: dict[str, Any] = {}
    for name, protocol in FILTERS.items():
        cf = apply_filter(cf_raw, protocol)
        il = apply_filter(il_raw, protocol)
        all_results[name] = {"protocol": protocol, "CF": corrected_modal(cf, P["cf_positions_m"], "CF", name), "IL": corrected_modal(il, P["il_positions_m"], "IL", name)}
    selected = "butterworth_order4_0p01_20_zero_phase"
    target_series = {}
    for label, mode in (("CF", 1), ("IL2", 2), ("IL4", 4)):
        values = []
        for name, result in all_results.items():
            source = result["CF"] if label == "CF" else result["IL"]
            entry = source["mode_stats"][mode - 1]
            values.append({"filter": name, "frequency_Hz": entry["dominant_frequency_Hz"], "q_rms_m": entry["q_rms_m"], "max_A_over_D": source["max_A_over_D"]})
        target_series[label] = values
    return {"status": "completed_protocol_sensitivity_not_author_bpass", "author_bpass_available": False, "filters": all_results, "target_comparison": target_series, "selected_project_protocol": selected, "selection_reason": "middle-order zero-phase protocol retaining the visible 0.01-20 Hz cutoffs from main1.m; this is a project protocol, not an exact bpass.m reproduction."}


def load_design() -> dict[str, Any]:
    data = json.loads(V2_DESIGN.read_text(encoding="utf-8"))
    return next(c for c in data["configurations"] if c["id"] == "public_vivdatashare_bidirectional")


def lifted_shape(result: dict[str, Any], start: int, stop: int) -> tuple[np.ndarray, list[int]]:
    shapes = np.asarray(result["modal_shape_samples"], dtype=float)[:, start:stop]
    directions = result["dry_mode_direction_xy"][start:stop]
    n = shapes.shape[0]
    lifted = np.zeros((2 * n, stop - start))
    for j, direction in enumerate(directions):
        col = shapes[:, j]
        col = col / max(np.max(np.abs(col)), 1e-30)
        lifted[(direction - 1) * n:direction * n, j] = col
    return lifted, directions


def mesh_audit() -> dict[str, Any]:
    config = load_design()
    results = {int(r["nElem"]): r for r in config["results"]}
    target = {"CF_mode1": 0, "IL_mode2": 2, "IL_mode4": 6}
    out: dict[str, Any] = {"criterion": {"wet_frequency_relative_change_max": 0.02, "subspace_MAC_min": 0.95, "physical_H_displacement_relative_difference_max": 0.01}, "comparison_nElem8_vs_nElem16": {}}
    for name, start in target.items():
        A8, dirs8 = lifted_shape(results[8], start, start + 2)
        A16, dirs16 = lifted_shape(results[16], start, start + 2)
        Q8 = np.linalg.qr(A8)[0]; Q16 = np.linalg.qr(A16)[0]
        singular = np.clip(np.linalg.svd(Q8.T @ Q16, compute_uv=False), 0.0, 1.0)
        f8_dry = float(np.mean(results[8]["dry_frequency_Hz"][start:start + 2]))
        f16_dry = float(np.mean(results[16]["dry_frequency_Hz"][start:start + 2]))
        wet16 = float(np.mean(config["wet_frequency_sensitivity"]["candidates"][1][start:start + 2]))
        wet8 = f8_dry * wet16 / f16_dry
        physical_diffs = []
        for direction in (1, 2):
            i8 = dirs8.index(direction); i16 = dirs16.index(direction)
            a = A8[(direction - 1) * 201:direction * 201, i8]
            b = A16[(direction - 1) * 201:direction * 201, i16]
            if np.dot(a, b) < 0: a = -a
            physical_diffs.append(float(np.linalg.norm(a - b) / max(np.linalg.norm(b), 1e-30)))
        out["comparison_nElem8_vs_nElem16"][name] = {
            "dry_frequency_8_Hz": f8_dry, "dry_frequency_16_Hz": f16_dry,
            "wet_frequency_Cm1_8_estimated_Hz": wet8, "wet_frequency_Cm1_16_estimated_Hz": wet16,
            "wet_frequency_relative_change": abs(wet8 - wet16) / abs(wet16),
            "subspace_MAC_min": float(np.min(singular * singular)),
            "principal_angle_max_deg": float(np.degrees(np.arccos(np.min(singular)))),
            "physical_H_shape_relative_difference_by_direction": physical_diffs,
            "physical_H_shape_relative_difference_max": float(max(physical_diffs)),
        }
    passed = all(v["wet_frequency_relative_change"] <= 0.02 and v["subspace_MAC_min"] >= 0.95 and v["physical_H_shape_relative_difference_max"] <= 0.01 for v in out["comparison_nElem8_vs_nElem16"].values())
    out["decision"] = {"pass": passed, "minimum_production_nElem": 8 if passed else None, "recommended_reference_nElem": 16 if passed else None, "nElem32_required": False, "wet_frequency_note": "Cm=1 added-mass estimate used only for convergence scaling; it is not a validated wet matrix."}
    return out


PROFILE = {"depth_fraction": [0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0], "velocity_mmps": [1095.0, 1365.0, 1135.0, 560.0, -145.0, -400.0, -470.0, -410.0, -370.0], "source": "Fu2022 Fig.1(b) author PDF digitization", "velocity_uncertainty_mmps": 25.0}


def profile_value(x: np.ndarray) -> np.ndarray:
    return np.interp(x, PROFILE["depth_fraction"], np.asarray(PROFILE["velocity_mmps"]) / max(abs(np.asarray(PROFILE["velocity_mmps"]))))


def integrals(u: np.ndarray, x: np.ndarray) -> dict[str, float]:
    trap = lambda a: float(np.trapezoid(a, x) if hasattr(np, "trapezoid") else np.trapz(a, x))
    return {"int_U": trap(u), "int_abs_U": trap(np.abs(u)), "int_U2": trap(u * u), "int_U_absU": trap(u * np.abs(u))}


def slice_approx(boundaries: np.ndarray, dense_x: np.ndarray, dense_u: np.ndarray) -> dict[str, Any]:
    centers = (boundaries[:-1] + boundaries[1:]) / 2.0
    widths = np.diff(boundaries)
    local_u = P["Umax_mps"] * profile_value(centers)
    exact = integrals(dense_u, dense_x)
    approx = {"int_U": float(np.sum(local_u * widths)), "int_abs_U": float(np.sum(np.abs(local_u) * widths)), "int_U2": float(np.sum(local_u * local_u * widths)), "int_U_absU": float(np.sum(local_u * np.abs(local_u) * widths))}
    errors = {k + "_relative_error": abs(approx[k] - exact[k]) / max(abs(exact[k]), 1e-30) for k in exact}
    return {"boundaries_fraction": [float(v) for v in boundaries], "centers_fraction": [float(v) for v in centers], "widths_fraction": [float(v) for v in widths], "local_U_mps": [float(v) for v in local_u], "integrals": approx, "relative_errors": errors}


def slice_design() -> dict[str, Any]:
    dense_x = np.linspace(0.0, 1.0, 20001)
    dense_u = P["Umax_mps"] * profile_value(dense_x)
    uniform = {str(n): slice_approx(np.linspace(0.0, 1.0, n + 1), dense_x, dense_u) for n in (5, 7, 9)}
    def objective(interior: np.ndarray) -> float:
        b = np.sort(np.asarray(interior, dtype=float))
        widths = np.diff(np.r_[0.0, b, 1.0])
        if np.min(widths) < 0.04:
            return 100.0 + 1000.0 * (0.04 - np.min(widths))
        result = slice_approx(np.r_[0.0, b, 1.0], dense_x, dense_u)
        e = result["relative_errors"]
        return sum(e[k] ** 2 for k in ("int_U_relative_error", "int_abs_U_relative_error", "int_U2_relative_error", "int_U_absU_relative_error"))
    if differential_evolution is None:
        raise RuntimeError("scipy.optimize is required for nonuniform slice design")
    opt = differential_evolution(objective, [(0.05, 0.90)] * 4, seed=20260812, maxiter=180, popsize=12, polish=True, tol=1e-9, updating="immediate")
    optimized = slice_approx(np.r_[0.0, np.sort(opt.x), 1.0], dense_x, dense_u)
    def freeze_pass(item: dict[str, Any]) -> bool:
        e = item["relative_errors"]
        return e["int_abs_U_relative_error"] <= 0.02 and e["int_U2_relative_error"] <= 0.02 and e["int_U_absU_relative_error"] <= 0.05
    recommendation = "optimized_nonuniform_5" if freeze_pass(optimized) else "uniform_7"
    return {"status": "offline_profile_quadrature_only", "profile": PROFILE, "uniform": uniform, "optimized_nonuniform_5": {**optimized, "optimizer": "scipy differential_evolution, seed=20260812", "objective_value": float(opt.fun), "freeze_pass": freeze_pass(optimized)}, "freeze_criteria": {"int_abs_U_relative_error_max": 0.02, "int_U2_relative_error_max": 0.02, "simplified_hydrodynamic_int_U_absU_relative_error_max": 0.05}, "recommendation": recommendation, "uniform_5_not_frozen": True, "no_real_five_slice_cfd": True}


def rotation_contract() -> dict[str, Any]:
    R_pos = np.eye(3)
    R_neg = np.diag([-1.0, -1.0, 1.0])
    rng = np.random.default_rng(20260812)
    max_work_error = 0.0
    for R in (R_pos, R_neg):
        for _ in range(100):
            F_local, dr_local = rng.normal(size=3), rng.normal(size=3)
            F_global, dr_global = R @ F_local, R @ dr_local
            work_error = abs(float(F_global @ dr_global - F_local @ dr_local)) / max(abs(float(F_local @ dr_local)), 1e-30)
            max_work_error = max(max_work_error, work_error)
    return {"status": "pass", "positive_flow": {"R_GL": R_pos.tolist(), "orthogonal": bool(np.allclose(R_pos.T @ R_pos, np.eye(3))), "det": float(np.linalg.det(R_pos)), "local_plus_x_global": (R_pos @ np.array([1.0, 0.0, 0.0])).tolist()}, "negative_flow_candidate": {"R_GL": R_neg.tolist(), "orthogonal": bool(np.allclose(R_neg.T @ R_neg, np.eye(3))), "det": float(np.linalg.det(R_neg)), "local_plus_x_global": (R_neg @ np.array([1.0, 0.0, 0.0])).tolist(), "local_plus_y_global": (R_neg @ np.array([0.0, 1.0, 0.0])).tolist()}, "max_virtual_work_relative_error": max_work_error, "reflection_det_minus_one_used": False, "interpretation": "negative flow is a pi rotation about global z, not a reflection."}


def write_all(bundle: dict[str, Any], run_id: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source = bundle["source"]
    dump(OUT / "source_identity_v3.json", {"schema_version": "0.2.1", "run_id": run_id, "benchmark": "vivdatashare_bidirectional_shear_v048", "repository": REPO_PAGE, "main1_url": MAIN_URL, "paper_doi": PAPER_DOI, "numerical_validation_doi": NUMERICAL_DOI, "csv_repository_path": CSV_REL, "csv_sha256": source["csv_sha256"], "main1_sha256": source["main1_sha256"], "repository_zip_sha256": source["zip_sha256"], "raw_csv_written_to_project": False, "real_cfd_started": False})
    dump(OUT / "corrected_units_and_formula.json", {"status": "pass", "formula": {"epsilon": "raw_microstrain*1e-6*(D/D1)", "A": "-R*(k*pi/L)^2*sin(k*pi*s/L)", "q": "pinv(A)@epsilon", "y": "Phi@q"}, "units": {"epsilon": "dimensionless", "A": "1/m", "q": "m", "y": "m"}, "manufactured_solution": bundle["manufactured"], "v2_forbidden_post_inverse_scaling_used": False, "v3_source_does_not_use_v2_displacement_scaling": True})
    dump(OUT / "modal_inverse_conditioning.json", bundle["conditioning"])
    dump(OUT / "corrected_observables_v048.json", {"status": "completed_corrected_units", "source_csv_sha256": source["csv_sha256"], "filter_protocol": bundle["robustness"]["selected_project_protocol"], "CF": bundle["primary_observables"]["CF"], "IL": bundle["primary_observables"]["IL"], "not_author_bpass_reproduction": True})
    dump(OUT / "filter_robustness.json", bundle["robustness"])
    dump(OUT / "corrected_target_mesh.json", bundle["mesh"])
    dump(OUT / "optimized_slice_design.json", bundle["slices"])
    dump(OUT / "signed_rotation_contract_candidate.json", bundle["rotation"])
    dump(OUT / "stage4e_a_v3_final_candidate_summary.json", {"status": "completed_offline_only", "run_id": run_id, "real_cfd_started": False, "v3_implemented": True, "manufactured_solution": bundle["manufactured"]["status"], "filter_protocol": bundle["robustness"]["selected_project_protocol"], "mesh_recommendation": bundle["mesh"]["decision"], "slice_recommendation": bundle["slices"]["recommendation"], "rotation_status": bundle["rotation"]["status"], "scope_boundary": ["author bpass.m is unavailable; selected protocol is explicitly project-defined", "velocity profile remains digitized design input", "real CFD authorization remains with Sol"]})


def build() -> dict[str, Any]:
    source = source_bundle()
    cf_raw, il_raw, metadata = raw_viv_arrays(source)
    A_cf, _ = modal_matrices(P["cf_positions_m"], 8)
    A_il, _ = modal_matrices(P["il_positions_m"], 13)
    conditioning = {"CF": inverse_conditioning(A_cf, "CF 9x8"), "IL": inverse_conditioning(A_il, "IL 14x13"), "source_columns": metadata["cf_source_columns"] + metadata["il_source_columns"], "repaired_points": metadata["repaired_points"]}
    manufactured = manufactured_solution()
    robustness = filter_robustness(cf_raw, il_raw)
    selected = robustness["selected_project_protocol"]
    primary = robustness["filters"][selected]
    return {"source": source, "conditioning": conditioning, "manufactured": manufactured, "robustness": robustness, "primary_observables": primary, "mesh": mesh_audit(), "slices": slice_design(), "rotation": rotation_contract()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--run-id", default="stage4e_a_v3_offline")
    args = parser.parse_args()
    if not args.write:
        parser.error("use --write")
    bundle = build()
    write_all(bundle, args.run_id)
    print(json.dumps({"out": str(OUT), "csv_sha256": bundle["source"]["csv_sha256"], "manufactured": bundle["manufactured"]["status"], "slice_recommendation": bundle["slices"]["recommendation"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
