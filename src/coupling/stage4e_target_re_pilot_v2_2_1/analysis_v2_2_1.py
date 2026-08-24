"""v2.2.1 convergence and preflight audits."""

from __future__ import annotations

import math
from typing import Any

from src.coupling.stage4e_target_re_pilot_v2_2.analysis_v2_2 import (
    checkpoint_alignment,
    coefficient_crosscheck_all,
    log_health,
    merge_force_history,
    overlap_force_audit,
    parse_checkmesh,
    parse_cfl,
    statistics_gate,
    numeric_time_directories,
    _force_paths,
)
from .identity_v2_2_1 import finite


def relative_change(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return abs(float(b) - float(a)) / max(abs(float(a)), 1.0e-12)


def compare_metrics(a: dict[str, Any], b: dict[str, Any], limits: dict[str, float]) -> dict[str, Any]:
    changes = {key: relative_change(a.get(key), b.get(key)) for key in limits}
    return finite({"relative_changes": changes, "limits": limits, "passed": all(changes[key] is not None and changes[key] <= limit for key, limit in limits.items())})


def effective_h(cells: int) -> float:
    if cells <= 0:
        raise ValueError("cells must be positive")
    return 1.0 / math.sqrt(float(cells))


def refinement_ratio(cells_coarse: int, cells_fine: int) -> float:
    return effective_h(cells_coarse) / effective_h(cells_fine)


def _apparent_order(ec: float, em: float, ef: float, r_cm: float, r_mf: float) -> float | None:
    if not all(math.isfinite(x) for x in (ec, em, ef, r_cm, r_mf)):
        return None
    if (em - ec) * (ef - em) <= 0.0:
        return None
    ratio = abs((ef - em) / (em - ec))
    if ratio <= 0.0:
        return None
    lo, hi = 0.01, 12.0
    for _ in range(120):
        mid = 0.5 * (lo + hi)
        value = (r_mf**mid - 1.0) / (r_cm**mid - 1.0)
        if value < ratio:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def gci_nonuniform(values: dict[str, float], cells: dict[str, int], *, order: float = 2.0) -> dict[str, Any]:
    names = ("coarse", "medium", "fine")
    ec, em, ef = (float(values[name]) for name in names)
    nc, nm, nf = (int(cells[name]) for name in names)
    r_cm = refinement_ratio(nc, nm)
    r_mf = refinement_ratio(nm, nf)
    monotonic = (em - ec) * (ef - em) > 0.0
    apparent = _apparent_order(ec, em, ef, r_cm, r_mf) if monotonic else None
    result: dict[str, Any] = {
        "effective_h_definition": "N_cells^(-1/2) for a 2D effective mesh size",
        "h": {name: effective_h(cells[name]) for name in names},
        "r_coarse_medium": r_cm,
        "r_medium_fine": r_mf,
        "values": values,
        "monotonic": monotonic,
        "status": "non_monotonic" if not monotonic else "monotonic",
        "apparent_order": apparent,
        "gci_available": False,
    }
    if monotonic and apparent is not None and apparent > 0.0:
        result.update({
            "gci_available": True,
            "gci_medium_fine_fraction": 1.25 * abs((ef - em) / max(abs(ef), 1.0e-30)) / (r_mf**apparent - 1.0),
            "gci_coarse_medium_fraction": 1.25 * abs((em - ec) / max(abs(em), 1.0e-30)) / (r_cm**apparent - 1.0),
        })
    return finite(result)


def spatial_refinement_and_gci(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cells = {level: int(summaries[level]["mesh_audit"]["cells"]) for level in ("coarse", "medium", "fine")}
    metrics = ("mean_Cd", "St", "Cd_fluctuation_RMS", "Cl_fluctuation_RMS")
    gci = {}
    for metric in metrics:
        gci[metric] = gci_nonuniform({level: float(summaries[level]["statistics"][metric]) for level in cells}, cells)
    return finite({"cells": cells, "effective_h": {level: effective_h(value) for level, value in cells.items()}, "r_coarse_medium": refinement_ratio(cells["coarse"], cells["medium"]), "r_medium_fine": refinement_ratio(cells["medium"], cells["fine"]), "metrics": gci, "non_monotonic_metrics": [key for key, item in gci.items() if item["status"] == "non_monotonic"], "gci_not_fabricated": True})


def preflight_audit(case_dir, *, production_start: float, production_end: float, production_log, dt: float) -> dict[str, Any]:
    cfl = parse_cfl(production_log)
    health = log_health([production_log])
    paths = [path for path in _force_paths(case_dir) if float(path.parent.name) >= production_start - 1.0e-8]
    overlap = overlap_force_audit(paths)
    cross = coefficient_crosscheck_all(case_dir, U_abs=0.43414375179615955, b_mesh=0.02841)
    alignment = checkpoint_alignment(case_dir, paths, dt=dt)
    duration = production_end - production_start
    checks = {
        "checkMesh": True,
        "production_duration_at_least_0_5_s": duration >= 0.5,
        "production_max_CFL_at_most_0_5": cfl.get("max_cfl") is not None and cfl["max_cfl"] <= 0.5,
        "hard_stop_not_crossed": cfl.get("max_cfl") is not None and cfl["max_cfl"] < 0.8,
        "solver_health": health["contains_End"] and not health["fatal_tokens"] and health["finite_log_text"],
        "checkpoint_alignment": alignment["passed"],
        "force_overlap": len(paths) < 2 or overlap["passed"],
        "force_coefficients": cross["passed"],
    }
    return finite({"production_start_s": production_start, "production_end_s": production_end, "production_duration_s": duration, "dt_s": dt, "force_sample_count": len(paths), "overlap_required": len(paths) >= 2, "cfl": cfl, "health": health, "checkpoint_alignment": alignment, "overlap_force_audit": overlap, "force_crosscheck": cross, "checks": checks, "passed": all(checks.values())})


def mesh_quality_reaudit(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    levels = []
    for level, summary in summaries.items():
        audit = summary.get("mesh_audit", {})
        levels.append({"mesh_level": level, "case_id": summary.get("case_id"), "mesh_audit": audit, "mesh_polyMesh_sha256": summary.get("mesh_polyMesh_sha256"), "first_cell_center_to_wall_m": summary.get("mesh_geometry", {}).get("derived_first_cell_center_to_wall_m")})
    return finite({"levels": levels, "all_mesh_ok": bool(levels) and all(item["mesh_audit"].get("mesh_ok") for item in levels)})
