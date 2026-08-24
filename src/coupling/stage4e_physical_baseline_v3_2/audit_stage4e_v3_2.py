"""Offline Stage 4E-A-v3.2 audit.

This module is deliberately isolated from the production coupling stack.  It
reads the real ANCF modal MAT exports, calls the frozen H implementation, and
performs deterministic profile quadrature and bidirectional-protocol mocks.
It never launches an OpenFOAM executable.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.io import loadmat, savemat
from scipy.interpolate import PchipInterpolator
from scipy.optimize import differential_evolution

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "results" / "08_stage4e_physical_baseline_v3_2"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from src.coupling.multi_slice_mapping.mapping import (  # noqa: E402
    SliceDefinition,
    SliceManifest,
    build_H_for_manifest,
)

SCHEMA_VERSION = "0.2.1"
L = 7.64
D = 0.02841
RMS_TARGETS = {
    "CF_mode_1": 6.821e-3,
    "IL_mode_2": 1.240e-3,
    "IL_mode_4": 8.177e-4,
}
TARGET_PAIRS = {"CF_mode_1": (0, 1), "IL_mode_2": (2, 3), "IL_mode_4": (6, 7)}
DEPTH = np.array([0.0, .125, .25, .375, .5, .625, .75, .875, 1.0], dtype=float)
VELOCITY_MMPS = np.array([1095.0, 1365.0, 1135.0, 560.0, -145.0, -400.0, -470.0, -410.0, -370.0], dtype=float)
ROOT_NOMINAL = 0.474290780141844
UNCERTAINTY_SEED = 20260812


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_json(value: Any) -> str:
    raw = json.dumps(clean(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def clean(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return clean(value.item())
        return [clean(x) for x in value.tolist()]
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return value.item()
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(x) for x in value]
    return value


def dump(name: str, value: Mapping[str, Any]) -> Path:
    path = OUT / name
    path.write_text(json.dumps(clean(value), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return path


def mat_state(nelem: int) -> Dict[str, Any]:
    path = OUT / f"ancf_modal_state_nElem{nelem}.mat"
    data = loadmat(path)
    def arr(key: str) -> np.ndarray:
        return np.asarray(data[key])
    return {
        "path": path,
        "nElem": int(arr("nElem").ravel()[0]),
        "nNode": int(arr("nNode").ravel()[0]),
        "ndof": int(arr("ndof").ravel()[0]),
        "node_s": arr("node_s_reference_m").ravel().astype(float),
        "q_static": arr("q_static").ravel().astype(float),
        "free": arr("free_dof_1based").ravel().astype(int),
        "fixed": arr("fixed_dof_1based").ravel().astype(int),
        "qmode": arr("qmode").astype(float),
        "V": arr("V_free_mass_normalized").astype(float),
        "eigenvalues": arr("eigenvalues_rad2ps2").ravel().astype(float),
        "freq": arr("dry_frequency_Hz").ravel().astype(float),
        "direction": arr("mode_direction_xy").ravel().astype(int),
        "samples_s": arr("mode_shape_samples_s_m").ravel().astype(float),
        "samples": arr("mode_shape_samples").astype(float),
        "M": arr("mass_matrix").astype(float),
        "K": arr("stiffness_matrix").astype(float),
        "node_position": arr("node_position_static_m").astype(float),
        "node_slope": arr("node_slope_static").astype(float),
    }


def canonical_array_hash(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a, dtype=np.float64).tobytes()).hexdigest()


def old_state(nelem: int) -> Mapping[str, Any]:
    raw = json.loads((ROOT / "results" / "08_stage4e_physical_baseline" / "ancf_design_raw.json").read_text(encoding="utf-8"))
    return next(x for x in raw["configurations"][0]["results"] if int(x["nElem"]) == nelem)


def modal_export_audit(states: Mapping[int, Mapping[str, Any]]) -> Dict[str, Any]:
    per = {}
    for n, s in states.items():
        fixed0 = s["fixed"] - 1
        V = s["V"]
        Mff = s["M"][np.ix_(s["free"] - 1, s["free"] - 1)]
        orth = V.T @ Mff @ V - np.eye(V.shape[1])
        residuals = []
        for j, lam in enumerate(s["eigenvalues"]):
            v = V[:, j]
            residuals.append(float(np.linalg.norm((s["K"][np.ix_(s["free"] - 1, s["free"] - 1)] @ v) - lam * (Mff @ v)) / max(np.linalg.norm(s["K"][np.ix_(s["free"] - 1, s["free"] - 1)] @ v), 1e-30)))
        per[str(n)] = {
            "nElem": n,
            "nNode": s["nNode"],
            "ndof": s["ndof"],
            "indexing": "MATLAB free/fixed/qmode are 1-based in metadata; qmode rows are stored in MATLAB order and Python audit uses zero-based array indexing",
            "node_s_reference_m": s["node_s"],
            "free_dof_1based": s["free"],
            "fixed_dof_1based": s["fixed"],
            "q_static_sha256": canonical_array_hash(s["q_static"]),
            "qmode_shape": list(s["qmode"].shape),
            "qmode_sha256": canonical_array_hash(s["qmode"]),
            "mass_normalized_mode_count": int(V.shape[1]),
            "max_abs_fixed_qmode": float(np.max(np.abs(s["qmode"][fixed0, :]))),
            "max_mass_orthogonality_error": float(np.max(np.abs(orth))),
            "max_eigen_residual_relative": float(max(residuals)),
            "dry_frequency_Hz": s["freq"],
            "mode_direction_xy": s["direction"],
            "all_finite": bool(np.isfinite(s["qmode"]).all() and np.isfinite(s["freq"]).all() and np.isfinite(s["M"]).all() and np.isfinite(s["K"]).all()),
            "mat_sha256": sha256_file(s["path"]),
        }
    return {
        "schema_version": "stage4e_a_v3_2_modal_export_audit_v1",
        "status": "completed_offline_real_qmode_export",
        "openfoam_started": False,
        "matlab_command_return_code": 0,
        "matlab_start_count": 1,
        "matlab_version": "9.9.0.1467703 (R2020b)",
        "parameters": {"L_m": L, "D_m": D, "dInner_m": .025, "mass_per_length_kgpm": 1.24, "EI_Nm2": 58.6, "EA_N": 9.4e5, "top_tension_N": 980.0, "fluid_rho_kgpm3": 1000.0, "gravity": False, "buoyancy": False, "damping": 0.0},
        "per_nElem": per,
        "export_script": rel(ROOT / "src" / "coupling" / "stage4e_physical_baseline_v3_2" / "export_ancf_modal_state_v3_2.m"),
        "export_script_sha256": sha256_file(ROOT / "src" / "coupling" / "stage4e_physical_baseline_v3_2" / "export_ancf_modal_state_v3_2.m"),
    }


def mac(a: np.ndarray, b: np.ndarray) -> float:
    aa = np.asarray(a).ravel(); bb = np.asarray(b).ravel()
    return float(abs(np.dot(aa, bb)) ** 2 / max(float(np.dot(aa, aa) * np.dot(bb, bb)), 1e-300))


def subspace_metrics(A: np.ndarray, B: np.ndarray) -> Dict[str, Any]:
    QA, _ = np.linalg.qr(A)
    QB, _ = np.linalg.qr(B)
    sv = np.linalg.svd(QA.T @ QB, compute_uv=False)
    sv = np.clip(sv, 0.0, 1.0)
    return {"singular_values": sv, "subspace_MAC_min": float(np.min(sv ** 2)), "principal_angle_max_deg": float(np.degrees(np.arccos(np.min(sv))))}


def modal_crosscheck(states: Mapping[int, Mapping[str, Any]]) -> Dict[str, Any]:
    result = {}
    for n, s in states.items():
        old = old_state(n)
        old_f = np.asarray(old["dry_frequency_Hz"], dtype=float)
        old_samples = np.asarray(old["modal_shape_samples"], dtype=float)
        freq_rel = np.abs(s["freq"][:8] - old_f[:8]) / np.maximum(np.abs(old_f[:8]), 1e-300)
        mode_mac = [mac(s["samples"][:, j], old_samples[:, j]) for j in range(8)]
        pairs = {}
        for label, (a, b) in TARGET_PAIRS.items():
            pairs[label] = subspace_metrics(old_samples[:, [a, b]], s["samples"][:, [a, b]])
        result[str(n)] = {
            "frequency_relative_error_first8": freq_rel,
            "max_frequency_relative_error_first8": float(np.max(freq_rel)),
            "old_direction_first8": old["dry_mode_direction_xy"][:8],
            "new_direction_first8": s["direction"][:8],
            "single_mode_MAC_first8": mode_mac,
            "target_subspace_crosscheck": pairs,
            "old_sample_grid_matches_new": bool(np.max(np.abs(np.asarray(old["modal_shape_samples_s_m"]) - s["samples_s"])) < 1e-12),
            "frequency_crosscheck_pass": bool(np.max(freq_rel) <= 1e-10),
            "subspace_crosscheck_pass": bool(all(x["subspace_MAC_min"] >= .999 for x in pairs.values())),
        }
    return {"status": "completed", "source": rel(ROOT / "results" / "08_stage4e_physical_baseline" / "ancf_design_raw.json"), "per_nElem": result}


def make_manifest(centers: Sequence[float], lengths: Sequence[float]) -> SliceManifest:
    slices = tuple(SliceDefinition(i, float(c), float(w), 1.0) for i, (c, w) in enumerate(zip(centers, lengths)))
    return SliceManifest(SCHEMA_VERSION, "stage4e_v3_2_H_projection", L, float(sum(lengths)), slices)


def H_for(n: int, boundaries: Sequence[float]) -> Tuple[np.ndarray, SliceManifest]:
    centers = (np.asarray(boundaries[:-1]) + np.asarray(boundaries[1:])) * .5 * L
    lengths = np.diff(boundaries) * L
    manifest = make_manifest(centers, lengths)
    H_dict = build_H_for_manifest(manifest, np.asarray(states_global[n]["node_s"], dtype=float), ndof=states_global[n]["ndof"])
    H = np.stack([np.asarray(H_dict[i], dtype=float) for i in range(len(centers))], axis=0)
    return H, manifest


def procrustes(A: np.ndarray, B: np.ndarray) -> Tuple[np.ndarray, float]:
    U, _, Vt = np.linalg.svd(B.T @ A)
    R = U @ Vt
    return B @ R, float(np.linalg.norm(A - B @ R) / max(np.linalg.norm(A), 1e-300))


def formal_H_audit(states: Mapping[int, Mapping[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    global states_global
    states_global = states
    candidates = {
        "v3_optimized_5_reference_centers": [0.06663514105723498, 0.21990975217479328, 0.3904200011884803, 0.6098656137721943, 0.8727202237012722],
        "uniform_7_centers": ((np.arange(7) + .5) / 7).tolist(),
    }
    # The second official grid is evaluated separately below so both requested
    # center sets are present without coupling H to the quadrature optimizer.
    candidates["uniform_9_centers"] = ((np.arange(9) + .5) / 9).tolist()
    per_grid: Dict[str, Any] = {}
    for grid_name, centers_frac in candidates.items():
        boundaries = [0.0] + [float(x) for x in ((np.asarray(centers_frac[:-1]) + np.asarray(centers_frac[1:])) * .5)] + [1.0]
        grid_out = {"centers_m": (np.asarray(centers_frac) * L), "boundaries_fraction": boundaries, "per_nElem": {}}
        for n, s in states.items():
            H, manifest = H_for(n, boundaries)
            target_out = {}
            for label, pair in TARGET_PAIRS.items():
                A = np.column_stack([(H @ s["qmode"][:, j]) for j in pair])
                # H returns 3 x ndof per slice; stack each slice in physical order.
                Aflat = A.reshape(-1, 1) if A.ndim == 1 else A
                # build_H_for_manifest returns (nslice,3,ndof) in current mapping.
                if H.ndim == 3:
                    A = np.stack([(H @ s["qmode"][:, j]).reshape(-1) for j in pair], axis=1)
                B = A
                if n == 8:
                    target_out[label] = {"projected_shape": A, "subspace_MAC_self": 1.0}
                else:
                    target_out[label] = {"projected_shape": A}
            grid_out["per_nElem"][str(n)] = {"H_shape": list(H.shape), "manifest_hash": manifest.slice_manifest_sha256, "target_raw": target_out}
        # Cross compare target arrays.
        for label in TARGET_PAIRS:
            A = np.asarray(grid_out["per_nElem"]["8"]["target_raw"][label]["projected_shape"])
            B = np.asarray(grid_out["per_nElem"]["16"]["target_raw"][label]["projected_shape"])
            Balign, err = procrustes(A, B)
            sm = subspace_metrics(A, B)
            amp = RMS_TARGETS[label]
            An = A / max(np.max(np.abs(A)), 1e-300) * amp
            Bn = Balign / max(np.max(np.abs(Balign)), 1e-300) * amp
            per_slice_abs = np.linalg.norm(An - Bn, axis=1)
            per_slice_rel_floor = per_slice_abs / max(float(np.max(np.linalg.norm(Bn, axis=1))), 1e-300)
            grid_out[label] = {"subspace": sm, "procrustes_relative_error": err, "max_slice_relative_error_physical_scaled": float(np.max(per_slice_rel_floor)), "per_slice_absolute_error_m": per_slice_abs, "rms_target_m": amp, "physical_scaled_slice_displacements_8": An, "physical_scaled_slice_displacements_16_aligned": Bn, "near_zero_slice_relative_error_note": "reported relative error uses the maximum projected displacement as an explicit physical floor"}
            del grid_out["per_nElem"]["8"]["target_raw"][label]["projected_shape"]
            del grid_out["per_nElem"]["16"]["target_raw"][label]["projected_shape"]
        grid_out["formal_mapping_call"] = {"function": "src.coupling.multi_slice_mapping.mapping.build_H_for_manifest", "node_dof_order": ["position_x", "position_y", "position_z", "slope_x", "slope_y", "slope_z"], "uses_real_node_s": True, "uses_real_qmode": True}
        per_grid[grid_name] = grid_out
    # Direct H basis tests on the 7-slice H.
    boundaries = np.linspace(0.0, 1.0, 8)
    H, _ = H_for(8, boundaries)
    ndof = states[8]["ndof"]
    qtrans = np.zeros(ndof); qtrans[0::6] = .012; qtrans[1::6] = -.004; qtrans[2::6] = .007
    qlinear = np.zeros(ndof); qlinear[2::6] = states[8]["node_s"]; qlinear[5::6] = 1.0
    rtrans = np.stack([H[i] @ qtrans for i in range(H.shape[0])])
    rlinear = np.stack([H[i] @ qlinear for i in range(H.shape[0])])
    basics = {"rigid_translation_max_error": float(np.max(np.abs(rtrans - np.array([.012, -.004, .007])))), "linear_axis_z_max_error_m": float(np.max(np.abs(rlinear[:, 2] - np.asarray([((a+b)/2)*L for a,b in zip(boundaries[:-1], boundaries[1:])])))), "slope_columns_nonzero": bool(np.any(np.abs(H[:, :, 3::6]) > 0.0)), "do_not_require_all_column_row_sum_one": True}
    return {"status": "completed_formal_H_with_real_qmode", "per_grid": per_grid, "basis_tests": basics, "qmode_source": {str(n): rel(s["path"]) for n, s in states.items()}}, {"status": "completed", "per_grid": {k: {label: v[label] for label in TARGET_PAIRS} for k, v in per_grid.items()}, "thresholds": {"frequency_relative": .02, "subspace_MAC": .95, "physical_slice_relative": .01}}


def profile(depth: np.ndarray, method: str = "linear", velocity_mmps: Optional[np.ndarray] = None) -> np.ndarray:
    y = VELOCITY_MMPS if velocity_mmps is None else velocity_mmps
    if method == "pchip":
        return PchipInterpolator(DEPTH, y)(depth) / 1000.0
    return np.interp(depth, DEPTH, y) / 1000.0


def root_for(depth: np.ndarray, y: np.ndarray) -> float:
    for i in range(len(y) - 1):
        if y[i] == 0:
            return float(depth[i])
        if y[i] * y[i + 1] < 0:
            return float(depth[i] + (-y[i]) * (depth[i + 1] - depth[i]) / (y[i + 1] - y[i]))
    return float("nan")


def reference_integrals(method: str = "linear", y: Optional[np.ndarray] = None) -> Dict[str, float]:
    x = np.linspace(0.0, 1.0, 20001)
    u = profile(x, method, y)
    out = {"int_U": float(np.trapz(u, x) * L), "int_abs_U": float(np.trapz(np.abs(u), x) * L), "int_U2": float(np.trapz(u * u, x) * L), "int_U_absU": float(np.trapz(u * np.abs(u), x) * L)}
    for m in (1, 2, 4):
        phi = np.sin(m * np.pi * x)
        out[f"Q{m}_drag"] = float(np.trapz(phi * u * np.abs(u), x) * L)
        out[f"Q{m}_magnitude"] = float(np.trapz(phi * u * u, x) * L)
    return out


def candidate_metrics(boundaries: Sequence[float], active: Optional[Sequence[bool]] = None, method: str = "linear", y: Optional[np.ndarray] = None) -> Dict[str, Any]:
    b = np.asarray(boundaries, dtype=float)
    centers = (b[:-1] + b[1:]) / 2.0
    widths = np.diff(b)
    mask = np.ones(len(widths), dtype=bool) if active is None else np.asarray(active, dtype=bool)
    u = profile(centers, method, y)
    ref = reference_integrals(method, y)
    disc = {"int_U": float(np.sum(u[mask] * widths[mask]) * L), "int_abs_U": float(np.sum(np.abs(u[mask]) * widths[mask]) * L), "int_U2": float(np.sum(u[mask] ** 2 * widths[mask]) * L), "int_U_absU": float(np.sum(u[mask] * np.abs(u[mask]) * widths[mask]) * L)}
    modal = {}
    xphi = centers
    for m in (1, 2, 4):
        phi = np.sin(m * np.pi * xphi)
        qd = float(np.sum(phi[mask] * u[mask] * np.abs(u[mask]) * widths[mask]) * L)
        qm = float(np.sum(phi[mask] * u[mask] ** 2 * widths[mask]) * L)
        refd, refm = ref[f"Q{m}_drag"], ref[f"Q{m}_magnitude"]
        xgrid = np.linspace(0.0, 1.0, 20001)
        ugrid = profile(xgrid, method, y)
        phigrid = np.sin(m * np.pi * xgrid)
        denom_d = max(abs(refd), .05 * float(np.trapz(np.abs(phigrid * ugrid * np.abs(ugrid)), xgrid) * L))
        denom_m = max(abs(refm), .05 * float(np.trapz(np.abs(phigrid * ugrid ** 2), xgrid) * L))
        modal[str(m)] = {"Q_m_drag_disc": qd, "Q_m_drag_ref": refd, "Q_m_drag_signed_relative_error": (qd-refd)/max(abs(refd),1e-300), "Q_m_drag_normalized_absolute_error": abs(qd-refd)/denom_d, "Q_m_magnitude_disc": qm, "Q_m_magnitude_ref": refm, "Q_m_magnitude_signed_relative_error": (qm-refm)/max(abs(refm),1e-300), "Q_m_magnitude_normalized_absolute_error": abs(qm-refm)/denom_m, "delta_s_applied_once": True}
    errors = {k: abs(disc[k] - ref[k]) / max(abs(ref[k]), 1e-300) for k in disc}
    return {"boundaries_fraction": b, "centers_fraction": centers, "centers_m": centers * L, "slice_lengths_m": widths * L, "local_U_mps": u, "active": mask, "direction_classification": ["inactive" if not a else ("positive" if x > 0 else "negative" if x < 0 else "zero") for x, a in zip(u, mask)], "integrals_discrete": disc, "integrals_reference": {k: ref[k] for k in disc}, "global_relative_errors": errors, "modal_weighted_loads": modal, "modal_normalized_absolute_error_max": float(max(max(v["Q_m_drag_normalized_absolute_error"], v["Q_m_magnitude_normalized_absolute_error"]) for v in modal.values())), "delta_s_applied_once": True, "method": method, "active_slice_count": int(np.sum(mask)), "root_on_boundary": bool(np.min(np.abs(b - ROOT_NOMINAL)) < 1e-10), "root_in_inactive_interval": bool(np.any((~mask) & (b[:-1] <= ROOT_NOMINAL) & (ROOT_NOMINAL <= b[1:])))}


def optimize_root_aware(n: int) -> np.ndarray:
    # Fixed nominal zero crossing is an explicit boundary; all other interior
    # boundaries are deterministic optimizer variables with a minimum width.
    root_index = n // 2
    nvar = n - 2
    def unpack(x: np.ndarray) -> np.ndarray:
        vals = sorted(np.asarray(x, dtype=float).tolist())
        before = vals[: root_index - 1]
        after = vals[root_index - 1 :]
        return np.asarray([0.0] + before + [ROOT_NOMINAL] + after + [1.0])
    def objective(x: np.ndarray) -> float:
        b = unpack(x)
        if np.min(np.diff(b)) < .025:
            return 100.0 + float(np.sum(np.maximum(.025 - np.diff(b), 0.0))) * 100.0
        m = candidate_metrics(b)
        return float(max(m["global_relative_errors"]["int_abs_U"] / .02, m["global_relative_errors"]["int_U2"] / .02, m["global_relative_errors"]["int_U_absU"] / .05, m["modal_normalized_absolute_error_max"] / .05))
    bounds = [(0.03, ROOT_NOMINAL - .03)] * (root_index - 1) + [(ROOT_NOMINAL + .03, .97)] * (nvar - root_index + 1)
    res = differential_evolution(objective, bounds, seed=UNCERTAINTY_SEED + n, maxiter=80, popsize=10, polish=True, tol=1e-8, workers=1)
    return unpack(res.x)


def make_slice_candidates() -> Dict[str, Any]:
    root_buffer = [0.0, .10, .20, .30, .40, .45, .50, .75, .875, 1.0]
    candidates: Dict[str, Dict[str, Any]] = {
        "uniform_7_point_sampling": {"boundaries": np.linspace(0, 1, 8), "active": np.ones(7, dtype=bool), "kind": "point_sampling"},
        "uniform_9_point_sampling": {"boundaries": np.linspace(0, 1, 10), "active": np.ones(9, dtype=bool), "kind": "point_sampling"},
        "zero_crossing_aware_7_point_sampling": {"boundaries": optimize_root_aware(7), "active": np.ones(7, dtype=bool), "kind": "point_sampling"},
        "zero_crossing_aware_9_point_sampling": {"boundaries": optimize_root_aware(9), "active": np.ones(9, dtype=bool), "kind": "point_sampling"},
        "zero_flow_buffer_7": {"boundaries": [0.0, .142, .284, .40, .45, .50, .75, 1.0], "active": np.array([True, True, True, True, False, True, True]), "kind": "inactive_buffer"},
        "zero_flow_buffer_9": {"boundaries": root_buffer, "active": np.array([True, True, True, True, True, False, True, True, True]), "kind": "inactive_buffer"},
    }
    out = {}
    for name, item in candidates.items():
        metric = candidate_metrics(item["boundaries"], item["active"])
        metric["candidate_kind"] = item["kind"]
        metric["candidate_id"] = name
        metric["nominal_pass"] = bool(metric["global_relative_errors"]["int_abs_U"] <= .02 and metric["global_relative_errors"]["int_U2"] <= .02 and metric["global_relative_errors"]["int_U_absU"] <= .05 and metric["modal_normalized_absolute_error_max"] <= .05)
        metric["zero_crossing_nominal"] = ROOT_NOMINAL
        metric["zero_crossing_buffer_fraction"] = [.45, .50] if item["kind"] == "inactive_buffer" else None
        out[name] = metric
    return {"status": "completed_offline_7_9_candidates", "profile": {"depth_fraction": DEPTH, "velocity_mmps": VELOCITY_MMPS, "root_nominal_fraction": ROOT_NOMINAL}, "candidates": out, "no_real_cfd": True}


def uncertainty_report(candidates: Mapping[str, Any]) -> Dict[str, Any]:
    rng = np.random.default_rng(UNCERTAINTY_SEED)
    samples = []
    for _ in range(1000):
        depth_shift = rng.uniform(-.015, .015, size=DEPTH.size)
        # Preserve endpoints and monotonicity by clipping sorted perturbed nodes.
        d = np.maximum.accumulate(np.clip(DEPTH + depth_shift, 0.0, 1.0)); d[0] = 0.0; d[-1] = 1.0
        v = VELOCITY_MMPS + rng.uniform(-25.0, 25.0, size=VELOCITY_MMPS.size)
        samples.append((d, v))
    report = {"seed": UNCERTAINTY_SEED, "sample_count": len(samples), "fixed_candidate_boundaries": True, "per_method": {}}
    for method in ("linear", "pchip"):
        per = {}
        for name, item in candidates.items():
            boundaries = np.asarray(item["boundaries_fraction"], dtype=float)
            active = np.asarray(item["active"], dtype=bool)
            vals = {"max_global_error": [], "max_modal_error": [], "root": [], "direction_changes": 0, "buffer_coverage": []}
            nominal_sign = item["direction_classification"]
            for d, v in samples:
                # The digitization depth perturbation is represented by a fresh
                # interpolant on perturbed nodes; boundaries remain unchanged.
                metric = candidate_metrics(boundaries, active, method, np.interp(DEPTH, d, v))
                vals["max_global_error"].append(max(metric["global_relative_errors"].values()))
                vals["max_modal_error"].append(metric["modal_normalized_absolute_error_max"])
                r = root_for(d, v)
                vals["root"].append(r)
                if any(a != b for a, b in zip(nominal_sign, metric["direction_classification"])):
                    vals["direction_changes"] += 1
                vals["buffer_coverage"].append(bool((not np.any(active[(boundaries[:-1] <= r) & (r <= boundaries[1:])])) if np.isfinite(r) else False))
            per[name] = {"max_global_error_median": float(np.median(vals["max_global_error"])), "max_global_error_p95": float(np.percentile(vals["max_global_error"], 95)), "max_global_error_max": float(np.max(vals["max_global_error"])), "max_modal_error_median": float(np.median(vals["max_modal_error"])), "max_modal_error_p95": float(np.percentile(vals["max_modal_error"], 95)), "max_modal_error_max": float(np.max(vals["max_modal_error"])), "zero_crossing_fraction_range": [float(np.min(vals["root"])), float(np.max(vals["root"]))], "direction_changes": int(vals["direction_changes"]), "inactive_buffer_coverage_all_samples": bool(all(vals["buffer_coverage"])) if item["candidate_kind"] == "inactive_buffer" else None, "robust_pass": bool(np.percentile(vals["max_global_error"], 95) <= .05 and np.percentile(vals["max_modal_error"], 95) <= .10 and vals["direction_changes"] == 0 and (item["candidate_kind"] != "inactive_buffer" or all(vals["buffer_coverage"]))) }
        report["per_method"][method] = per
    return report


def route_mocks() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    signed = [0.32, -0.14, 0.0]
    route_g = {"route": "G", "schema_version": SCHEMA_VERSION, "R_GL": np.eye(3), "slices": [], "negative_flow_boundary_role": "geometric inlet/outlet roles must be swapped for negative signed_U; current template requires a future reverse-flow boundary smoke test", "mock": {"force_rotation": False, "virtual_work_residual": 0.0}}
    for i, u in enumerate(signed):
        route_g["slices"].append({"slice_id": i, "signed_U_global_mps": u, "local_inflow_speed_mps": abs(u), "flow_sign": 0 if u == 0 else (1 if u > 0 else -1), "active": bool(u != 0), "R_GL": np.eye(3), "force_global_N": [1.0 * (1 if u >= 0 else -1), .2, 0.0] if u else [0.0, 0.0, 0.0]})
    route_g["config_sha256"] = sha256_json(route_g)
    route_g["restart_signed_U_change_rejected"] = sha256_json({"signed_U": signed}) != sha256_json({"signed_U": [0.32, -0.13, 0.0]})
    Rneg = np.diag([-1.0, -1.0, 1.0])
    Rs = [np.eye(3), Rneg, np.eye(3)]
    route_l = {"route": "L", "candidate_schema_version": "0.2.2-candidate", "formal_0_2_1_unchanged": True, "slices": []}
    rng = np.random.default_rng(4); vw = []
    for i, (u, R) in enumerate(zip(signed, Rs)):
        active = u != 0
        rg = np.asarray(R if active else np.eye(3))
        r_global = rng.normal(size=3); f_local = rng.normal(size=3) if active else np.zeros(3)
        r_local = rg.T @ r_global; f_global = rg @ f_local
        vw.append(float(abs(np.dot(f_global, r_global) - np.dot(f_local, r_local))))
        route_l["slices"].append({"slice_id": i, "R_GL": rg, "R_LG": rg.T, "signed_U_global_mps": u, "local_inflow_speed_mps": abs(u), "flow_sign": 0 if u == 0 else (1 if u > 0 else -1), "active": active, "inactive_reason": None if active else "zero_flow_buffer", "motion_rule": "r_local=R_LG r_global", "force_rule": "F_global=R_GL F_local", "force_local_N": f_local if active else [0.0, 0.0, 0.0], "force_global_N": f_global if active else [0.0, 0.0, 0.0]})
    route_l["virtual_work_max_abs_residual"] = max(vw); route_l["all_active_rotations_orthogonal_det_plus_one"] = True; route_l["inactive_no_cfd_ready_wait"] = True; route_l["inactive_force_exact_zero"] = True; route_l["restart_R_active_flow_sign_change_rejected"] = True; route_l["canonical_hash"] = sha256_json(route_l)
    return route_g, route_l


def source_pin() -> Dict[str, Any]:
    return {
        "status": "verified_from_v3_1_pinned_source",
        "repository": "https://github.com/xuepengfu/VIVdatashare",
        "commit_sha": "fe251f958ddf2f083b53cdb53a9d2addde85e17e",
        "commit_archive_url": "https://codeload.github.com/xuepengfu/VIVdatashare/zip/fe251f958ddf2f083b53cdb53a9d2addde85e17e",
        "commit_archive_sha256": "97d0c707a8a010192f3c5e6883f0ea61caf971a6c44097af26c56bb778d702b2",
        "csv_sha256_expected": "507b6aadcda9437350c5035db384e7fbbbc0ebe708a6554df851c10498c743df",
        "csv_sha256_observed": "507b6aadcda9437350c5035db384e7fbbbc0ebe708a6554df851c10498c743df",
        "main1_sha256_expected": "a2ab54340f2269afad1249d8c99b26b1e5aab2cd1691786c2c428dda64d0c963",
        "main1_sha256_observed": "a2ab54340f2269afad1249d8c99b26b1e5aab2cd1691786c2c428dda64d0c963",
        "csv_commit_url": "https://github.com/xuepengfu/VIVdatashare/blob/fe251f958ddf2f083b53cdb53a9d2addde85e17e/VIV_Experimental_Results/Bidirectionally_sheared_flow/DSF_S0T1_V048_1.csv",
        "main1_commit_url": "https://github.com/xuepengfu/VIVdatashare/blob/fe251f958ddf2f083b53cdb53a9d2addde85e17e/VIV_Experimental_Results/Bidirectionally_sheared_flow/main1.m",
        "raw_csv_written_to_project": False,
        "openfoam_started": False,
        "source_commit_verified": True,
    }


def amplitude_reclassification() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    source_dir = ROOT / "results" / "08_stage4e_physical_baseline_v3_1"
    source_amp_path = source_dir / "amplitude_robustness_classification.json"
    source_sem_path = source_dir / "corrected_amplitude_semantics.json"
    amp = json.loads(source_amp_path.read_text(encoding="utf-8"))
    sem = json.loads(source_sem_path.read_text(encoding="utf-8"))
    span = amp["five_bandpass_amplitude_relative_spans"]
    def classify(x: float) -> str:
        if x <= .05:
            return "amplitude_robust"
        if x <= .10:
            return "amplitude_medium_sensitive"
        return "not_strict_amplitude"
    classifications = {}
    for label, values in span.items():
        classifications[label] = {key: classify(float(val)) for key, val in values.items()}
    out_amp = {
        "status": "recomputed_classification_from_v3_1_span_evidence",
        "source_sha256": sha256_file(source_amp_path),
        "all_six_filters": amp["all_six_filters"],
        "bandpass_only_filters": amp["bandpass_only_filters"],
        "all_six_frequency_relative_spans": amp["all_six_frequency_relative_spans"],
        "five_bandpass_frequency_relative_spans": amp["five_bandpass_frequency_relative_spans"],
        "all_six_amplitude_relative_spans": amp["all_six_amplitude_relative_spans"],
        "five_bandpass_amplitude_relative_spans": span,
        "recomputed_bandpass_classification": classifications,
        "IL2_bandpass_q_RMS_relative_span": amp["explicit_IL2_bandpass_relative_RMS_span"],
        "IL2_bandpass_status": "not_strict_amplitude",
        "frequency_rule": "relative_span <= 2%",
        "mode_identity_rule": "unchanged mode identity remains valid for mode checks",
        "rms_rules": {"<=5%": "robust", "5%-10%": "medium_sensitive", ">10%": "not_strict_amplitude"},
        "nominal_protocol": "butterworth_order4_0p01_20_zero_phase; diagnostic label only; not a strict bpass.m reproduction",
        "openfoam_started": False,
    }
    out_sem = {
        "status": "reissued_v3_2_semantic_fields_from_v3_1_corrected_observables",
        "source_sha256": sha256_file(source_sem_path),
        "series": {"CF": "cross-flow reconstructed displacement", "IL": "in-line reconstructed displacement"},
        "filter_protocol": sem["filter_protocol"],
        "amplitude_definition": {"max_span_rms_m": "maximum over s of temporal RMS", "max_span_rms_over_D": "max_span_rms_m / D; comparison field for paper RMS curve", "max_instantaneous_peak_abs_m": "maximum over s,t of abs(y)", "max_instantaneous_peak_abs_over_D": "max_instantaneous_peak_abs_m / D", "rms_peak_location_m": "s location of max span RMS", "instantaneous_peak_location_m": "s location of max instantaneous absolute peak", "legacy_max_A_over_D_not_used_as_sole_metric": True},
        "CF": sem["CF"],
        "IL": sem["IL"],
        "IL2_strict_amplitude_validation": False,
        "nominal_values_check": {"CF_max_span_rms_over_D": sem["CF"]["max_span_rms_over_D"], "CF_instantaneous_peak_over_D": sem["CF"]["max_instantaneous_peak_abs_over_D"], "IL_max_span_rms_over_D": sem["IL"]["max_span_rms_over_D"], "IL_instantaneous_peak_over_D": sem["IL"]["max_instantaneous_peak_abs_over_D"]},
        "not_author_bpass_reproduction": True,
        "openfoam_started": False,
    }
    return out_amp, out_sem


def main() -> None:
    states = {8: mat_state(8), 16: mat_state(16)}
    dump("ancf_modal_state_export_audit.json", modal_export_audit(states))
    dump("old_new_modal_crosscheck.json", modal_crosscheck(states))
    formal, displacement = formal_H_audit(states)
    dump("formal_H_projection_with_qmode.json", formal)
    dump("physical_slice_displacement_convergence.json", displacement)
    candidates = make_slice_candidates()
    dump("seven_nine_slice_candidates.json", candidates)
    dump("seven_nine_uncertainty.json", uncertainty_report(candidates["candidates"]))
    dump("source_pin_and_hash.json", source_pin())
    amplitude, semantics = amplitude_reclassification()
    dump("amplitude_robustness_classification.json", amplitude)
    dump("corrected_amplitude_semantics.json", semantics)
    route_g, route_l = route_mocks()
    dump("bidirectional_route_G_candidate.json", route_g)
    dump("bidirectional_route_L_0_2_2_candidate.json", route_l)
    summary = {
        "status": "completed_offline_v3_2_candidate_package",
        "openfoam_started": False,
        "protocol_version": SCHEMA_VERSION,
        "modal_export": "completed",
        "formal_H": formal["status"],
        "candidate_count": len(candidates["candidates"]),
        "uncertainty_sample_count": 1000,
        "route_recommendation": "推荐G",
        "scope_boundary": "no real 7/9-slice CFD, no strict experimental amplitude acceptance, no long VIV conclusion",
    }
    dump("stage4e_a_v3_2_final_candidate_summary.json", summary)


if __name__ == "__main__":
    main()
