"""Reproducible, offline-only audit for the selected VIVdatashare benchmark.

This module intentionally keeps downloaded raw files in a system temporary
directory and writes only metadata, hashes, aggregate statistics and derived
observables to the project results directory.  It never calls OpenFOAM.

The public repository does not contain the author's ``bpass.m`` helper.  The
raw preprocessing is therefore separated from a clearly labelled diagnostic
Butterworth result; the latter must not be presented as an exact reproduction
of the paper's filtered curves.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np

try:
    from scipy.signal import butter, sosfiltfilt, welch
except Exception:  # pragma: no cover - diagnostics require scipy in normal use
    butter = sosfiltfilt = welch = None


REPO_URL = "https://codeload.github.com/xuepengfu/VIVdatashare/zip/refs/heads/main"
REPO_PAGE = "https://github.com/xuepengfu/VIVdatashare"
PAPER_DOI = "https://doi.org/10.1016/j.jfluidstructs.2022.103722"
PAPER_PDF = "https://xuepengfu.github.io/assets/pdf/JFSbiflow.pdf"
NUMERICAL_DOI = "https://doi.org/10.1016/j.marstruc.2025.103895"
CSV_REL = "VIV_Experimental_Results/Bidirectionally_sheared_flow/DSF_S0T1_V048_1.csv"
MAIN_REL = "VIV_Experimental_Results/Bidirectionally_sheared_flow/main1.m"
RAW_CSV_SHA256 = "507b6aadcda9437350c5035db384e7fbbbc0ebe708a6554df851c10498c743df"

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = PROJECT_ROOT / "results" / "08_stage4e_physical_baseline_v2"
DESIGN_RAW = PROJECT_ROOT / "results" / "08_stage4e_physical_baseline" / "ancf_design_raw.json"

PAPER_PARAMETERS = {
    "L_m": 7.64,
    "D_m": 0.02841,
    "dInner_m": 0.025,
    "air_mass_per_length_kgpm": 1.24,
    "top_tension_N": 980.0,
    "EI_Nm2": 58.6,
    "EA_N": 9.4e5,
    "damping_ratio_percent": 2.58,
    "water_density_kgpm3": 1000.0,
    "Umax_mps": 0.48,
    "sampling_Hz": 250.0,
    "dt_s": 0.004,
    "Cm": 1.0,
    "wet_frequencies_experimental_Hz": [1.59, 3.14, 4.78],
    "wet_f1_calculated_Hz": 1.51,
    "cf_sensor_positions_m": [1.21, 1.86, 2.5125, 3.1635, 3.8145, 4.4645, 5.1145, 5.767, 6.417],
    "il_sensor_positions_m": [0.885, 1.336, 1.787, 2.2405, 2.692, 3.1435, 3.595, 4.0465, 4.4955, 4.9505, 5.403, 5.85, 6.305, 6.754],
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def finite_stats(values: np.ndarray) -> dict[str, Any]:
    x = np.asarray(values, dtype=float).ravel()
    finite = np.isfinite(x)
    y = x[finite]
    if y.size == 0:
        return {"count": int(x.size), "finite_count": 0, "nan_or_inf_count": int(x.size)}
    return {
        "count": int(x.size),
        "finite_count": int(y.size),
        "nan_or_inf_count": int(x.size - y.size),
        "mean": float(np.mean(y)),
        "std": float(np.std(y)),
        "rms": float(np.sqrt(np.mean(y * y))),
        "min": float(np.min(y)),
        "max": float(np.max(y)),
        "max_abs": float(np.max(np.abs(y))),
    }


def _download_zip() -> tuple[bytes, str]:
    request = urllib.request.Request(REPO_URL, headers={"User-Agent": "Stage4E-A-v2-offline-audit"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    return data, sha256_bytes(data)


def _zip_member(zf: zipfile.ZipFile, relative: str) -> bytes:
    matches = [name for name in zf.namelist() if name.endswith("/" + relative)]
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one repository member for {relative!r}, found {matches}")
    return zf.read(matches[0])


def load_public_source() -> dict[str, Any]:
    """Download to memory/temp only, parse the selected CSV and return arrays."""
    zip_bytes, zip_sha = _download_zip()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        csv_bytes = _zip_member(zf, CSV_REL)
        main_bytes = _zip_member(zf, MAIN_REL)
    csv_sha = sha256_bytes(csv_bytes)
    if csv_sha != RAW_CSV_SHA256:
        raise RuntimeError(f"selected CSV hash changed: {csv_sha}")
    text = csv_bytes.decode("gb18030")
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 3:
        raise ValueError("CSV has no data rows")
    raw_header = rows[0]
    semantic_header = rows[1]
    data_rows = rows[2:]
    ncol = len(semantic_header)
    if any(len(row) != ncol for row in data_rows):
        raise ValueError("data row column count is not constant")
    matrix = np.asarray([[float(v.strip()) for v in row] for row in data_rows], dtype=float)
    return {
        "repo_zip_sha256": zip_sha,
        "csv_sha256": csv_sha,
        "main1_sha256": sha256_bytes(main_bytes),
        "main1_text": main_bytes.decode("utf-8"),
        "raw_header": raw_header,
        "semantic_header": semantic_header,
        "matrix": matrix,
        "source_time": matrix[:, 2],
        "record_id": matrix[:, 0],
        "test_id": matrix[:, 1],
    }


def schema_audit(source: dict[str, Any]) -> dict[str, Any]:
    matrix = source["matrix"]
    source_time = source["source_time"]
    derived_time = np.arange(matrix.shape[0], dtype=float) / PAPER_PARAMETERS["sampling_Hz"]
    header = source["semantic_header"]
    groups: dict[str, list[int]] = {}
    for label in ("CF1_4", "CF2_4", "CF1_5", "CF2_5", "IL1_6", "IL2_6", "IL1_8", "IL2_8"):
        groups[label] = [i for i, name in enumerate(header) if label in name]
    return {
        "status": "pass",
        "encoding": "gb18030",
        "raw_header_columns": len(source["raw_header"]),
        "semantic_header_columns": len(header),
        "data_rows": int(matrix.shape[0]),
        "data_columns": int(matrix.shape[1]),
        "record_id": {
            "first": int(matrix[0, 0]),
            "last": int(matrix[-1, 0]),
            "strict_unit_increment": bool(np.all(np.diff(matrix[:, 0]) == 1)),
        },
        "test_id": {"unique": sorted({int(x) for x in matrix[:, 1]})},
        "source_time_column": {
            "column_index": 2,
            "unique_count": int(np.unique(source_time).size),
            "min": float(np.min(source_time)),
            "max": float(np.max(source_time)),
            "monotone_non_decreasing": bool(np.all(np.diff(source_time) >= 0)),
            "zero_differences": int(np.count_nonzero(np.diff(source_time) == 0)),
            "one_differences": int(np.count_nonzero(np.diff(source_time) == 1)),
            "interpretation": "quantized source field; not used as physical sample timestamp",
        },
        "derived_index_time": {
            "rule": "t_n = n/Fs, n=0..N-1",
            "Fs_Hz": PAPER_PARAMETERS["sampling_Hz"],
            "dt_s": PAPER_PARAMETERS["dt_s"],
            "first_s": float(derived_time[0]),
            "last_s": float(derived_time[-1]),
        },
        "channel_groups": groups,
        "all_data_finite": bool(np.isfinite(matrix).all()),
        "raw_csv_not_written_to_project": True,
    }


def _find_group(header: list[str], token: str) -> list[int]:
    found = [i for i, name in enumerate(header) if token in name]
    if not found:
        raise KeyError(f"missing channel group {token}")
    return found


def _repair_spikes(x: np.ndarray, threshold: float = 2000.0) -> tuple[np.ndarray, int]:
    y = np.asarray(x, dtype=float).copy()
    bad = np.where(np.abs(y) > threshold)[0]
    repaired = 0
    for i in bad:
        if i >= 2:
            y[i] = y[i - 1] + y[i - 1] - y[i - 2]
            repaired += 1
    return y, repaired


def _diagnostic_filter(x: np.ndarray, fs: float) -> np.ndarray:
    if butter is None or sosfiltfilt is None:
        raise RuntimeError("scipy is required for the diagnostic filter")
    sos = butter(4, [0.01, 20.0], btype="bandpass", fs=fs, output="sos")
    return sosfiltfilt(sos, x, axis=0)


def _dominant_frequency(x: np.ndarray, fs: float) -> tuple[float | None, float | None]:
    if welch is None or x.size < 16:
        return None, None
    f, pxx = welch(x, fs=fs, nperseg=min(8192, x.size), detrend="constant")
    if len(f) < 2:
        return None, None
    k = int(np.argmax(pxx[1:]) + 1)
    return float(f[k]), float(pxx[k])


def _pair_viv(matrix: np.ndarray, header: list[str], ordinal: int, token1: str, token2: str) -> tuple[np.ndarray, dict[str, Any]]:
    group1 = _find_group(header, token1)
    group2 = _find_group(header, token2)
    i1 = group1[ordinal]
    i2 = group2[ordinal]
    a, repair_a = _repair_spikes(matrix[:, i1])
    b, repair_b = _repair_spikes(matrix[:, i2])
    a = a - np.mean(a)
    b = b - np.mean(b)
    return (a - b) / 2.0, {"source_columns": [i1, i2], "repaired_points": repair_a + repair_b}


def _single_viv(matrix: np.ndarray, header: list[str], ordinal: int, token: str) -> tuple[np.ndarray, dict[str, Any]]:
    i = _find_group(header, token)[ordinal]
    a, repairs = _repair_spikes(matrix[:, i])
    baseline_n = min(1000, len(a))
    return a - np.mean(a[:baseline_n]), {"source_column": i, "baseline_samples": baseline_n, "repaired_points": repairs}


def _modal_observables(strain_um: np.ndarray, positions: list[float], L: float, R: float, fs: float) -> dict[str, Any]:
    z = np.linspace(0.0, L, 101)
    max_mode = 8 if len(positions) == 9 else 13
    A = np.asarray([-(k * math.pi / L) ** 2 * np.sin(k * math.pi * np.asarray(positions) / L) for k in range(1, max_mode + 1)]).T * R
    # A maps modal coordinates to sensor strain.  Solve all time samples in
    # one call, retaining the N_time x N_mode orientation used below.
    coeff = np.linalg.lstsq(A, (strain_um * 1e-6).T, rcond=None)[0].T
    displacement_basis = np.sin(np.outer(z, np.arange(1, max_mode + 1)) * math.pi / L)
    displacement = displacement_basis @ coeff.T / (R * 1e6)
    mode_data = []
    for j in range(max_mode):
        freq, power = _dominant_frequency(coeff[:, j], fs)
        mode_data.append({"mode": j + 1, "rms": float(np.sqrt(np.mean(coeff[:, j] ** 2))), "peak_abs": float(np.max(np.abs(coeff[:, j]))), "dominant_frequency_Hz": freq, "dominant_psd": power})
    span_rms = np.sqrt(np.mean(displacement * displacement, axis=0))
    return {
        "sensor_count": len(positions),
        "positions_m": positions,
        "basis_modes": max_mode,
        "modal_coordinate_stats": mode_data,
        "span_rms_displacement_m_by_sample": {
            "max": float(np.max(span_rms)),
            "mean": float(np.mean(span_rms)),
            "midspan": float(span_rms[len(span_rms) // 2]),
        },
        "span_peak_abs_displacement_m": float(np.max(np.abs(displacement))),
        "span_grid_count": int(len(z)),
    }


def process_observables(source: dict[str, Any]) -> dict[str, Any]:
    matrix = source["matrix"]
    header = source["semantic_header"]
    fs = PAPER_PARAMETERS["sampling_Hz"]
    cf_raw = []
    cf_meta = []
    for ordinal in range(4):
        value, meta = _pair_viv(matrix, header, ordinal, "CF1_4", "CF2_4")
        cf_raw.append(value)
        cf_meta.append(meta)
    for ordinal in range(5):
        value, meta = _pair_viv(matrix, header, ordinal, "CF1_5", "CF2_5")
        cf_raw.append(value)
        cf_meta.append(meta)
    il_raw = []
    il_meta = []
    for ordinal in range(6):
        value, meta = _single_viv(matrix, header, ordinal, "IL1_6")
        il_raw.append(value)
        il_meta.append(meta)
    for ordinal in range(8):
        value, meta = _single_viv(matrix, header, ordinal, "IL1_8")
        il_raw.append(value)
        il_meta.append(meta)
    cf_raw_a = np.column_stack(cf_raw)
    il_raw_a = np.column_stack(il_raw)
    cf_filtered = _diagnostic_filter(cf_raw_a, fs)
    il_filtered = _diagnostic_filter(il_raw_a, fs)
    D = PAPER_PARAMETERS["D_m"]
    D1 = PAPER_PARAMETERS["dInner_m"]
    cf_disp = cf_filtered / 1e6 * D / D1
    il_disp = il_filtered / 1e6 * D / D1
    def sensor_stats(a: np.ndarray) -> list[dict[str, Any]]:
        out = []
        for j in range(a.shape[1]):
            freq, power = _dominant_frequency(a[:, j], fs)
            st = finite_stats(a[:, j])
            st.update({"sensor_index": j + 1, "dominant_frequency_Hz": freq, "dominant_psd": power})
            out.append(st)
        return out
    fx = matrix[:, 6] * 9.8
    fy = matrix[:, 7] * 9.8
    fz = matrix[:, 8] / 54.94505495 * 56.17977528 * 9.8
    cf_modal = _modal_observables(cf_filtered, PAPER_PARAMETERS["cf_sensor_positions_m"], PAPER_PARAMETERS["L_m"], D / 2.0, fs)
    il_modal = _modal_observables(il_filtered, PAPER_PARAMETERS["il_sensor_positions_m"], PAPER_PARAMETERS["L_m"], D / 2.0, fs)
    return {
        "status": "completed_with_filter_boundary",
        "source_csv_sha256": source["csv_sha256"],
        "source_main1_sha256": source["main1_sha256"],
        "source_samples": int(matrix.shape[0]),
        "time_rule": "derived_index_time = arange(N)/250; source time column retained only as quantized metadata",
        "preprocessing": {
            "raw_formula": "CF=(CF1-mean(CF1) - (CF2-mean(CF2)))/2; IL=IL1-mean(IL1[0:1000])",
            "spike_rule": "|value|>2000 repaired by x[n]=x[n-1]+x[n-1]-x[n-2], as in main1.m",
            "diagnostic_filter": "4th-order zero-phase Butterworth bandpass 0.01-20 Hz, Fs=250 Hz",
            "filter_equivalence": "not_proven: public repository lacks bpass.m or its documented order/phase",
            "raw_values_preserved_in_processing": True,
        },
        "raw_observables": {
            "cf_microstrain_stats": sensor_stats(cf_raw_a),
            "il_microstrain_stats": sensor_stats(il_raw_a),
            "force_stats_N": {"Fx": finite_stats(fx), "Fy": finite_stats(fy), "Fz": finite_stats(fz)},
            "cf_repair_metadata": cf_meta,
            "il_repair_metadata": il_meta,
        },
        "diagnostic_filtered_observables": {
            "cf_microstrain_stats": sensor_stats(cf_filtered),
            "il_microstrain_stats": sensor_stats(il_filtered),
            "cf_displacement_stats_m": sensor_stats(cf_disp),
            "il_displacement_stats_m": sensor_stats(il_disp),
            "cf_modal": cf_modal,
            "il_modal": il_modal,
        },
        "not_a_raw_data_redistribution": True,
    }


def paper_comparison(processed: dict[str, Any]) -> dict[str, Any]:
    il_modes = processed["diagnostic_filtered_observables"]["il_modal"]["modal_coordinate_stats"]
    cf_modes = processed["diagnostic_filtered_observables"]["cf_modal"]["modal_coordinate_stats"]
    return {
        "source_primary_experiment": {"title": "Vortex-induced vibrations of a flexible pipe in bidirectionally sheared flow", "doi": PAPER_DOI, "author_pdf": PAPER_PDF, "classification": "primary experimental paper"},
        "source_numerical_validation": {"doi": NUMERICAL_DOI, "classification": "numerical validation paper, not the primary experiment"},
        "case": "DSF_S0T1_V048_1 / Umax=0.48 m/s",
        "paper_parameters": PAPER_PARAMETERS,
        "paper_observables": {
            "Vr": 10.54,
            "CF_dominant_mode": 1,
            "IL_dominant_modes": [2, 4],
            "IL_initial_displacement_mode": 2,
            "global_St_CF": 0.10,
            "global_St_IL": 0.24,
            "stable_phase_periods": "approximately 50-100 periods from paper discussion",
            "reported_max_RMS_discrepancy": {"abstract_D": {"CF": 0.51, "IL": 0.18}, "body_D": {"CF": 0.57, "IL": 0.11}},
            "exact_U048_numeric_RMS_in_text": False,
        },
        "repository_observables": {
            "diagnostic_filter_not_official": True,
            "cf_mode_1": cf_modes[0],
            "il_mode_2": il_modes[1],
            "il_mode_4": il_modes[3],
        },
        "comparison_status": "qualitative_target_mode_and_frequency_comparison_only_until_bpass_is_obtained",
        "data_availability_boundary": "paper says data used are confidential; repository makes selected files available after negotiation; permission must be obtained before redistribution or publication of derived curves.",
    }


def _get_config() -> dict[str, Any]:
    data = json.loads(DESIGN_RAW.read_text(encoding="utf-8"))
    for config in data["configurations"]:
        if config.get("id") == "public_vivdatashare_bidirectional":
            return config
    raise KeyError("public_vivdatashare_bidirectional not in read-only ANCF design evidence")


def _pair_summary(freq: list[float], start: int) -> float:
    return float(np.mean(np.asarray(freq[start:start + 2], dtype=float)))


def _subspace(a: np.ndarray) -> np.ndarray:
    return np.linalg.qr(a)[0]


def _subspace_metrics(a: np.ndarray, b: np.ndarray, sample_s: np.ndarray, probe_s: Iterable[float], directions_a: list[int] | None = None, directions_b: list[int] | None = None) -> dict[str, Any]:
    # A scalar displacement sample cannot distinguish the two members of a
    # repeated x/y eigenvalue.  Lift each column into its physical direction
    # block before computing subspace angles; this is the direction-aware
    # equivalent of comparing the H-interpolated vector motion.
    lifted = directions_a is not None and directions_b is not None
    if lifted:
        n = len(sample_s)
        aa = np.zeros((2 * n, a.shape[1]))
        bb = np.zeros((2 * n, b.shape[1]))
        for j, d in enumerate(directions_a):
            aa[(int(d) - 1) * n:int(d) * n, j] = a[:, j]
        for j, d in enumerate(directions_b):
            bb[(int(d) - 1) * n:int(d) * n, j] = b[:, j]
    else:
        aa, bb = a, b
    qa, qb = _subspace(aa), _subspace(bb)
    singular = np.linalg.svd(qa.T @ qb, compute_uv=False)
    singular = np.clip(singular, 0.0, 1.0)
    probes = []
    for s in probe_s:
        idx = int(np.argmin(np.abs(sample_s - s)))
        if lifted:
            row_diffs = []
            for d in (0, 1):
                pa = qa[d * len(sample_s) + idx, :]
                pb = qb[d * len(sample_s) + idx, :]
                row_diffs.append(float(np.linalg.norm(np.outer(pa, pa) - np.outer(pb, pb))))
            probe_value = max(row_diffs)
        else:
            pa = qa[idx, :]
            pb = qb[idx, :]
            probe_value = float(np.linalg.norm(np.outer(pa, pa) - np.outer(pb, pb)))
        probes.append({"s_m": float(sample_s[idx]), "projector_row_norm_difference": probe_value})
    return {
        "principal_angle_max_deg": float(np.degrees(np.arccos(singular.min()))),
        "principal_angle_min_deg": float(np.degrees(np.arccos(singular.max()))),
        "singular_cosines": [float(x) for x in singular],
        "subspace_MAC_mean": float(np.mean(singular * singular)),
        "subspace_MAC_min": float(np.min(singular * singular)),
        "H_interpolated_probe_metrics": probes,
    }


def wet_modal_validation() -> dict[str, Any]:
    config = _get_config()
    results = {int(r["nElem"]): r for r in config["results"]}
    n16 = results[16]
    dry = np.asarray(n16["dry_frequency_Hz"], dtype=float)
    wet_ca1 = np.asarray(config["wet_frequency_sensitivity"]["candidates"][1], dtype=float)
    exp = np.asarray(PAPER_PARAMETERS["wet_frequencies_experimental_Hz"], dtype=float)
    paper_calc = np.asarray([PAPER_PARAMETERS["wet_f1_calculated_Hz"], np.nan, np.nan])
    return {
        "status": "diagnostic_added_mass_only",
        "equation": "m_wet_per_length = m_air_per_length + 0.25*Cm*rho*pi*D^2",
        "Cm": 1.0,
        "calculated_and_measured_are_separate": True,
        "experimental_wet_frequencies_Hz": exp.tolist(),
        "paper_calculated_wet_f1_Hz": PAPER_PARAMETERS["wet_f1_calculated_Hz"],
        "ancf_nElem16_dry_frequencies_Hz": dry[:6].tolist(),
        "ancf_nElem16_Cm1_estimated_wet_frequencies_Hz": wet_ca1[:6].tolist(),
        "relative_error_Cm1_vs_experiment_first_three": ((wet_ca1[[0, 2, 4]] - exp) / exp).tolist(),
        "relative_error_paper_calculated_f1_vs_experiment": float((PAPER_PARAMETERS["wet_f1_calculated_Hz"] - exp[0]) / exp[0]),
        "relative_error_Cm1_f1_vs_paper_calculated": float((wet_ca1[0] - PAPER_PARAMETERS["wet_f1_calculated_Hz"]) / PAPER_PARAMETERS["wet_f1_calculated_Hz"]),
        "added_mass_matrix_status": "not_implemented_in_this_offline_audit",
        "interpretation": "Ca=1 is a sensitivity estimate and is not a validated wet ANCF model; do not overwrite the paper measured or calculated frequencies.",
    }


def target_mode_mesh_convergence() -> dict[str, Any]:
    config = _get_config()
    results = {int(r["nElem"]): r for r in config["results"]}
    target = {"CF_order1": (0, 2), "IL_order2": (2, 4), "IL_order4": (6, 8)}
    out = {"criterion": "target experiment-excited modal subspaces; frequency <=1% for target modes; H-interpolated shape subspace audit", "target_modes": target, "models": {}}
    for ne, result in results.items():
        out["models"][str(ne)] = {
            "nElem": ne,
            "nNode": result["nNode"],
            "ndof": result["ndof"],
            "frequencies_target_Hz": {name: _pair_summary(result["dry_frequency_Hz"], pair[0]) for name, pair in target.items()},
        }
    sample_s = np.asarray(results[16]["modal_shape_samples_s_m"], dtype=float)
    for coarse, fine in ((4, 8), (8, 16)):
        pair_metrics = {}
        for name, (start, stop) in target.items():
            a = np.asarray(results[coarse]["modal_shape_samples"], dtype=float)[:, start:stop]
            b = np.asarray(results[fine]["modal_shape_samples"], dtype=float)[:, start:stop]
            f0 = _pair_summary(results[coarse]["dry_frequency_Hz"], start)
            f1 = _pair_summary(results[fine]["dry_frequency_Hz"], start)
            metric = _subspace_metrics(a, b, sample_s, [0.25 * PAPER_PARAMETERS["L_m"], 0.5 * PAPER_PARAMETERS["L_m"], 0.75 * PAPER_PARAMETERS["L_m"]], results[coarse]["dry_mode_direction_xy"][start:stop], results[fine]["dry_mode_direction_xy"][start:stop])
            metric.update({"coarse_nElem": coarse, "fine_nElem": fine, "frequency_coarse_Hz": f0, "frequency_fine_Hz": f1, "frequency_relative_change": abs(f0 - f1) / abs(f1)})
            pair_metrics[name] = metric
        out[f"comparison_{coarse}_vs_{fine}"] = pair_metrics
    out["decision"] = {
        "nElem4_vs_nElem8_target_mode_frequency_pass": bool(all(v["frequency_relative_change"] <= 0.01 for v in out["comparison_4_vs_8"].values())),
        "nElem8_vs_nElem16_target_mode_frequency_pass": bool(all(v["frequency_relative_change"] <= 0.01 for v in out["comparison_8_vs_16"].values())),
        "recommended_minimum_target_mode_nElem": 8,
        "reference_nElem": 16,
        "nElem4_failure_reason": "IL order-4 target frequency change exceeds the 1% target-mode criterion; the obsolete all-retained-mode criterion is not used.",
        "nElem32_required": False,
    }
    return out


# Approximate digitization of Fig. 1(b) from the author PDF.  Values are
# normalized to the largest absolute digitized velocity before scaling to
# Umax=.48 m/s.  They are a design shape, not a substitute for the raw profile.
PROFILE_DIGITIZED = {
    "source": PAPER_PDF,
    "figure": "Fig. 1(b)",
    "method": "manual pixel digitization of red curve; depth and velocity uncertainty retained",
    "depth_fraction": [0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0],
    "velocity_mmps": [1095.0, 1365.0, 1135.0, 560.0, -145.0, -400.0, -470.0, -410.0, -370.0],
    "velocity_uncertainty_mmps": 25.0,
    "depth_fraction_uncertainty": 0.015,
    "scale_rule": "shape = digitized velocity / max(abs(digitized velocity)); Ulocal = .48*shape",
}


def _profile_value(frac: np.ndarray) -> np.ndarray:
    x = np.asarray(PROFILE_DIGITIZED["depth_fraction"], dtype=float)
    u = np.asarray(PROFILE_DIGITIZED["velocity_mmps"], dtype=float)
    return np.interp(frac, x, u / np.max(np.abs(u)))


def bidirectional_slice_design() -> dict[str, Any]:
    L, D, Umax, rho, nu = 7.64, 0.02841, 0.48, 1000.0, 1.0e-6
    dense = np.linspace(0, 1, 10001)
    shape = _profile_value(dense)
    def integral(values: np.ndarray) -> float:
        return float(np.trapz(values, dense) * L)
    exact = {"int_abs_U_m2ps": integral(np.abs(Umax * shape)), "int_U2_m3ps2": integral((Umax * shape) ** 2), "int_signed_U_m2ps": integral(Umax * shape)}
    designs: dict[str, Any] = {}
    for n in (3, 5, 7, 9):
        centers = (np.arange(n) + 0.5) / n
        widths = np.full(n, 1.0 / n)
        local_shape = _profile_value(centers)
        local_u = Umax * local_shape
        cells = []
        for j, (c, w, u) in enumerate(zip(centers, widths, local_u)):
            cells.append({"slice_id": j, "s_ref_m": float(c * L), "slice_length_m": float(w * L), "Ulocal_mps": float(u), "Ulocal_over_Umax": float(u / Umax), "flow_sign": "positive" if u > 0 else "negative" if u < 0 else "zero", "crosses_zero_within_slice": bool((_profile_value(np.array([c - w / 2, c + w / 2])) <= 0).any() and (_profile_value(np.array([c - w / 2, c + w / 2])) >= 0).any()), "Re_abs_assuming_nu_1e-6": float(abs(u) * D / nu), "Re_note": "illustrative only; nu is not specified in the paper table"})
        approx = {"int_abs_U_m2ps": float(np.sum(np.abs(local_u) * widths) * L), "int_U2_m3ps2": float(np.sum(local_u ** 2 * widths) * L), "int_signed_U_m2ps": float(np.sum(local_u * widths) * L)}
        errors = {k + "_relative_error": abs(approx[k] - exact[k]) / max(abs(exact[k]), 1e-15) for k in exact}
        designs[str(n)] = {"n_slices": n, "slices": cells, "integral_proxy": approx, "relative_errors_vs_dense": errors}
    chosen = next((n for n in (5, 7, 9) if designs[str(n)]["relative_errors_vs_dense"]["int_abs_U_m2ps_relative_error"] <= 0.05 and designs[str(n)]["relative_errors_vs_dense"]["int_U2_m3ps2_relative_error"] <= 0.05), None)
    return {
        "status": "offline_design_only",
        "geometry": {"L_m": L, "D_m": D, "Umax_mps": Umax, "water_rho_kgpm3": rho, "nu_assumed_m2ps": nu},
        "profile": PROFILE_DIGITIZED,
        "profile_scaling_boundary": "The PDF curve is digitized as a signed shape and scaled to .48 m/s only for slice-design diagnostics; this is not an independently validated pointwise velocity field.",
        "dense_integrals": exact,
        "slice_designs": designs,
        "recommended_minimum_quadrature_slices_for_absU_and_U2_5pct": chosen,
        "future_cfd_alternatives": ["signed global velocity per slice, preserving bidirectional flow", "local positive-flow coordinate plus explicit R_GL/back-transform; requires Sol protocol decision"],
        "current_R_GL_I_warning": "Do not use R_GL=I with signed local profile without deciding coordinate/sign convention.",
    }


def cost_estimate() -> dict[str, Any]:
    baseline = {"source": "Stage 4D-B formal 100-step run", "slices": 3, "steps": 100, "dt_s": 0.0025, "wall_s": 720.263, "result_dir_bytes": 577 * 1024 * 1024}
    estimates = {}
    # Experimental wet f1 gives the structural period; St values give two
    # flow-oscillation periods. These are planning scales, not runtime claims.
    periods = {"wet_f1_period_s": 1 / 1.59, "CF_shedding_period_s": PAPER_PARAMETERS["D_m"] / (0.10 * PAPER_PARAMETERS["Umax_mps"]), "IL_shedding_period_s": PAPER_PARAMETERS["D_m"] / (0.24 * PAPER_PARAMETERS["Umax_mps"])}
    for n in (5, 7, 9):
        per_step = baseline["wall_s"] / baseline["steps"] * n / baseline["slices"]
        estimates[str(n)] = {"estimated_wall_s_per_global_step": per_step, "estimated_result_bytes_per_step": baseline["result_dir_bytes"] / baseline["steps"] * n / baseline["slices"], "estimated_10_wet_f1_periods_wall_h": per_step * math.ceil(10 * periods["wet_f1_period_s"] / baseline["dt_s"]) / 3600, "estimated_20_wet_f1_periods_wall_h": per_step * math.ceil(20 * periods["wet_f1_period_s"] / baseline["dt_s"]) / 3600, "estimated_50_wet_f1_periods_wall_h": per_step * math.ceil(50 * periods["wet_f1_period_s"] / baseline["dt_s"]) / 3600, "estimate_boundary": "linear slice/step extrapolation from Stage 4D-B; no new CFD run"}
    return {"status": "planning_estimate_only", "baseline": baseline, "period_scales": periods, "slice_count_estimates": estimates, "architecture_options": ["persistent OpenFOAM slice worker per case", "segmented continuous OpenFOAM execution with global barriers", "reduced checkpoint frequency only after a separate atomic-checkpoint protocol review"], "current_bottleneck": "Stage 4D-B restarts OpenFOAM for each slice-step; this is not a production long-run architecture."}


def build_all() -> dict[str, Any]:
    source = load_public_source()
    schema = schema_audit(source)
    processed = process_observables(source)
    comparison = paper_comparison(processed)
    wet = wet_modal_validation()
    mesh = target_mode_mesh_convergence()
    slices = bidirectional_slice_design()
    costs = cost_estimate()
    return {"source": source, "schema": schema, "processed": processed, "paper": comparison, "wet": wet, "mesh": mesh, "slices": slices, "costs": costs}


def write_outputs(bundle: dict[str, Any], run_id: str = "stage4e_a_v2_offline") -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    source = bundle["source"]
    source_correction = {
        "schema_version": "0.2.1",
        "run_id": run_id,
        "primary_benchmark": "vivdatashare_bidirectional_shear_v048",
        "source_classification": {"Fu2022_JFS_103722": "primary experiment", "Fu2025_MarineStructures_103895": "numerical validation paper", "VIVdatashare": "repository with selected experiment data and numerical code"},
        "sources": {"repository": REPO_PAGE, "paper_doi": PAPER_DOI, "paper_pdf": PAPER_PDF, "numerical_validation_doi": NUMERICAL_DOI},
        "selected_csv": {"repository_path": CSV_REL, "sha256": source["csv_sha256"], "expected_sha256": RAW_CSV_SHA256, "raw_csv_written_to_project": False},
        "correction": "The 2022 paper is the primary experiment; the 2025 paper is numerical validation. This correction is frozen in the v2 audit and does not overwrite v1 evidence.",
        "real_cfd_started": False,
    }
    license_boundary = {
        "repository": REPO_PAGE,
        "license_file_observed": False,
        "public_access_is_not_a_license": True,
        "paper_data_availability_statement": "paper states data used are confidential",
        "repository_boundary": "README says experiment data are available after negotiation; selected files are present in repository",
        "allowed_now": ["offline metadata audit", "hashing", "aggregate statistics", "non-redistributive derived observables", "permission-request draft"],
        "not_allowed_without_permission": ["redistributing raw CSV", "publishing raw or near-raw curves", "asserting exact paper preprocessing without bpass.m", "sending an email automatically"],
        "permission_status": "not_obtained; draft only",
        "derived_outputs_are_aggregate_only": True,
    }
    freeze = {
        "status": "conditionally_frozen_offline_only",
        "benchmark_id": "vivdatashare_bidirectional_shear_v048",
        "protocol_version": "0.2.1",
        "selection": "primary conditional benchmark; no real CFD authorization",
        "conditions": ["obtain permission/usage clarification", "obtain exact bpass.m or document an accepted replacement", "freeze signed velocity-profile convention before CFD", "keep source and paper classifications separate"],
        "fallback": "chaplin_huera_delfta_stepped_current",
        "real_cfd_started": False,
    }
    for filename, value in {
        "source_correction_v2.json": source_correction,
        "license_and_use_boundary.json": license_boundary,
        "csv_schema_audit.json": bundle["schema"],
        "processed_observables_v048.json": bundle["processed"],
        "paper_observable_comparison.json": bundle["paper"],
        "wet_modal_validation.json": bundle["wet"],
        "target_mode_mesh_convergence.json": bundle["mesh"],
        "bidirectional_slice_design.json": bundle["slices"],
        "cost_and_architecture_estimate.json": bundle["costs"],
        "primary_benchmark_freeze_candidate_v2.json": freeze,
    }.items():
        json_dump(RESULTS_DIR / filename, value)
    summary = {
        "status": "partially_completed",
        "run_id": run_id,
        "real_cfd_started": False,
        "blocking_items": ["exact public bpass.m preprocessing unavailable", "data-use permission not obtained", "velocity profile is digitized design shape with uncertainty", "no real CFD authorized in this task"],
        "outputs": sorted(p.name for p in RESULTS_DIR.glob("*.json")),
        "benchmark": freeze,
    }
    json_dump(RESULTS_DIR / "stage4e_a_v2_candidate_summary.json", summary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="download and write aggregate audit outputs")
    parser.add_argument("--run-id", default="stage4e_a_v2_offline")
    args = parser.parse_args()
    if not args.write:
        parser.error("use --write to run the explicit offline audit")
    bundle = build_all()
    write_outputs(bundle, args.run_id)
    print(json.dumps({"results_dir": str(RESULTS_DIR), "csv_sha256": bundle["source"]["csv_sha256"], "data_rows": bundle["schema"]["data_rows"], "recommended_slices": bundle["slices"]["recommended_minimum_quadrature_slices_for_absU_and_U2_5pct"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
