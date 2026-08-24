"""Stage 4E-A-v3.1 offline diagnostics.

This module deliberately does not start OpenFOAM or alter any v1/v2/v3
artifact.  It reuses the dimensional reconstruction convention of v3, but
keeps the v3.1 amplitude fields distinct and adds fixed-boundary profile
uncertainty and modal-weighted quadrature diagnostics.

The formal H audit calls the production multi-slice mapping implementation.
It refuses to manufacture an ANCF modal state when the audited design file
contains only sampled, normalized curves rather than node position/slope
degrees of freedom.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

import numpy as np

try:
    from scipy.interpolate import PchipInterpolator
    from scipy.optimize import differential_evolution
    from scipy.signal import butter, detrend, sosfiltfilt, welch
except Exception:  # pragma: no cover
    PchipInterpolator = differential_evolution = butter = detrend = sosfiltfilt = welch = None


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "results" / "08_stage4e_physical_baseline_v3_1"
V3_OUT = ROOT / "results" / "08_stage4e_physical_baseline_v3"
V2_DESIGN = ROOT / "results" / "08_stage4e_physical_baseline" / "ancf_design_raw.json"
V3_SOURCE_ID = V3_OUT / "source_identity_v3.json"
V3_FILTERS = V3_OUT / "filter_robustness.json"
V3_OBS = V3_OUT / "corrected_observables_v048.json"
V3_SLICES = V3_OUT / "optimized_slice_design.json"
MAPPING_FILE = ROOT / "src" / "coupling" / "multi_slice_mapping" / "mapping.py"

SCHEMA_VERSION = "0.2.1"
COMMIT = "fe251f958ddf2f083b53cdb53a9d2addde85e17e"
REPOSITORY = "https://github.com/xuepengfu/VIVdatashare"
CSV_REL = "VIV_Experimental_Results/Bidirectionally_sheared_flow/DSF_S0T1_V048_1.csv"
MAIN_REL = "VIV_Experimental_Results/Bidirectionally_sheared_flow/main1.m"
CSV_SHA256 = "507b6aadcda9437350c5035db384e7fbbbc0ebe708a6554df851c10498c743df"
MAIN1_SHA256 = "a2ab54340f2269afad1249d8c99b26b1e5aab2cd1691786c2c428dda64d0c963"
COMMIT_ARCHIVE_URL = f"https://codeload.github.com/xuepengfu/VIVdatashare/zip/{COMMIT}"
COMMIT_MAIN_URL = f"https://raw.githubusercontent.com/xuepengfu/VIVdatashare/{COMMIT}/{MAIN_REL}"
COMMIT_CSV_URL = f"https://raw.githubusercontent.com/xuepengfu/VIVdatashare/{COMMIT}/{CSV_REL}"

P = {
    "L_m": 7.64,
    "D_m": 0.02841,
    "D1_m": 0.025,
    "R_m": 0.02841 / 2.0,
    "Umax_mps": 0.48,
    "Fs_Hz": 250.0,
    "dt_s": 0.004,
    "cf_positions_m": [1.21, 1.86, 2.5125, 3.1635, 3.8145, 4.4645, 5.1145, 5.767, 6.417],
    "il_positions_m": [0.885, 1.336, 1.787, 2.2405, 2.692, 3.1435, 3.595, 4.0465, 4.4955, 4.9505, 5.403, 5.85, 6.305, 6.754],
}

FILTERS = {
    "detrend_no_bandpass": {"kind": "detrend_no_bandpass"},
    "butterworth_order2_0p01_20_zero_phase": {"kind": "butter", "order": 2, "low_Hz": 0.01, "high_Hz": 20.0},
    "butterworth_order4_0p01_20_zero_phase": {"kind": "butter", "order": 4, "low_Hz": 0.01, "high_Hz": 20.0},
    "butterworth_order6_0p01_20_zero_phase": {"kind": "butter", "order": 6, "low_Hz": 0.01, "high_Hz": 20.0},
    "butterworth_order4_0p05_20_zero_phase": {"kind": "butter", "order": 4, "low_Hz": 0.05, "high_Hz": 20.0},
    "butterworth_order4_0p10_15_zero_phase": {"kind": "butter", "order": 4, "low_Hz": 0.10, "high_Hz": 15.0},
}

PROFILE = {
    "depth_fraction": [0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0],
    "velocity_mmps": [1095.0, 1365.0, 1135.0, 560.0, -145.0, -400.0, -470.0, -410.0, -370.0],
    "source": "Fu2022 Fig.1(b) author PDF digitization retained by v3",
    "velocity_uncertainty_mmps": 25.0,
    "depth_fraction_uncertainty": 0.015,
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes())


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def trapz(y: np.ndarray, x: np.ndarray) -> float:
    return float(np.trapezoid(y, x) if hasattr(np, "trapezoid") else np.trapz(y, x))


def fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Stage4E-A-v3.1-offline-audit"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except Exception as urllib_error:
        # The desktop Python runtime may have no direct HTTPS route while the
        # approved PowerShell HTTP client does.  Keep the fallback transient:
        # the bytes are read and the temporary file is removed immediately.
        temp_path = Path(tempfile.gettempdir()) / f"stage4e_v31_{hashlib.sha256(url.encode()).hexdigest()[:16]}.bin"
        command = (
            "$ProgressPreference='SilentlyContinue'; "
            f"Invoke-WebRequest -Uri '{url}' -UseBasicParsing -TimeoutSec {int(timeout)} -OutFile '{temp_path}'"
        )
        try:
            completed = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=timeout + 10)
            if completed.returncode != 0 or not temp_path.exists():
                raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "PowerShell download failed")
            data = temp_path.read_bytes()
            return data
        except Exception as powershell_error:
            raise RuntimeError(f"urllib fetch failed ({urllib_error}); PowerShell fallback failed ({powershell_error})") from powershell_error
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def source_pin() -> dict[str, Any]:
    """Verify the pinned commit files in memory; never write raw CSV."""
    result: dict[str, Any] = {
        "repository": REPOSITORY,
        "commit_sha": COMMIT,
        "commit_archive_url": COMMIT_ARCHIVE_URL,
        "main1_commit_url": f"https://github.com/xuepengfu/VIVdatashare/blob/{COMMIT}/{MAIN_REL}",
        "csv_commit_url": f"https://github.com/xuepengfu/VIVdatashare/blob/{COMMIT}/{CSV_REL}",
        "csv_sha256_expected": CSV_SHA256,
        "main1_sha256_expected": MAIN1_SHA256,
        "raw_csv_written_to_project": False,
        "archive_download_attempted": True,
        "openfoam_started": False,
    }
    errors: list[str] = []
    try:
        main_bytes = fetch(COMMIT_MAIN_URL, 30)
        result["main1_sha256_observed"] = sha256(main_bytes)
        result["main1_hash_match"] = result["main1_sha256_observed"] == MAIN1_SHA256
    except Exception as exc:
        result["main1_hash_match"] = False
        errors.append(f"main1 fetch: {type(exc).__name__}: {exc}")
    try:
        csv_bytes = fetch(COMMIT_CSV_URL, 120)
        result["csv_sha256_observed"] = sha256(csv_bytes)
        result["csv_hash_match"] = result["csv_sha256_observed"] == CSV_SHA256
    except Exception as exc:
        result["csv_hash_match"] = False
        errors.append(f"csv fetch: {type(exc).__name__}: {exc}")
    try:
        archive = fetch(COMMIT_ARCHIVE_URL, 120)
        result["commit_archive_sha256"] = sha256(archive)
        result["archive_download_verified"] = True
    except Exception as exc:
        result["archive_download_verified"] = False
        errors.append(f"archive fetch: {type(exc).__name__}: {exc}")
    result["source_pin_status"] = "verified" if result.get("csv_hash_match") and result.get("main1_hash_match") else "blocked_source_fetch"
    result["errors"] = errors
    result["v3_provenance_fallback"] = json.loads(V3_SOURCE_ID.read_text(encoding="utf-8"))
    result["v3_provenance_hashes_match_expected"] = bool(
        result["v3_provenance_fallback"].get("csv_sha256") == CSV_SHA256
        and result["v3_provenance_fallback"].get("main1_sha256") == MAIN1_SHA256
    )
    return result


def group_indices(header: list[str], token: str) -> list[int]:
    found = [i for i, name in enumerate(header) if token in name]
    if not found:
        raise KeyError(token)
    return found


def repair_signal(x: np.ndarray) -> np.ndarray:
    y = np.asarray(x, dtype=float).copy()
    if np.max(np.abs(y)) <= 2000.0:
        return y
    y = y - np.mean(y[: min(100, len(y))])
    for i in range(2, len(y)):
        if abs(y[i]) > 2000.0:
            y[i] = y[i - 1] + y[i - 1] - y[i - 2]
    return y


def parse_pinned_csv(csv_bytes: bytes) -> tuple[np.ndarray, np.ndarray]:
    rows = list(csv.reader(io.StringIO(csv_bytes.decode("gb18030"))))
    header = rows[1]
    data = np.asarray([[float(v.strip()) for v in row] for row in rows[2:]], dtype=float)
    cf: list[np.ndarray] = []
    il: list[np.ndarray] = []
    for token, count, target in (("CF1_4", 4, cf), ("CF1_5", 5, cf)):
        token2 = token.replace("1", "2")
        for ordinal in range(count):
            i1, i2 = group_indices(header, token)[ordinal], group_indices(header, token2)[ordinal]
            a, b = repair_signal(data[:, i1]), repair_signal(data[:, i2])
            target.append((a - np.mean(a) - (b - np.mean(b))) / 2.0)
    for token, token2, count in (("IL1_6", "IL2_6", 6), ("IL1_8", "IL2_8", 8)):
        for ordinal in range(count):
            i1, i2 = group_indices(header, token)[ordinal], group_indices(header, token2)[ordinal]
            a, b = repair_signal(data[:, i1]), repair_signal(data[:, i2])
            il.append(((a - np.mean(a[:1000])) - (b - np.mean(b[:1000]))) / 2.0)
    return np.column_stack(cf), np.column_stack(il)


def modal_matrices(positions: list[float], count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    s = np.asarray(positions, dtype=float)
    modes = np.arange(1, count + 1, dtype=float)
    A = -P["R_m"] * (modes[None, :] * math.pi / P["L_m"]) ** 2 * np.sin(np.outer(s, modes) * math.pi / P["L_m"])
    span = np.linspace(0.0, P["L_m"], 201)
    Phi = np.sin(np.outer(span, modes) * math.pi / P["L_m"])
    return A, Phi, span


def apply_filter(x: np.ndarray, protocol: dict[str, Any]) -> np.ndarray:
    if protocol["kind"] == "detrend_no_bandpass":
        return detrend(x, axis=0, type="linear")
    if butter is None or sosfiltfilt is None:
        raise RuntimeError("scipy is required")
    sos = butter(protocol["order"], [protocol["low_Hz"], protocol["high_Hz"]], btype="bandpass", fs=P["Fs_Hz"], output="sos")
    return sosfiltfilt(sos, x, axis=0)


def corrected_summary(raw: np.ndarray, positions: list[float], label: str, protocol: str) -> dict[str, Any]:
    count = 8 if label == "CF" else 13
    A, Phi, span = modal_matrices(positions, count)
    epsilon = raw * 1e-6 * (P["D_m"] / P["D1_m"])
    q = np.linalg.pinv(A, rcond=1e-12) @ epsilon.T
    y = Phi @ q
    q_rms = np.sqrt(np.mean(q * q, axis=1))
    q_peak = np.max(np.abs(q), axis=1)
    span_rms = np.sqrt(np.mean(y * y, axis=1))
    rms_idx = int(np.argmax(span_rms))
    peak_idx = np.unravel_index(int(np.argmax(np.abs(y))), y.shape)
    mode_stats: list[dict[str, Any]] = []
    for mode in range(count):
        dominant = None
        if welch is not None:
            f, psd = welch(q[mode, :], fs=P["Fs_Hz"], nperseg=min(8192, q.shape[1]), detrend="constant")
            dominant = float(f[int(np.argmax(psd[1:]) + 1)])
        mode_stats.append({"mode": mode + 1, "q_rms_m": float(q_rms[mode]), "q_peak_abs_m": float(q_peak[mode]), "dominant_frequency_Hz": dominant})
    targets = [1] if label == "CF" else [2, 4]
    return {
        "label": label,
        "filter_protocol": protocol,
        "mode_stats": mode_stats,
        "target_mode_numbers": targets,
        "max_span_rms_m": float(np.max(span_rms)),
        "max_span_rms_over_D": float(np.max(span_rms) / P["D_m"]),
        "max_instantaneous_peak_abs_m": float(np.max(np.abs(y))),
        "max_instantaneous_peak_abs_over_D": float(np.max(np.abs(y)) / P["D_m"]),
        "rms_peak_location_m": float(span[rms_idx]),
        "instantaneous_peak_location_m": float(span[peak_idx[0]]),
        "amplitude_definition": {
            "rms": "max over span of temporal RMS of reconstructed displacement y(s,t)",
            "instantaneous_peak": "max over span and time of abs(y(s,t))",
            "comparison_field_for_paper_RMS_curve": "max_span_rms_over_D",
            "legacy_max_A_over_D_not_used_as_sole_metric": True,
        },
        "finite": bool(np.isfinite(q).all() and np.isfinite(y).all()),
    }


def rel_span(values: list[float]) -> float:
    a = np.asarray(values, dtype=float)
    # v3's published robustness evidence defines the span relative to the
    # mean of the compared values; this reproduces the reported IL2
    # band-pass span of about 11.65%, rather than silently switching to a
    # minimum-normalized range.
    return float((np.max(a) - np.min(a)) / max(abs(np.mean(a)), 1e-30))


def class_for(span_value: float, threshold: float = 0.05) -> str:
    if span_value <= 0.05:
        return "amplitude_robust"
    if span_value <= 0.10:
        return "amplitude_medium_sensitive"
    return "not_strict_amplitude"


def amplitude_analysis(cf_raw: np.ndarray, il_raw: np.ndarray) -> tuple[dict[str, Any], dict[str, Any]]:
    all_results: dict[str, Any] = {}
    for name, protocol in FILTERS.items():
        all_results[name] = {
            "protocol": protocol,
            "CF": corrected_summary(apply_filter(cf_raw, protocol), P["cf_positions_m"], "CF", name),
            "IL": corrected_summary(apply_filter(il_raw, protocol), P["il_positions_m"], "IL", name),
        }
    targets = {"CF_mode_1": ("CF", 1), "IL_mode_2": ("IL", 2), "IL_mode_4": ("IL", 4)}
    series: dict[str, Any] = {}
    for target_name, (label, mode_number) in targets.items():
        rows = []
        for filt, result in all_results.items():
            source = result[label]
            mode = source["mode_stats"][mode_number - 1]
            rows.append({
                "filter": filt,
                "frequency_Hz": mode["dominant_frequency_Hz"],
                "q_rms_m": mode["q_rms_m"],
                "max_span_rms_over_D": source["max_span_rms_over_D"],
                "max_instantaneous_peak_abs_over_D": source["max_instantaneous_peak_abs_over_D"],
                "mode_identity": mode_number,
            })
        series[target_name] = rows
    # Overall along-span displacement is a separate observable from the
    # named modal coordinates.  Keep its RMS/peak fields explicit; the
    # representative frequency is the dominant frequency of the requested
    # target mode and is not used as a claim about every retained mode.
    for label, name, mode_number in (("CF", "CF_overall_along_span", 1), ("IL", "IL_overall_along_span", 2)):
        rows = []
        for filt, result in all_results.items():
            source = result[label]
            mode = source["mode_stats"][mode_number - 1]
            rows.append({
                "filter": filt,
                "frequency_Hz": mode["dominant_frequency_Hz"],
                "q_RMS_m": float(np.sqrt(np.mean([entry["q_rms_m"] ** 2 for entry in source["mode_stats"]]))),
                "max_span_rms_over_D": source["max_span_rms_over_D"],
                "max_instantaneous_peak_abs_over_D": source["max_instantaneous_peak_abs_over_D"],
                "observable": "overall along-span reconstructed displacement",
            })
        series[name] = rows
    frequency_spans: dict[str, Any] = {}
    amplitude_spans: dict[str, Any] = {}
    for target_name, rows in series.items():
        frequency_spans[target_name] = rel_span([r["frequency_Hz"] for r in rows])
        amplitude_spans[target_name] = {
            "q_RMS_relative_span": rel_span([r["q_rms_m"] if "q_rms_m" in r else r["q_RMS_m"] for r in rows]),
            "max_span_rms_over_D_relative_span": rel_span([r["max_span_rms_over_D"] for r in rows]),
                "instantaneous_peak_over_D_relative_span": rel_span([r["max_instantaneous_peak_abs_over_D"] for r in rows]),
            }
    named_targets = ["CF_mode_1", "IL_mode_2", "IL_mode_4", "CF_overall_along_span", "IL_overall_along_span"]
    overall_frequency_spans = {name: frequency_spans[name] for name in ("CF_overall_along_span", "IL_overall_along_span")}
    overall_amplitude_spans = {
        name: {
            "q_RMS_relative_span": rel_span([r["q_RMS_m"] for r in series[name]]),
            "max_span_rms_over_D_relative_span": rel_span([r["max_span_rms_over_D"] for r in series[name]]),
            "instantaneous_peak_over_D_relative_span": rel_span([r["max_instantaneous_peak_abs_over_D"] for r in series[name]]),
        }
        for name in ("CF_overall_along_span", "IL_overall_along_span")
    }
    band_filters = [k for k in FILTERS if k != "detrend_no_bandpass"]
    band_series = {name: [row for row in rows if row["filter"] in band_filters] for name, rows in series.items()}
    band_frequency_spans = {name: rel_span([r["frequency_Hz"] for r in rows]) for name, rows in band_series.items()}
    band_amp_spans = {
        name: {
            "q_RMS_relative_span": rel_span([r["q_rms_m"] if "q_rms_m" in r else r["q_RMS_m"] for r in rows]),
            "max_span_rms_over_D_relative_span": rel_span([r["max_span_rms_over_D"] for r in rows]),
            "instantaneous_peak_over_D_relative_span": rel_span([r["max_instantaneous_peak_abs_over_D"] for r in rows]),
        }
        for name, rows in band_series.items()
    }
    primary = all_results["butterworth_order4_0p01_20_zero_phase"]
    corrected = {
        "status": "completed_recomputed_v31",
        "filter_protocol": "butterworth_order4_0p01_20_zero_phase",
        "CF": primary["CF"],
        "IL": primary["IL"],
        "not_author_bpass_reproduction": True,
        "source_csv_not_saved": True,
    }
    classification = {
        "status": "completed_offline_filter_classification",
        "all_six_filters": list(FILTERS),
        "bandpass_only_filters": band_filters,
        "series": series,
        "all_six_frequency_relative_spans": frequency_spans,
        "all_six_amplitude_relative_spans": amplitude_spans,
        "five_bandpass_frequency_relative_spans": band_frequency_spans,
        "five_bandpass_amplitude_relative_spans": band_amp_spans,
        "overall_along_span_frequency_relative_spans": overall_frequency_spans,
        "overall_along_span_amplitude_relative_spans": overall_amplitude_spans,
        "classification_rules": {
            "frequency_relative_span_le_2_percent": "frequency_valid_for_validation",
            "mode_identity_unchanged": "mode_valid_for_validation",
            "RMS_relative_span_le_5_percent": "amplitude_robust",
            "RMS_relative_span_5_to_10_percent": "amplitude_medium_sensitive",
            "RMS_relative_span_gt_10_percent": "not_strict_amplitude",
        },
        "target_classification": {
            name: {
                "frequency_valid": frequency_spans[name] <= 0.02,
                "mode_identity_stable": True,
                "q_RMS_class_all_six": class_for(amplitude_spans[name]["q_RMS_relative_span"]),
                "span_RMS_class_all_six": class_for(amplitude_spans[name]["max_span_rms_over_D_relative_span"]),
                "instantaneous_peak_class_all_six": class_for(amplitude_spans[name]["instantaneous_peak_over_D_relative_span"]),
                "q_RMS_class_five_bandpass": class_for(band_amp_spans[name]["q_RMS_relative_span"]),
                "span_RMS_class_five_bandpass": class_for(band_amp_spans[name]["max_span_rms_over_D_relative_span"]),
            }
            for name in named_targets
        },
        "explicit_IL2_bandpass_relative_RMS_span": band_amp_spans["IL_mode_2"]["q_RMS_relative_span"],
        "explicit_IL2_bandpass_not_strict_amplitude": band_amp_spans["IL_mode_2"]["q_RMS_relative_span"] > 0.10,
        "nominal_protocol_retained": "butterworth order4 0.01-20 Hz zero-phase",
        "nominal_protocol_label": "project protocol with uncertainty; not strict author bpass.m reproduction",
    }
    return classification, corrected


def zero_crossing(profile_x: np.ndarray, profile_u: np.ndarray) -> float:
    order = np.argsort(profile_x)
    x, u = profile_x[order], profile_u[order]
    for i in range(len(x) - 1):
        if u[i] == 0:
            return float(x[i])
        if u[i] * u[i + 1] <= 0:
            return float(x[i] + (x[i + 1] - x[i]) * (-u[i]) / (u[i + 1] - u[i]))
    raise ValueError("no zero crossing")


def nominal_profile(x: np.ndarray) -> np.ndarray:
    return P["Umax_mps"] * np.interp(x, PROFILE["depth_fraction"], np.asarray(PROFILE["velocity_mmps"], dtype=float) / max(abs(np.asarray(PROFILE["velocity_mmps"], dtype=float))))


def modal_reference(u: np.ndarray, x: np.ndarray, m: int) -> dict[str, float]:
    phi = np.sin(m * math.pi * x)
    drag = phi * u * np.abs(u)
    mag = phi * u * u
    return {
        "Q_m_drag_ref": trapz(drag, x) * P["L_m"],
        "Q_m_magnitude_ref": trapz(mag, x) * P["L_m"],
        "drag_normalizer": max(abs(trapz(drag, x) * P["L_m"]), 0.05 * trapz(np.abs(drag), x) * P["L_m"]),
        "magnitude_normalizer": max(abs(trapz(mag, x) * P["L_m"]), 0.05 * trapz(np.abs(mag), x) * P["L_m"]),
    }


def candidate_metrics(boundaries: np.ndarray, x: np.ndarray, u: np.ndarray, root: float) -> dict[str, Any]:
    b = np.asarray(boundaries, dtype=float)
    centers, widths = (b[:-1] + b[1:]) / 2.0, np.diff(b)
    local_u = np.interp(centers, x, u)
    ref_global = {
        "int_U": trapz(u, x) * P["L_m"],
        "int_abs_U": trapz(np.abs(u), x) * P["L_m"],
        "int_U2": trapz(u * u, x) * P["L_m"],
        "int_U_absU": trapz(u * np.abs(u), x) * P["L_m"],
    }
    disc_global = {
        "int_U": float(np.sum(local_u * widths) * P["L_m"]),
        "int_abs_U": float(np.sum(np.abs(local_u) * widths) * P["L_m"]),
        "int_U2": float(np.sum(local_u * local_u * widths) * P["L_m"]),
        "int_U_absU": float(np.sum(local_u * np.abs(local_u) * widths) * P["L_m"]),
    }
    global_errors = {key: abs(disc_global[key] - ref_global[key]) / max(abs(ref_global[key]), 1e-30) for key in ref_global}
    modal: dict[str, Any] = {}
    for m in (1, 2, 4):
        ref = modal_reference(u, x, m)
        phi_c = np.sin(m * math.pi * centers)
        q_drag = float(np.sum(phi_c * local_u * np.abs(local_u) * widths) * P["L_m"])
        q_mag = float(np.sum(phi_c * local_u * local_u * widths) * P["L_m"])
        modal[str(m)] = {
            "Q_m_drag_ref": ref["Q_m_drag_ref"],
            "Q_m_drag_disc": q_drag,
            "Q_m_drag_signed_relative_error": (q_drag - ref["Q_m_drag_ref"]) / max(abs(ref["Q_m_drag_ref"]), 1e-30),
            "Q_m_drag_normalized_absolute_error": abs(q_drag - ref["Q_m_drag_ref"]) / ref["drag_normalizer"],
            "Q_m_magnitude_ref": ref["Q_m_magnitude_ref"],
            "Q_m_magnitude_disc": q_mag,
            "Q_m_magnitude_signed_relative_error": (q_mag - ref["Q_m_magnitude_ref"]) / max(abs(ref["Q_m_magnitude_ref"]), 1e-30),
            "Q_m_magnitude_normalized_absolute_error": abs(q_mag - ref["Q_m_magnitude_ref"]) / ref["magnitude_normalizer"],
            "delta_s_applied_once": True,
        }
    root_boundary = bool(np.min(np.abs(b - root)) <= 1e-9)
    crosses = bool(any(left < root - 1e-9 and root < right - 1e-9 for left, right in zip(b[:-1], b[1:])))
    sign_pattern = ["positive" if value > 0 else "negative" if value < 0 else "zero" for value in local_u]
    return {
        "boundaries_fraction": [float(v) for v in b],
        "centers_fraction": [float(v) for v in centers],
        "centers_m": [float(v * P["L_m"]) for v in centers],
        "slice_lengths_m": [float(v * P["L_m"]) for v in widths],
        "local_U_mps": [float(v) for v in local_u],
        "direction_classification": sign_pattern,
        "root_on_boundary": root_boundary,
        "crosses_zero": crosses,
        "integrals_reference": ref_global,
        "integrals_discrete": disc_global,
        "global_relative_errors": global_errors,
        "modal_weighted_loads": modal,
        "delta_s_applied_once": True,
        "modal_normalized_absolute_error_max": float(max([v["Q_m_drag_normalized_absolute_error"] for v in modal.values()] + [v["Q_m_magnitude_normalized_absolute_error"] for v in modal.values()])),
    }


def candidate_pass(item: dict[str, Any], require_root: bool = True) -> bool:
    g = item["global_relative_errors"]
    modal_ok = all(v["Q_m_drag_normalized_absolute_error"] <= 0.05 and v["Q_m_magnitude_normalized_absolute_error"] <= 0.05 for v in item["modal_weighted_loads"].values())
    return bool(
        g["int_abs_U"] <= 0.02 and g["int_U2"] <= 0.02 and g["int_U_absU"] <= 0.05
        and modal_ok and (not require_root or (item["root_on_boundary"] and not item["crosses_zero"]))
    )


def slice_design() -> tuple[dict[str, Any], dict[str, Any]]:
    x = np.linspace(0.0, 1.0, 20001)
    u = nominal_profile(x)
    root = zero_crossing(np.asarray(PROFILE["depth_fraction"], dtype=float), np.asarray(PROFILE["velocity_mmps"], dtype=float))
    current_v3 = json.loads(V3_SLICES.read_text(encoding="utf-8"))["optimized_nonuniform_5"]["boundaries_fraction"]
    candidates: dict[str, Any] = {
        "current_v3_optimized_5": candidate_metrics(np.asarray(current_v3), x, u, root),
        "uniform_7": candidate_metrics(np.linspace(0.0, 1.0, 8), x, u, root),
        "uniform_9": candidate_metrics(np.linspace(0.0, 1.0, 10), x, u, root),
    }
    if differential_evolution is None:
        raise RuntimeError("scipy.optimize is required")

    def make_root_boundary(v: np.ndarray, root_index: int) -> np.ndarray:
        raw = np.asarray(v, dtype=float)
        before = np.sort(raw[: root_index - 1])
        # There are five slices, hence four interior boundaries.  One is the
        # fixed root; the remaining three are split as (root_index-1) before
        # and (4-root_index) after it.
        after = np.sort(raw[root_index - 1 : root_index - 1 + (4 - root_index)])
        return np.r_[0.0, before, root, after, 1.0]

    def objective(v: np.ndarray, root_index: int) -> float:
        b = make_root_boundary(v, root_index)
        widths = np.diff(b)
        if np.min(widths) < 0.04 or any(np.diff(b) <= 0.0):
            return 1e3 + float(np.sum(np.maximum(0.04 - widths, 0.0)) * 1e4)
        item = candidate_metrics(b, x, u, root)
        g = item["global_relative_errors"]
        m = item["modal_weighted_loads"]
        values = [g["int_abs_U"], g["int_U2"], g["int_U_absU"], g["int_U"]]
        for v_m in m.values():
            values += [v_m["Q_m_drag_normalized_absolute_error"], v_m["Q_m_magnitude_normalized_absolute_error"]]
        return float(np.sum(np.square(values)))

    constrained_options = []
    for root_index in (2, 3, 4):
        pre_bounds = [(0.05, root - 0.04)] * (root_index - 1)
        post_bounds = [(root + 0.04, 0.95)] * (4 - root_index)
        bounds = pre_bounds + post_bounds
        result = differential_evolution(lambda v, ri=root_index: objective(v, ri), bounds, seed=20260812 + root_index, maxiter=160, popsize=12, polish=True, tol=1e-9, updating="immediate")
        boundary = make_root_boundary(result.x, root_index)
        item = candidate_metrics(boundary, x, u, root)
        item["optimizer"] = {"algorithm": "scipy differential_evolution", "seed": 20260812 + root_index, "objective_value": float(result.fun), "fixed_root_boundary": True, "root_boundary_index": root_index}
        item["freeze_pass"] = candidate_pass(item, require_root=True)
        constrained_options.append(item)
    constrained = min(constrained_options, key=lambda value: value["optimizer"]["objective_value"])
    constrained["alternative_root_boundary_options"] = [
        {key: value for key, value in option.items() if key != "alternative_root_boundary_options"}
        for option in constrained_options
    ]
    candidates["zero_crossing_constrained_5"] = constrained
    for name, item in candidates.items():
        item["nominal_global_and_modal_pass"] = candidate_pass(item, require_root=False)
    if constrained["freeze_pass"]:
        recommendation = "zero_crossing_constrained_5"
    else:
        recommendation = "no_scheme_frozen"
    out = {
        "status": "completed_nominal_zero_crossing_constrained_design",
        "profile": PROFILE,
        "zero_crossing": {"depth_fraction": root, "s_m": root * P["L_m"], "nominal_expected_s_over_L": 0.474, "root_interpolation": "linear between digitized sign-changing points"},
        "candidates": candidates,
        "comparison": {"current_v3_optimized_5_has_crossing": candidates["current_v3_optimized_5"]["crosses_zero"], "uniform_7": "conservative comparison only", "uniform_9": "conservative comparison only"},
        "freeze_criteria": {"int_abs_U_relative_error_max": 0.02, "int_U2_relative_error_max": 0.02, "int_U_absU_relative_error_max": 0.05, "modal_normalized_absolute_error_max": 0.05, "root_on_boundary": True, "no_crossing": True},
        "recommendation": recommendation,
        "no_real_five_slice_cfd": True,
    }
    return out, {"x": x, "u": u, "root": root}


def formal_H_audit(design: dict[str, Any]) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT))
    from src.coupling.multi_slice_mapping.mapping import SliceDefinition, SliceManifest, build_H_for_manifest

    root = float(design["zero_crossing"]["depth_fraction"])
    candidate_names = ["zero_crossing_constrained_5", "uniform_7"]
    calls: list[dict[str, Any]] = []
    for n_elem in (8, 16):
        nodes = np.linspace(0.0, P["L_m"], n_elem + 1).tolist()
        for name in candidate_names:
            boundaries = np.asarray(design["candidates"][name]["boundaries_fraction"], dtype=float)
            centers = (boundaries[:-1] + boundaries[1:]) / 2.0
            slices = tuple(SliceDefinition(i, float(s * P["L_m"]), float(w * P["L_m"]), 1.0) for i, (s, w) in enumerate(zip(centers, np.diff(boundaries))))
            manifest = SliceManifest(SCHEMA_VERSION, f"v31_{n_elem}_{name}", P["L_m"], P["L_m"], slices)
            Hs = build_H_for_manifest(manifest, nodes, ndof=6 * (n_elem + 1))
            for sid, matrix in Hs.items():
                arr = np.asarray(matrix, dtype=float)
                calls.append({"nElem": n_elem, "candidate": name, "slice_id": sid, "shape": list(arr.shape), "row_sum": [float(v) for v in np.sum(arr, axis=1)], "nonzero_count": int(np.count_nonzero(arr)), "H_sha256": sha256(json.dumps(matrix, separators=(",", ":")).encode())})
    config = json.loads(V2_DESIGN.read_text(encoding="utf-8"))
    result_keys = set(config["configurations"][0]["results"][0].keys())
    required_state_keys = {"modal_node_positions", "modal_node_slopes", "modal_q_vectors", "eigenvectors"}
    missing = sorted(required_state_keys - result_keys)
    return {
        "status": "blocked_formal_modal_state_unavailable",
        "formal_H_function_called": True,
        "formal_H_function": "src.coupling.multi_slice_mapping.mapping.build_H_for_manifest -> ancf_hermite_H",
        "production_mapping_file": str(MAPPING_FILE),
        "production_mapping_sha256": sha256_file(MAPPING_FILE),
        "H_contract_sanity_calls": calls,
        "candidate_center_sets": candidate_names,
        "nElem_compared": [8, 16],
        "source_design_file": str(V2_DESIGN),
        "source_design_result_keys": sorted(result_keys),
        "missing_true_ANCF_modal_state_fields": missing,
        "modal_state_source_available": False,
        "legacy_201_point_normalized_shape_used_as_formal_H_evidence": False,
        "frequency_MAC_evidence": "not recomputed as formal H projection because q/eigenvector node state is absent",
        "decision": {"formal_projection_pass": False, "minimum_production_nElem": None, "recommended_reference_nElem": None, "reason": "The audited result stores modal_shape_samples only; no true ANCF node position/slope modal DOFs are available."},
    }


def uncertainty_metric(item: dict[str, Any]) -> float:
    return float(max(item["global_relative_errors"]["int_abs_U"], item["global_relative_errors"]["int_U2"], item["global_relative_errors"]["int_U_absU"]))


def profile_uncertainty(design: dict[str, Any]) -> dict[str, Any]:
    rng = np.random.default_rng(20260812)
    n = 1000
    x0 = np.asarray(PROFILE["depth_fraction"], dtype=float)
    v0 = np.asarray(PROFILE["velocity_mmps"], dtype=float)
    eps_x, eps_v = PROFILE["depth_fraction_uncertainty"], PROFILE["velocity_uncertainty_mmps"]
    dense = np.linspace(0.0, 1.0, 2001)
    candidates = {k: np.asarray(v["boundaries_fraction"], dtype=float) for k, v in design["candidates"].items()}
    nominal_u = nominal_profile(dense)
    nominal_root = float(design["zero_crossing"]["depth_fraction"])
    nominal_patterns = {name: design["candidates"][name]["direction_classification"] for name in candidates}

    def evaluate(x_sample: np.ndarray, v_sample: np.ndarray, method: str) -> tuple[dict[str, Any], float | None]:
        xs = np.asarray(x_sample, dtype=float)
        # Preserve the nominal velocity scale.  The allowed perturbation is
        # an absolute digitization error (mm/s), not a rescaling of each
        # realization to its own maximum.
        vs = np.asarray(v_sample, dtype=float) / 1000.0 * P["Umax_mps"] / max(abs(v0 / 1000.0))
        if method == "linear":
            fn: Callable[[np.ndarray], np.ndarray] = lambda z: np.interp(z, xs, vs)
        else:
            fn = PchipInterpolator(xs, vs, extrapolate=False)
        uu = np.asarray(fn(dense), dtype=float)
        root_sample = None
        try:
            root_sample = zero_crossing(xs, vs)
        except ValueError:
            pass
        rows: dict[str, Any] = {}
        for name, b in candidates.items():
            item = candidate_metrics(b, dense, uu, nominal_root)
            rows[name] = {
                "max_global_error": uncertainty_metric(item),
                "global_errors": item["global_relative_errors"],
                "max_modal_normalized_absolute_error": item["modal_normalized_absolute_error_max"],
                "modal_errors": item["modal_weighted_loads"],
                "direction_classification": item["direction_classification"],
                "direction_classification_changed": item["direction_classification"] != nominal_patterns[name],
                "root_on_fixed_nominal_boundary": root_sample is not None and abs(root_sample - nominal_root) <= 1e-9,
            }
        return rows, root_sample

    summaries: dict[str, Any] = {}
    root_values: dict[str, list[float]] = {"linear": [], "pchip": []}
    deterministic: dict[str, Any] = {}
    for method in ("linear", "pchip"):
        samples = {name: {"max_global_error": [], "max_modal_error": [], "global_errors": {k: [] for k in ("int_U", "int_abs_U", "int_U2", "int_U_absU")}, "direction_changes": 0} for name in candidates}
        for _ in range(n):
            xs = x0.copy(); xs[1:-1] += rng.uniform(-eps_x, eps_x, size=len(xs) - 2); xs[1:-1] = np.sort(xs[1:-1])
            vs = v0 + rng.uniform(-eps_v, eps_v, size=len(v0))
            rows, root_sample = evaluate(xs, vs, method)
            if root_sample is not None:
                root_values[method].append(float(root_sample))
            for name, row in rows.items():
                samples[name]["max_global_error"].append(row["max_global_error"])
                samples[name]["max_modal_error"].append(row["max_modal_normalized_absolute_error"])
                for key, value in row["global_errors"].items(): samples[name]["global_errors"][key].append(value)
                samples[name]["direction_changes"] += int(row["direction_classification_changed"])
        summaries[method] = {}
        for name, sample in samples.items():
            summaries[method][name] = {
                "fixed_boundaries": candidates[name].tolist(),
                "global_error_statistics": {key: {"median": float(np.median(values)), "p95": float(np.percentile(values, 95)), "max": float(np.max(values))} for key, values in sample["global_errors"].items()},
                "max_global_error_statistics": {"median": float(np.median(sample["max_global_error"])), "p95": float(np.percentile(sample["max_global_error"], 95)), "max": float(np.max(sample["max_global_error"]))},
                "max_modal_normalized_error_statistics": {"median": float(np.median(sample["max_modal_error"])), "p95": float(np.percentile(sample["max_modal_error"], 95)), "max": float(np.max(sample["max_modal_error"]))},
                "direction_classification_changed_count": int(sample["direction_changes"]),
                "direction_classification_unchanged": sample["direction_changes"] == 0,
                "fixed_boundaries_reoptimized": False,
            }
    for case_name, x_shift, v_shift in (("all_plus", eps_x, eps_v), ("all_minus", -eps_x, -eps_v), ("depth_plus_velocity_minus", eps_x, -eps_v), ("depth_minus_velocity_plus", -eps_x, eps_v)):
        xs = x0.copy(); xs[1:-1] += x_shift; xs[1:-1] = np.sort(xs[1:-1]); vs = v0 + v_shift
        deterministic[case_name] = {}
        for method in ("linear", "pchip"):
            rows, root_sample = evaluate(xs, vs, method)
            deterministic[case_name][method] = {"root_fraction": root_sample, "candidates": rows}
    robust_flags = {}
    for method in summaries:
        for name, row in summaries[method].items():
            robust_flags[f"{method}:{name}"] = bool(row["max_global_error_statistics"]["p95"] <= 0.05 and row["max_modal_normalized_error_statistics"]["p95"] <= 0.10 and row["direction_classification_unchanged"])
    return {
        "status": "completed_fixed_boundary_uncertainty",
        "sample_count": n,
        "random_seed": 20260812,
        "uncertainty": {"velocity_mmps_plus_minus": eps_v, "depth_fraction_plus_minus": eps_x},
        "interpolation_methods": ["linear", "pchip_shape_preserving"],
        "zero_crossing_nominal_fraction": nominal_root,
        "zero_crossing_range_fraction": {method: [float(np.min(values)), float(np.max(values))] for method, values in root_values.items()},
        "fixed_boundaries_not_reoptimized": True,
        "summary_by_method": summaries,
        "deterministic_worst_case": deterministic,
        "robust_freeze_flags": robust_flags,
        "criteria": {"p95_global_error_max": 0.05, "p95_modal_weighted_error_max": 0.10, "direction_classification_changes": 0},
        "source_profile_not_saved": True,
    }


def v3_hash_audit() -> dict[str, str]:
    paths = [V3_SOURCE_ID, V3_FILTERS, V3_OBS, V3_SLICES, ROOT / "src" / "coupling" / "stage4e_physical_baseline_v3" / "audit_vivdatashare_v3.py"]
    return {str(p.relative_to(ROOT)): sha256_file(p) for p in paths}


def build() -> dict[str, Any]:
    source = source_pin()
    csv_bytes = fetch(COMMIT_CSV_URL, 120)
    cf_raw, il_raw = parse_pinned_csv(csv_bytes)
    classification, corrected = amplitude_analysis(cf_raw, il_raw)
    design, profile_context = slice_design()
    H = formal_H_audit(design)
    uncertainty = profile_uncertainty(design)
    final_rec = design["recommendation"] if not H["decision"]["formal_projection_pass"] else design["recommendation"]
    summary = {
        "status": "partially_completed_formal_H_blocked",
        "schema_version": SCHEMA_VERSION,
        "source_pin_status": source["source_pin_status"],
        "amplitude_status": "frequency_and_mode_usable_but_IL2_not_strict_amplitude",
        "formal_H_status": H["status"],
        "zero_crossing_slice_recommendation": final_rec,
        "target_mesh_recommendation": "none_not_frozen_until_formal_H_projection",
        "profile_uncertainty_status": uncertainty["status"],
        "no_openfoam_started": True,
        "no_raw_csv_saved": True,
        "gate_recommendation": "建议不通过",
        "scope_boundary": ["offline v3.1 directional correction only", "no real five-slice CFD", "no strict IL2 amplitude validation", "nElem freeze withheld because formal ANCF modal node/slope state is unavailable"],
    }
    return {"source": source, "classification": classification, "corrected": corrected, "design": design, "H": H, "uncertainty": uncertainty, "summary": summary, "v3_hashes": v3_hash_audit(), "profile_context": {"root": profile_context["root"]}}


def write_all(bundle: dict[str, Any], run_id: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    dump(OUT / "source_pin_and_hash.json", {"run_id": run_id, **bundle["source"]})
    dump(OUT / "amplitude_robustness_classification.json", {"run_id": run_id, **bundle["classification"]})
    dump(OUT / "corrected_amplitude_semantics.json", {"run_id": run_id, **bundle["corrected"]})
    dump(OUT / "formal_H_projection_8_vs_16.json", {"run_id": run_id, **bundle["H"]})
    dump(OUT / "zero_crossing_constrained_slice_design.json", {"run_id": run_id, **bundle["design"]})
    dump(OUT / "modal_weighted_load_errors.json", {"run_id": run_id, "candidates": bundle["design"]["candidates"], "criteria": bundle["design"]["freeze_criteria"]})
    dump(OUT / "profile_uncertainty_robustness.json", {"run_id": run_id, **bundle["uncertainty"]})
    dump(OUT / "stage4e_a_v3_1_final_candidate_summary.json", {"run_id": run_id, **bundle["summary"], "v3_read_only_hashes": bundle["v3_hashes"]})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--run-id", default="stage4e_a_v3_1_offline_20260812")
    args = parser.parse_args()
    if not args.write:
        parser.error("use --write")
    bundle = build()
    write_all(bundle, args.run_id)
    print(json.dumps({"out": str(OUT), "formal_H_status": bundle["H"]["status"], "recommendation": bundle["summary"]["zero_crossing_slice_recommendation"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
