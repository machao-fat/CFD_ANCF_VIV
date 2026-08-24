"""Shared, Ur-independent physical lock-in classification for v6."""

from __future__ import annotations

import math


def classify_lockin(
    *,
    final_steady_window_pass: bool,
    frequency_state: str,
    response_frequency_reliable: bool,
    y_rms_m: float,
    amplitude_baseline_m: float,
    mean_power_W: float,
    force_velocity_phase_deg: float,
    power_noise_floor_W: float,
    quasi_periodic: bool = False,
) -> str:
    """Classify physical state without using Ur-specific branches.

    The amplitude baseline is supplied by the campaign audit (not by Ur
    number).  Phase is only an auxiliary sign check; positive cycle-average
    power is the primary energy-input condition.  NaN phase never silently
    becomes lock-in.
    """
    if quasi_periodic and final_steady_window_pass:
        return "quasi_periodic_or_multifrequency"
    if not final_steady_window_pass:
        return "transitional_or_unsteady"
    if not response_frequency_reliable or frequency_state == "frequency_unresolved":
        return "frequency_unresolved"
    phase_positive = math.isfinite(force_velocity_phase_deg) and math.cos(math.radians(force_velocity_phase_deg)) > 0.0
    amplitude_significant = math.isfinite(y_rms_m) and math.isfinite(amplitude_baseline_m) and y_rms_m > 1.5 * max(amplitude_baseline_m, 1.0e-30)
    if frequency_state == "frequency_synchronized" and mean_power_W > power_noise_floor_W and phase_positive and amplitude_significant:
        return "locked_or_near_lockin"
    return "outside_lockin"
