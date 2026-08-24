"""Energy bookkeeping for the one-pass file-coupling audit.

The CFD-side work uses the predicted interface velocity, while the structure
side work uses the corrected velocity.  The audit deliberately distinguishes
an explicit, user-selected physical window from the default last-half
diagnostic window; selecting the latter does not establish statistical
stationarity.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable


def _number(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key, "")
    if value in (None, ""):
        return default
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{key} is NaN/Inf at step {row.get('step')}")
    return out


def _initial_stored_energy(
    first: dict[str, Any],
    stored: float,
    supplied: float | None,
) -> tuple[float, str, bool]:
    if supplied is not None:
        value = float(supplied)
        if not math.isfinite(value):
            raise ValueError("initial_stored_energy_J is NaN/Inf")
        return value, "function_argument", True
    if first.get("stored_energy_previous_J", "") not in (None, ""):
        return _number(first, "stored_energy_previous_J"), "first_row_previous_state", True
    if first.get("delta_stored_energy_J", "") not in (None, ""):
        # Historical Stage-three CSVs contain this column, but it was
        # generated after the initial-energy unwrapping bug and is therefore
        # not an independent checkpoint value.  Preserve the numerical
        # reconstruction for diagnostics while refusing physical acceptance.
        return stored-_number(first, "delta_stored_energy_J"), "inferred_unverified_first_row_delta", False
    # Keep legacy CSVs readable, but make the assumption explicit so the
    # resulting full-window residual cannot be used as physical acceptance.
    return 0.0, "assumed_zero_legacy_fallback", False


def _validate_force_representation(source: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    per_row = [str(row.get("force_representation", "")).strip() for row in source]
    values = sorted({value for value in per_row if value})
    if any(value != "integrated_N" for value in values):
        raise ValueError(f"energy audit requires integrated_N loads, found {values}")
    return bool(per_row) and all(value == "integrated_N" for value in per_row), values


def _aligned_index(times: list[float], boundary: float, *, allow_initial: float | None = None) -> int | None:
    tolerance = 1.0e-10*max(1.0, abs(boundary))
    if allow_initial is not None and abs(boundary-allow_initial) <= tolerance:
        return -1
    for index, value in enumerate(times):
        if abs(value-boundary) <= tolerance:
            return index
    return None


def compute_energy_rows(
    rows: Iterable[dict[str, Any]],
    *,
    initial_stored_energy_J: float | None = None,
    window_start_s: float | None = None,
    window_end_s: float | None = None,
    steady_state_verified: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Integrate interface work and structural energy over aligned steps.

    ``window_start_s`` and ``window_end_s`` are state-time boundaries.  The
    audit includes increments on ``(window_start_s, window_end_s]`` and
    therefore requires both boundaries to coincide with recorded states (or
    the inferred initial state).  Power/damping use right-endpoint rectangle
    quadrature, matching the current Stage-three online driver definition.
    """
    source = list(rows)
    if not source:
        raise ValueError("energy audit requires at least one row")
    force_unit_verified, representations = _validate_force_representation(source)
    out: list[dict[str, Any]] = []
    w_cfd = w_structure = defect = projection_defect = temporal_defect = damping_work = structure_balance = 0.0
    work_throughput = 0.0
    previous_time = 0.0
    explicit_stored = "stored_energy_J" in source[0]
    first_stored = _number(source[0], "stored_energy_J" if explicit_stored else "mechanical_energy_J")
    previous_stored, initial_source, initial_known = _initial_stored_energy(source[0], first_stored, initial_stored_energy_J)
    inferred_initial_time: float | None = None

    for index, row in enumerate(source):
        time_s = _number(row, "time_s")
        if index:
            dt = time_s-previous_time
        else:
            step = int(float(row.get("step", 1)))
            dt = _number(row, "dt_s", time_s/max(1, step))
            inferred_initial_time = time_s-dt
        if dt <= 0 or not math.isfinite(dt):
            raise ValueError(f"non-positive dt at step {row.get('step')}")
        fx, fy, fz = (_number(row, key) for key in ("force_x_N", "force_y_N", "force_z_N"))
        applied_force = tuple(
            _number(row, f"applied_force_{axis}_N", raw)
            for axis, raw in zip(("x", "y", "z"), (fx, fy, fz))
        )
        pred = tuple(_number(row, key) for key in ("predicted_vx_mps", "predicted_vy_mps", "predicted_vz_mps"))
        corr = tuple(_number(row, key) for key in ("corrected_vx_mps", "corrected_vy_mps", "corrected_vz_mps"))
        p_cfd = fx*pred[0] + fy*pred[1] + fz*pred[2]
        p_structure = sum(force*velocity for force, velocity in zip(applied_force, corr))
        p_projection_defect = sum((raw-applied)*velocity for raw, applied, velocity in zip((fx, fy, fz), applied_force, pred))
        p_temporal_defect = sum(force*(vp-vc) for force, vp, vc in zip(applied_force, pred, corr))
        damping_power = _number(row, "damping_power_W")
        if damping_power < -1.0e-12:
            raise ValueError(f"negative damping dissipation at step {row.get('step')}")
        stored = _number(row, "stored_energy_J" if explicit_stored else "mechanical_energy_J")
        # For every step after the first, the previous recorded state is the
        # authoritative boundary.  The explicit first-row value only supplies
        # the state at the beginning of the audited file.
        boundary_stored = previous_stored
        delta_stored = stored-boundary_stored
        work_cfd_increment = p_cfd*dt
        work_structure_increment = p_structure*dt
        defect_increment = (p_cfd-p_structure)*dt
        projection_defect_increment = p_projection_defect*dt
        temporal_defect_increment = p_temporal_defect*dt
        damping_increment = damping_power*dt
        balance_increment = work_structure_increment-delta_stored-damping_increment
        w_cfd += work_cfd_increment
        w_structure += work_structure_increment
        defect += defect_increment
        projection_defect += projection_defect_increment
        temporal_defect += temporal_defect_increment
        damping_work += damping_increment
        structure_balance += balance_increment
        work_throughput += abs(work_structure_increment)
        out.append({
            "step": int(float(row["step"])), "time_s": time_s, "dt_s": dt,
            "power_cfd_predicted_W": p_cfd, "power_structure_corrected_W": p_structure,
            "power_coupling_defect_W": p_cfd-p_structure,
            "power_load_projection_defect_W": p_projection_defect,
            "power_predictor_corrector_defect_W": p_temporal_defect,
            "fluid_work_cfd_increment_J": work_cfd_increment,
            "structure_work_increment_J": work_structure_increment,
            "coupling_defect_increment_J": defect_increment,
            "load_projection_defect_increment_J": projection_defect_increment,
            "predictor_corrector_defect_increment_J": temporal_defect_increment,
            "damping_increment_J": damping_increment,
            "fluid_work_cfd_J": w_cfd, "structure_work_J": w_structure,
            "coupling_defect_work_J": defect, "damping_power_W": damping_power,
            "load_projection_defect_work_J": projection_defect,
            "predictor_corrector_defect_work_J": temporal_defect,
            "damping_dissipation_J": damping_work, "stored_energy_previous_J": boundary_stored,
            "stored_energy_J": stored, "delta_stored_energy_J": delta_stored,
            "structure_energy_balance_increment_J": balance_increment,
            "structure_energy_balance_residual_J": structure_balance,
        })
        previous_time = time_s
        previous_stored = stored

    times = [float(row["time_s"]) for row in out]
    explicit_window = window_start_s is not None or window_end_s is not None
    if explicit_window:
        start = float(window_start_s if window_start_s is not None else inferred_initial_time)
        end = float(window_end_s if window_end_s is not None else times[-1])
        start_index = _aligned_index(times, start, allow_initial=inferred_initial_time)
        end_index = _aligned_index(times, end)
        if start_index is None or end_index is None or end_index <= start_index:
            raise ValueError("energy window boundaries must align with recorded states and have positive duration")
        selected = out[start_index+1:end_index+1]
        window_definition = "explicit_state_time_interval"
    else:
        first_index = len(out)//2
        selected = out[first_index:]
        start = float(selected[0]["time_s"])-float(selected[0]["dt_s"])
        end = float(selected[-1]["time_s"])
        window_definition = "heuristic_last_half_not_verified_steady"

    def summed(key: str) -> float:
        return sum(float(row[key]) for row in selected)

    window_w_cfd = summed("fluid_work_cfd_increment_J")
    window_w_structure = summed("structure_work_increment_J")
    window_defect = summed("coupling_defect_increment_J")
    window_projection_defect = summed("load_projection_defect_increment_J")
    window_temporal_defect = summed("predictor_corrector_defect_increment_J")
    window_damping = summed("damping_increment_J")
    window_stored_change = summed("delta_stored_energy_J")
    window_balance = summed("structure_energy_balance_increment_J")
    window_throughput = sum(abs(float(row["structure_work_increment_J"])) for row in selected)
    full_stored_change = float(out[-1]["stored_energy_J"])-float(out[0]["stored_energy_previous_J"])
    full_scale = max(abs(w_structure), abs(full_stored_change), abs(damping_work), work_throughput, 1.0e-30)
    window_scale = max(abs(window_w_structure), abs(window_stored_change), abs(window_damping), window_throughput, 1.0e-30)
    window_initial_known = initial_known or selected[0] is not out[0]
    summary = {
        "steps": len(out), "time_end_s": times[-1],
        "power_quadrature": "right_endpoint_rectangle",
        "energy_units": {"force": "N", "velocity": "m/s", "power": "W", "work_and_energy": "J", "time": "s"},
        "force_representation_values": representations,
        "force_unit_verified_integrated_N": force_unit_verified,
        "explicit_stored_energy": explicit_stored,
        "initial_stored_energy_J": float(out[0]["stored_energy_previous_J"]),
        "initial_stored_energy_source": initial_source,
        "initial_stored_energy_known": initial_known,
        "W_CFD_J": w_cfd, "W_structure_J": w_structure,
        "E_coupling_defect_J": defect, "W_damping_J": damping_work,
        "E_load_projection_defect_J": projection_defect,
        "E_predictor_corrector_defect_J": temporal_defect,
        "coupling_defect_decomposition_closure_J": defect-projection_defect-temporal_defect,
        "stored_energy_change_J": full_stored_change,
        "structure_work_throughput_J": work_throughput,
        "structure_energy_balance_residual_J": structure_balance,
        "structure_energy_balance_relative": abs(structure_balance)/full_scale,
        "audit_window_definition": window_definition,
        "audit_window_explicit": explicit_window,
        "audit_window_steady_state_verified_by_caller": bool(steady_state_verified),
        "audit_window_start_s": start, "audit_window_end_s": end,
        "audit_window_duration_s": end-start, "audit_window_steps": len(selected),
        "audit_window_initial_energy_known": window_initial_known,
        "audit_window_W_CFD_J": window_w_cfd,
        "audit_window_W_structure_J": window_w_structure,
        "audit_window_coupling_defect_J": window_defect,
        "audit_window_load_projection_defect_J": window_projection_defect,
        "audit_window_predictor_corrector_defect_J": window_temporal_defect,
        "audit_window_defect_decomposition_closure_J": window_defect-window_projection_defect-window_temporal_defect,
        "audit_window_W_damping_J": window_damping,
        "audit_window_stored_energy_change_J": window_stored_change,
        "audit_window_structure_work_throughput_J": window_throughput,
        "audit_window_structure_balance_residual_J": window_balance,
        "audit_window_structure_balance_relative": abs(window_balance)/window_scale,
        "physical_energy_acceptance_ready": bool(
            explicit_window and steady_state_verified and explicit_stored
            and window_initial_known and force_unit_verified
        ),
        # Backward-compatible aliases.  These name the selected audit window;
        # the definition field states whether it is actually a steady window.
        "stable_window_steps": len(selected),
        "stable_window_W_CFD_J": window_w_cfd,
        "stable_window_W_structure_J": window_w_structure,
        "stable_window_coupling_defect_J": window_defect,
        "stable_window_W_damping_J": window_damping,
        "stable_window_stored_energy_change_J": window_stored_change,
        "stable_window_structure_balance_residual_J": window_balance,
    }
    return out, summary


def audit_csv(
    input_path: str | Path,
    output_csv: str | Path,
    output_json: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    with Path(input_path).open("r", newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    audit_rows, summary = compute_energy_rows(rows, **kwargs)
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    with Path(output_csv).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(audit_rows[0]))
        writer.writeheader()
        writer.writerows(audit_rows)
    Path(output_json).write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    return summary
