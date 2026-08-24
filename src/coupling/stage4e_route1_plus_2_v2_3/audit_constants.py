"""Frozen audit constants for Stage 4E-B2-A-v2.3 (methodology freeze + high-Re URANS pilot).

This module is read-only audit support code. It does NOT run OpenFOAM and does NOT
change any frozen project direction. It is independent of the ANCF/EB/core modules.
"""

import math

# Frozen physical parameters (from Sol's frozen v2.2.2 maximum-forward-slice set).
U_MPS = 0.43414375179615955
D_M = 0.02841
NU_M2PS = 1.0e-6
RHO_KGPM3 = 1000.0
RE = abs(U_MPS) * D_M / NU_M2PS

# Actual extruded thickness read from mesh bounding box (frozen for fixed cylinder).
B_MESH_M = 0.02841
AREF_M2 = D_M * B_MESH_M  # == 0.0008071281

# CFL gates.
CFL_TARGET = 0.5
CFL_HARD_STOP = 0.8

# Scenario limits.
MAX_ENTRY_SCENARIOS = 2
FORBIDDEN_MODELS = ("kEpsilon", "kOmega", "kOmegaSST", "SpalartAllmaras")  # any model beyond the single authorized one

# Transition model entry contract (scenario N nominal).
TU_N_PERCENT = 1.0
I_N = 0.01
LT_OVER_D_N = 0.07
CMU = 0.09

# Scenario S (upper sensitivity) — source-verified from legacy kOmegaSST case.
TU_S_PERCENT = 4.472135954999579
K_S_M2PS2 = 0.000565442391670936
OMEGA_S_1PS = 305.627421187018


def rethetat0_zero_pressure_gradient(tu_percent):
    """OpenFOAM 10 kOmegaSSTLM ReThetat0 correlation for dU/ds <= 0.

    The source defines ``Tu = 100*sqrt((2/3)*k)/Us`` and uses Tu in percent.
    With lambda initialised to zero, Flambda is one for a zero-pressure-gradient
    inlet.  This helper is an independent audit implementation, not a fitted
    CFD parameter.
    """
    tu = float(tu_percent)
    if not math.isfinite(tu) or tu < 0:
        raise ValueError("Tu must be finite and non-negative")
    if tu <= 1.3:
        value = 1173.51 - 589.428 * tu + 0.2196 / (tu * tu)
    else:
        value = 331.50 * (tu - 0.5658) ** (-0.671)
    return max(value, 20.0)


def k_from_intensity(U, I):
    """k = 1.5 * (abs(U) * I)^2  [m2/s2]. I is a fraction, NOT a percent."""
    return 1.5 * (abs(U) * I) ** 2


def omega_from_length_scale(k, Lt, Cmu=CMU):
    """omega = sqrt(k) / (Cmu^(1/4) * Lt)  [1/s]."""
    return math.sqrt(k) / (Cmu ** 0.25 * Lt)


def length_scale_from_k_omega(k, omega, Cmu=CMU):
    """Lt = sqrt(k) / (Cmu^(1/4) * omega)  [m]."""
    return math.sqrt(k) / (Cmu ** 0.25 * omega)


def turbulence_intensity_from_k(U, k):
    """I = sqrt(k / 1.5) / abs(U)  (fraction)."""
    return math.sqrt(k / 1.5) / abs(U)


def cd_from_force(Fx, U, Aref, rho=RHO_KGPM3):
    """Cd = Fx / (0.5 * rho * U^2 * Aref). Aref = D * b_mesh for fixed cylinder."""
    return Fx / (0.5 * rho * U * U * Aref)


def cl_from_force(Fy, U, Aref, rho=RHO_KGPM3):
    """Cl = Fy / (0.5 * rho * U^2 * Aref)."""
    return Fy / (0.5 * rho * U * U * Aref)


def strouhal(f, D, U):
    """St = f * D / abs(U)."""
    return f * D / abs(U)


def fluctuation_rms(samples):
    """Fluctuation RMS = RMS of (x - mean(x)). Distinct from total RMS."""
    if not samples:
        return float("nan")
    m = sum(samples) / len(samples)
    return math.sqrt(sum((x - m) ** 2 for x in samples) / len(samples))


def total_rms(samples):
    """Total RMS = sqrt(mean(x^2)). Distinct from fluctuation RMS."""
    if not samples:
        return float("nan")
    return math.sqrt(sum(x * x for x in samples) / len(samples))


def relative_change(a, b, epsilon=1e-12):
    """relative_change(a,b) = abs(a-b)/max(abs(b), epsilon). b is reference."""
    return abs(a - b) / max(abs(b), epsilon)
