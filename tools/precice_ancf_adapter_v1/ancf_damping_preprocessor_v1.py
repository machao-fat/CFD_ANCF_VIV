"""Pure, paper-independent Rayleigh damping parameter preprocessing.

This module resolves an explicit damping description to the already validated
production ``rayleigh_coefficients`` case-config block.  It never constructs
the production damping matrix and never runs ANCF dynamics or modal analysis.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

try:
    from .ancf_case_config_v1 import canonical_sha256
except ImportError:  # pragma: no cover - direct script import support
    from ancf_case_config_v1 import canonical_sha256  # type: ignore


SCHEMA_VERSION = 1
REFERENCE_STATE = "dynamic_initial"
PREPROCESSOR_PROTOCOL_SHA256 = (
    "2493448EFD4FAFEF7E869DC417191144F2466187BB9C1B0E19D76F4FD88F0125"
)
PSD_POLICY_REQUIRED = True
MODES = (
    "explicit_coefficients",
    "modal_pair",
    "mass_proportional_single_target",
    "stiffness_proportional_single_target",
)
SEPARATION_RELATIVE_TOLERANCE = 1.0e-12


class RayleighPreprocessorError(ValueError):
    """Deterministic input or admissibility error."""


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise RayleighPreprocessorError(f"{name} must be finite numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RayleighPreprocessorError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise RayleighPreprocessorError(f"{name} must be finite")
    return result


def _nonnegative(value: Any, name: str) -> float:
    result = _finite(value, name)
    if result < 0.0:
        raise RayleighPreprocessorError(f"{name} must be nonnegative")
    return result


def _positive(value: Any, name: str) -> float:
    result = _finite(value, name)
    if result <= 0.0:
        raise RayleighPreprocessorError(f"{name} must be positive")
    return result


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RayleighPreprocessorError(f"{name} must be an object")
    return value


def _strict_keys(value: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RayleighPreprocessorError(
            f"{name} contains unsupported fields: {', '.join(unknown)}"
        )


def _target(value: Any, index: int) -> tuple[dict[str, float], float, float]:
    target = _mapping(value, f"targets[{index}]")
    _strict_keys(target, {"frequency_hz", "zeta"}, f"targets[{index}]")
    if "frequency_hz" not in target:
        raise RayleighPreprocessorError("DAMPING_TARGET_FREQUENCY_REQUIRED")
    if "zeta" not in target:
        raise RayleighPreprocessorError("DAMPING_TARGET_ZETA_REQUIRED")
    frequency = _positive(target["frequency_hz"], f"targets[{index}].frequency_hz")
    zeta = _nonnegative(target["zeta"], f"targets[{index}].zeta")
    return {"frequency_hz": frequency, "zeta": zeta}, frequency, zeta


def _modal_output(
    mode: str,
    source_targets: list[dict[str, float]],
    canonical_targets: list[dict[str, float]],
    alpha: float,
    beta: float,
    assumption: str,
    formula_contract_id: str,
    canonical_input: Any,
) -> dict[str, Any]:
    if not math.isfinite(alpha) or not math.isfinite(beta):
        raise RayleighPreprocessorError("RAYLEIGH_RESOLVED_COEFFICIENT_NONFINITE")
    if alpha < 0.0 or beta < 0.0:
        raise RayleighPreprocessorError("RAYLEIGH_MODAL_PAIR_NEGATIVE_COEFFICIENT")

    reconstruction = []
    for target in canonical_targets:
        omega = target["omega_rad_s"]
        zeta_hat = alpha / (2.0 * omega) + beta * omega / 2.0
        reconstruction.append(
            {
                "frequency_hz": target["frequency_hz"],
                "zeta": target["zeta"],
                "omega_rad_s": omega,
                "zeta_hat": zeta_hat,
                "absolute_error": abs(zeta_hat - target["zeta"]),
            }
        )

    identity_payload = {
        "schema_version": SCHEMA_VERSION,
        "input_mode": mode,
        "canonical_input": canonical_input,
        "assumption": assumption,
        "formula_contract_id": formula_contract_id,
        "reference_state": REFERENCE_STATE,
        "resolved": {
            "alpha_mass_per_s": alpha,
            "beta_stiffness_s": beta,
        },
    }
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "input_mode": mode,
        "alpha_mass_per_s": alpha,
        "beta_stiffness_s": beta,
        "reference_state": REFERENCE_STATE,
        "source_targets": source_targets,
        "canonical_targets": canonical_targets,
        "target_reconstruction": reconstruction,
        "assumption": assumption,
        "formula_contract_id": formula_contract_id,
        "preprocessor_protocol_sha256": PREPROCESSOR_PROTOCOL_SHA256,
        "damping_preprocess_identity_sha256": canonical_sha256(identity_payload),
        "canonical_damping": {
            "mode": "rayleigh_coefficients",
            "alpha_mass_per_s": alpha,
            "beta_stiffness_s": beta,
            "reference_state": REFERENCE_STATE,
            "require_free_tangent_positive_semidefinite": PSD_POLICY_REQUIRED,
        },
    }
    return result


def _resolve_modal_pair(spec: Mapping[str, Any]) -> dict[str, Any]:
    _strict_keys(spec, {"mode", "targets"}, "modal_pair")
    targets_value = spec.get("targets")
    if isinstance(targets_value, (str, bytes)) or not isinstance(targets_value, Sequence):
        raise RayleighPreprocessorError("RAYLEIGH_MODAL_PAIR_REQUIRES_TWO_TARGETS")
    if len(targets_value) != 2:
        raise RayleighPreprocessorError("RAYLEIGH_MODAL_PAIR_REQUIRES_TWO_TARGETS")
    first, f1, z1 = _target(targets_value[0], 0)
    second, f2, z2 = _target(targets_value[1], 1)
    separation = abs(f2 - f1)
    limit = SEPARATION_RELATIVE_TOLERANCE * max(1.0, abs(f1), abs(f2))
    if separation <= limit:
        raise RayleighPreprocessorError("RAYLEIGH_MODAL_PAIR_FREQUENCIES_TOO_CLOSE")

    original = [first, second]
    ordered = sorted(original, key=lambda item: (item["frequency_hz"], item["zeta"]))
    canonical_targets = []
    for target in ordered:
        frequency = target["frequency_hz"]
        canonical_targets.append(
            {
                "frequency_hz": frequency,
                "zeta": target["zeta"],
                "omega_rad_s": 2.0 * math.pi * frequency,
            }
        )
    omega1 = canonical_targets[0]["omega_rad_s"]
    omega2 = canonical_targets[1]["omega_rad_s"]
    zeta1 = canonical_targets[0]["zeta"]
    zeta2 = canonical_targets[1]["zeta"]
    denominator = omega2 * omega2 - omega1 * omega1
    beta = 2.0 * (zeta2 * omega2 - zeta1 * omega1) / denominator
    alpha = (
        2.0 * omega1 * omega2 * (zeta1 * omega2 - zeta2 * omega1) / denominator
    )
    return _modal_output(
        "modal_pair",
        original,
        canonical_targets,
        alpha,
        beta,
        "two_modal_targets",
        "rayleigh_modal_pair_v1",
        {"targets": canonical_targets},
    )


def _resolve_single(spec: Mapping[str, Any], mode: str) -> dict[str, Any]:
    _strict_keys(spec, {"mode", "frequency_hz", "zeta"}, mode)
    if "frequency_hz" not in spec:
        raise RayleighPreprocessorError("DAMPING_TARGET_FREQUENCY_REQUIRED")
    if "zeta" not in spec:
        raise RayleighPreprocessorError("DAMPING_TARGET_ZETA_REQUIRED")
    frequency = _positive(spec["frequency_hz"], "frequency_hz")
    zeta = _nonnegative(spec["zeta"], "zeta")
    omega = 2.0 * math.pi * frequency
    if mode == "mass_proportional_single_target":
        alpha, beta = 2.0 * zeta * omega, 0.0
        assumption = "mass_proportional_only"
        formula = "rayleigh_mass_proportional_single_target_v1"
    else:
        alpha, beta = 0.0, 2.0 * zeta / omega
        assumption = "stiffness_proportional_only"
        formula = "rayleigh_stiffness_proportional_single_target_v1"
    target = {"frequency_hz": frequency, "zeta": zeta}
    canonical_target = {**target, "omega_rad_s": omega}
    return _modal_output(
        mode,
        [target],
        [canonical_target],
        alpha,
        beta,
        assumption,
        formula,
        {"frequency_hz": frequency, "zeta": zeta},
    )


def preprocess_damping(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve one canonical preprocessing description."""
    value = _mapping(spec, "damping preprocessing spec")
    if "mode" not in value:
        raise RayleighPreprocessorError("DAMPING_PREPROCESSOR_MODE_REQUIRED")
    mode = value["mode"]
    if mode not in MODES:
        raise RayleighPreprocessorError("DAMPING_PREPROCESSOR_UNKNOWN_MODE")
    if mode == "explicit_coefficients":
        _strict_keys(value, {"mode", "alpha_mass_per_s", "beta_stiffness_s"}, mode)
        if "alpha_mass_per_s" not in value or "beta_stiffness_s" not in value:
            raise RayleighPreprocessorError("EXPLICIT_RAYLEIGH_COEFFICIENTS_REQUIRED")
        alpha = _nonnegative(value["alpha_mass_per_s"], "alpha_mass_per_s")
        beta = _nonnegative(value["beta_stiffness_s"], "beta_stiffness_s")
        return _modal_output(
            mode,
            {"alpha_mass_per_s": alpha, "beta_stiffness_s": beta},  # type: ignore[arg-type]
            [],
            alpha,
            beta,
            "explicit_coefficients",
            "rayleigh_explicit_coefficients_v1",
            {"alpha_mass_per_s": alpha, "beta_stiffness_s": beta},
        )
    if mode == "modal_pair":
        return _resolve_modal_pair(value)
    return _resolve_single(value, mode)


def canonical_damping_block(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the production case-config damping block."""
    return dict(preprocess_damping(spec)["canonical_damping"])
