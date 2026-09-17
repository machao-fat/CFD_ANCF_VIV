"""Generic installed-stretch static-prestress initializer.

Python owns the case contract, deterministic calibration, identities, and
artifacts.  Each candidate is solved by the standalone C++ bridge, which calls
the unchanged production ANCF static API.
"""

from __future__ import annotations

from copy import deepcopy
import csv
import json
import math
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Callable, Mapping, Sequence

from .ancf_case_config_v1 import (
    CaseConfig,
    CaseConfigError,
    DOF_ORDER,
    canonical_sha256,
)
from .ancf_kinematics_v1 import gradient_at_s, position_at_s


class PrestressError(ValueError):
    """Prestress configuration, solve, or artifact contract failure."""


RESULT_SCHEMA_VERSION = "ANCF_STATIC_PRESTRESS_RESULT_V1.2"


def _reject_json_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON constant {token}")


def _validate_finite_tree(value: Any, path: str = "result") -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PrestressError(f"HELPER_RESULT_FILE_INVALID: nonfinite {path}")
    elif isinstance(value, Mapping):
        for key, child in value.items():
            _validate_finite_tree(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_finite_tree(child, f"{path}[{index}]")


def read_result_file(path: str | Path, expected_evaluation_id: str, *,
                     allow_transport_test: bool = False) -> Mapping[str, Any]:
    """Read and validate the V1.2 machine-result file, never stdout."""
    result_path = Path(path)
    if not result_path.is_file() or result_path.stat().st_size == 0:
        raise PrestressError("HELPER_RESULT_FILE_MISSING")
    try:
        text = result_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PrestressError("HELPER_RESULT_FILE_INVALID: unreadable UTF-8") from exc
    try:
        result = json.loads(text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise PrestressError("HELPER_RESULT_FILE_INVALID: malformed JSON") from exc
    if not isinstance(result, Mapping):
        raise PrestressError("HELPER_RESULT_FILE_INVALID: top level is not an object")
    if result.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise PrestressError("STALE_OR_MISMATCHED_RESULT: schema_version")
    if result.get("evaluation_id") != expected_evaluation_id:
        raise PrestressError("STALE_OR_MISMATCHED_RESULT: evaluation_id")
    if result.get("status") not in ("PASS", "FAIL"):
        raise PrestressError("HELPER_RESULT_FILE_INVALID: status")
    _validate_finite_tree(result)
    if result["status"] == "PASS":
        required = (
            "static_status", "DeltaL_m", "H_m", "top_tension_N",
            "top_reaction_vector_N", "bottom_reaction_vector_N",
            "global_balance_error", "q", "potential_diagnostics",
        )
        missing = [name for name in required if name not in result]
        if missing:
            raise PrestressError(
                "HELPER_RESULT_FILE_INVALID: missing " + ",".join(missing))
        if result.get("static_status") != "CONVERGED" and not (
                allow_transport_test and result.get("static_status") == "TRANSPORT_TEST"):
            raise PrestressError("HELPER_RESULT_FILE_INVALID: PASS static_status")
    else:
        if not result.get("failure_classification"):
            raise PrestressError("HELPER_RESULT_FILE_INVALID: failure_classification")
    return result


def _finite(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PrestressError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise PrestressError(f"{name} must be finite")
    return result


def _positive(value: Any, name: str) -> float:
    result = _finite(value, name)
    if result <= 0.0:
        raise PrestressError(f"{name} must be positive")
    return result


def _norm3(value: Sequence[float]) -> float:
    return math.sqrt(sum(float(item) * float(item) for item in value))


def _section_properties(config: CaseConfig) -> dict[str, float]:
    section = config.raw["section"]
    if section["mode"] == "legacy_physical":
        legacy = section["legacy"]
        diameter = _positive(legacy["D_m"], "section.legacy.D_m")
        inner = _finite(legacy["Di_m"], "section.legacy.Di_m")
        modulus = _positive(legacy["E_Pa"], "section.legacy.E_Pa")
        density = _positive(legacy["rho_material_kg_m3"], "section.legacy.rho_material_kg_m3")
        diameter_squared = diameter * diameter
        inner_squared = inner * inner
        area = math.pi * (diameter_squared - inner_squared) / 4.0
        inertia = math.pi * (diameter_squared * diameter_squared -
                              inner_squared * inner_squared) / 64.0
        return {
            "A_m2": area,
            "I_m4": inertia,
            "EA_N": modulus * area,
            "EI_Nm2": modulus * inertia,
            "mass_per_length_kg_m": density * area,
            "displaced_area_m2": math.pi * diameter_squared / 4.0,
        }
    explicit = config.raw["section"]["explicit"]
    return {
        "A_m2": float("nan"),
        "I_m4": float("nan"),
        "EA_N": _positive(explicit["EA_N"], "section.explicit.EA_N"),
        "EI_Nm2": _positive(explicit["EI_Nm2"], "section.explicit.EI_Nm2"),
        "mass_per_length_kg_m": _positive(
            explicit["mass_per_length_kg_m"], "section.explicit.mass_per_length_kg_m"),
        "displaced_area_m2": _positive(
            explicit["displaced_area_m2"], "section.explicit.displaced_area_m2"),
    }


def _omega_s(config: CaseConfig, properties: Mapping[str, float]) -> float:
    environment = config.raw["environment"]
    gravity = _positive(environment["gravity_m_s2"], "environment.gravity_m_s2")
    fluid_density = _positive(environment["rho_fluid_kg_m3"], "environment.rho_fluid_kg_m3")
    return (properties["mass_per_length_kg_m"] * gravity -
            fluid_density * properties["displaced_area_m2"] * gravity)


def _json_vector(value: Any, name: str) -> tuple[float, ...]:
    try:
        result = tuple(_finite(item, f"{name}[{index}]") for index, item in enumerate(value))
    except TypeError as exc:
        raise PrestressError(f"{name} must be a sequence") from exc
    return result


def _relative_difference(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        return math.inf
    return max((abs(float(a) - float(b)) / max(1.0, abs(float(a)), abs(float(b)))
                for a, b in zip(left, right)), default=0.0)


class StaticPrestressInitializer:
    """Run deterministic installed-stretch/top-reaction calibration."""

    def __init__(self, config: CaseConfig, driver: str | Path,
                 *, runner: Callable[[str], Mapping[str, Any]] | None = None,
                 result_directory: str | Path | None = None) -> None:
        spec = config.prestress_spec()
        if spec["mode"] != "installed_stretch_target_top_reaction":
            raise PrestressError("PRESTRESS_CONFIG_FAIL: unsupported prestress mode")
        self.config = config
        self.spec = spec
        self.driver = Path(driver).resolve()
        self.runner = runner
        self.result_directory = Path(result_directory).resolve() if result_directory else Path(
            tempfile.mkdtemp(prefix="ancf_static_prestress_v1_"))
        self.result_directory.mkdir(parents=True, exist_ok=True)
        self.last_evaluation_paths: dict[str, Path] = {}
        self.properties = _section_properties(config)
        self.omega_s = _omega_s(config, self.properties)
        self.history: list[dict[str, Any]] = []
        self.evaluation_id = 0
        self.static_solves = 0
        self.total_newton_iterations = 0
        self.potential_non_descent_failures = 0
        self.potential_line_search_failures = 0
        self.minimum_accepted_beta = 1.0
        self.maximum_backtrack_depth = 0
        self.unchanged_trials_seen = 0
        self.unchanged_trials_accepted = 0
        if not math.isfinite(self.omega_s):
            raise PrestressError("INVALID_PRECHECK_PARAMETERS")

    def _request_text(self, delta_length_m: float) -> str:
        model = self.config.kernel_model()
        mode = 1 if model.section_property_mode == "explicit" else 0
        load_mode = 1 if self.config.raw["base_load"]["source"] == "model_static" else 0
        spec = self.spec
        bottom = tuple(spec["bottom_position_m"])
        axis = tuple(spec["installation_axis"])
        values: list[Any] = [
            mode, load_mode, self.config.elements, self.config.length_m,
            model.youngs_modulus_Pa, model.diameter_m, model.inner_diameter_m,
            model.material_density, model.explicit_EA_N or 0.0,
            model.explicit_EI_Nm2 or 0.0, model.explicit_mass_per_length_kg_m or 0.0,
            model.explicit_displaced_area_m2 or 0.0, model.fluid_density, model.gravity,
            0.00125, model.beta, model.gamma, model.newton_tolerance,
            model.max_newton, model.gauss_order, model.mass_gauss_order,
            spec["static_load_steps"], delta_length_m, *bottom, *axis,
        ]
        base = self.config.base_load_vector() if load_mode == 0 else ()
        values.append(len(base))
        values.extend(base)
        return " ".join(format(value, ".17g") if isinstance(value, float) else str(value)
                        for value in values) + "\n"

    def _run_driver(self, delta_length_m: float) -> Mapping[str, Any]:
        request = self._request_text(delta_length_m)
        if self.runner is not None:
            return self.runner(request)
        if not self.driver.is_file():
            raise PrestressError(f"STATIC_SOLVE_FAIL: helper not found: {self.driver}")
        evaluation_id = f"eval-{self.evaluation_id:06d}"
        result_path = self.result_directory / f"{evaluation_id}.result.json"
        request_path = self.result_directory / f"{evaluation_id}.request.json"
        stdout_path = self.result_directory / f"{evaluation_id}.stdout.txt"
        stderr_path = self.result_directory / f"{evaluation_id}.stderr.txt"
        command_path = self.result_directory / f"{evaluation_id}.command.json"
        returncode_path = self.result_directory / f"{evaluation_id}.returncode.txt"
        try:
            result_path.unlink(missing_ok=True)
        except OSError as exc:
            raise PrestressError(f"HELPER_RESULT_FILE_INVALID: cannot prepare result path: {exc}") from exc
        request_path.write_text(json.dumps({
            "schema_version": RESULT_SCHEMA_VERSION,
            "evaluation_id": evaluation_id,
            "transport": "whitespace_stdin",
            "request_text": request,
            "result_path": str(result_path),
        }, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        command = [str(self.driver), "--result-json", str(result_path),
                   "--evaluation-id", evaluation_id]
        command_path.write_text(json.dumps(command, ensure_ascii=False) + "\n", encoding="utf-8")
        completed = subprocess.run(
            command, input=request, text=True,
            capture_output=True, check=False,
        )
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        returncode_path.write_text(str(completed.returncode) + "\n", encoding="utf-8")
        self.last_evaluation_paths = {
            "request": request_path, "result": result_path,
            "stdout": stdout_path, "stderr": stderr_path,
            "command": command_path, "returncode": returncode_path,
        }
        try:
            result = read_result_file(result_path, evaluation_id)
        except PrestressError:
            raise
        if completed.returncode == 0:
            if result.get("status") != "PASS":
                raise PrestressError("HELPER_RETURN_CODE_MISMATCH")
            return result
        if result.get("status") == "FAIL":
            raise PrestressError(
                f"{result.get('failure_classification')}: "
                f"{result.get('failure_reason', '')}".rstrip())
        raise PrestressError(f"HELPER_EXIT_FAILURE: {completed.returncode}")

    def _evaluate(self, delta_length_m: float, bisection_iteration: int) -> Mapping[str, Any]:
        if delta_length_m <= -self.config.length_m:
            raise PrestressError("TARGET_REACTION_BRACKET_FAIL: nonpositive installed length")
        self.evaluation_id += 1
        raw = dict(self._run_driver(delta_length_m))
        if raw.get("status") != "PASS":
            raise PrestressError(str(raw.get("failure_classification", "STATIC_SOLVE_FAIL")))
        target = self.spec["target_reaction_N"]
        top = _finite(raw.get("top_tension_N"), "top_tension_N")
        f_value = top - target
        row = {
            "evaluation_id": self.evaluation_id,
            "bisection_iteration": bisection_iteration,
            "DeltaL_m": delta_length_m,
            "H_m": self.config.length_m + delta_length_m,
            "lambda0": (self.config.length_m + delta_length_m) / self.config.length_m,
            "epsilon0": 0.5 * (((self.config.length_m + delta_length_m) /
                               self.config.length_m) ** 2 - 1.0),
            "static_status": raw.get("status"),
            "static_Newton_iterations": raw.get("iterations"),
            "T_top_N": top,
            "f_N": f_value,
            "relative_target_error": abs(f_value) / target,
            "top_Rx_N": raw.get("top_reaction_vector_N", raw["top_reaction"])[0],
            "top_Ry_N": raw.get("top_reaction_vector_N", raw["top_reaction"])[1],
            "top_Rz_N": raw.get("top_reaction_vector_N", raw["top_reaction"])[2],
            "bottom_Rx_N": raw.get("bottom_reaction_vector_N", raw["bottom_reaction"])[0],
            "bottom_Ry_N": raw.get("bottom_reaction_vector_N", raw["bottom_reaction"])[1],
            "bottom_Rz_N": raw.get("bottom_reaction_vector_N", raw["bottom_reaction"])[2],
        }
        self.history.append(row)
        self.static_solves += 1
        self.total_newton_iterations += int(raw["iterations"])
        self.potential_non_descent_failures += int(raw.get("non_descent_failures", 0))
        self.potential_line_search_failures += int(raw.get("line_search_failures", 0))
        self.minimum_accepted_beta = min(
            self.minimum_accepted_beta, float(raw.get("minimum_accepted_beta", 1.0)))
        self.maximum_backtrack_depth = max(
            self.maximum_backtrack_depth, int(raw.get("maximum_backtrack_depth", 0)))
        self.unchanged_trials_seen += int(raw.get("unchanged_trials_seen", 0))
        self.unchanged_trials_accepted += int(raw.get("unchanged_trials_accepted", 0))
        return raw

    def calibrate(self) -> dict[str, Any]:
        low_delta = float(self.spec["delta_length_low_m"])
        high_delta = float(self.spec["delta_length_high_m"])
        low = self._evaluate(low_delta, 0)
        high = self._evaluate(high_delta, 0)
        low_f = float(low["top_tension_N"]) - self.spec["target_reaction_N"]
        high_f = float(high["top_tension_N"]) - self.spec["target_reaction_N"]
        if low_f * high_f >= 0.0:
            raise PrestressError("TARGET_REACTION_BRACKET_FAIL")
        final = None
        final_delta = None
        for iteration in range(1, int(self.spec["max_iterations"]) + 1):
            delta = 0.5 * (low_delta + high_delta)
            candidate = self._evaluate(delta, iteration)
            final = candidate
            final_delta = delta
            error = abs(float(candidate["top_tension_N"]) -
                        self.spec["target_reaction_N"]) / self.spec["target_reaction_N"]
            if error <= self.spec["relative_target_tolerance"]:
                break
            candidate_f = float(candidate["top_tension_N"]) - self.spec["target_reaction_N"]
            if low_f * candidate_f < 0.0:
                high_delta, high_f = delta, candidate_f
            else:
                low_delta, low_f = delta, candidate_f
        else:
            raise PrestressError("TARGET_REACTION_CALIBRATION_FAIL")
        assert final is not None and final_delta is not None
        return {
            "final_delta_length_m": final_delta,
            "final": final,
            "bracket_low": low,
            "bracket_high": high,
            "bracket_valid": True,
            "static_solves": self.static_solves,
            "total_newton_iterations": self.total_newton_iterations,
            "potential_non_descent_failures": self.potential_non_descent_failures,
            "potential_line_search_failures": self.potential_line_search_failures,
            "minimum_accepted_beta": self.minimum_accepted_beta,
            "maximum_backtrack_depth": self.maximum_backtrack_depth,
            "unchanged_trials_seen": self.unchanged_trials_seen,
            "unchanged_trials_accepted": self.unchanged_trials_accepted,
            "history": list(self.history),
        }

    def tension_profile(self, result: Mapping[str, Any]) -> list[dict[str, float]]:
        length = self.config.length_m
        elements = self.config.elements
        element_length = length / elements
        target = self.spec["target_reaction_N"]
        top_tension = float(result["top_tension_N"])
        rows: list[dict[str, float]] = []
        for element in range(elements):
            for xi in (-1.0 / math.sqrt(3.0), 1.0 / math.sqrt(3.0)):
                s = (element + 0.5 * (xi + 1.0)) * element_length
                gradient = gradient_at_s(result["q"], s, length, elements)
                position = position_at_s(result["q"], s, length, elements)
                lam = _norm3(gradient)
                epsilon = 0.5 * (lam * lam - 1.0)
                t_ancf = self.properties["EA_N"] * epsilon * lam
                t_ref = top_tension - self.omega_s * (length - s)
                rows.append({
                    "s_ref_m": s,
                    "current_z_m": position[2],
                    "lambda": lam,
                    "epsilon": epsilon,
                    "T_ANCF_N": t_ancf,
                    "T_ref_N": t_ref,
                    "difference_N": t_ancf - t_ref,
                    "normalized_error": abs(t_ancf - t_ref) / target,
                })
        return rows

    def write_history(self, path: str | Path) -> None:
        fields = [
            "evaluation_id", "bisection_iteration", "DeltaL_m", "H_m", "lambda0",
            "epsilon0", "static_status", "static_Newton_iterations", "T_top_N",
            "f_N", "relative_target_error", "top_Rx_N", "top_Ry_N", "top_Rz_N",
            "bottom_Rx_N", "bottom_Ry_N", "bottom_Rz_N",
        ]
        with Path(path).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(self.history)

    def make_static_artifact(self, calibration: Mapping[str, Any],
                             protocol_sha256: str,
                             producer_commit: str) -> dict[str, Any]:
        final = calibration["final"]
        delta = float(calibration["final_delta_length_m"])
        height = self.config.length_m + delta
        fixed = (0, 1, 2, 6 * self.config.elements,
                 6 * self.config.elements + 1, 6 * self.config.elements + 2)
        bottom = tuple(self.spec["bottom_position_m"])
        axis = tuple(self.spec["installation_axis"])
        prescribed = bottom + tuple(bottom[i] + axis[i] * height for i in range(3))
        boundary_core = {
            "contract_id": self.config.raw["boundary"]["contract_id"],
            "fixed_dof": list(fixed),
            "prescribed_values": list(prescribed),
        }
        resolved_identity = self.config.model_identity_sha256_for_boundary(fixed, prescribed)
        source = self.config.raw["base_load"]["source"]
        base = self.config.base_load_vector() if source == "caller_supplied" else None
        q = _json_vector(final["q"], "q")
        zeros = [0.0] * self.config.ndof
        artifact = {
            "schema_version": 1,
            "state_kind": "prestressed_static",
            "q": list(q),
            "qdot": zeros,
            "qddot": zeros,
            "dof_order": DOF_ORDER,
            "dof_count": self.config.ndof,
            "length_m": self.config.length_m,
            "reference_material_length_m": self.config.length_m,
            "elements": self.config.elements,
            "section": self.config._state_section_identity(),
            "environment": self.config._state_environment_identity(),
            "base_load": {
                "source": source,
                "vector": list(base) if base is not None else None,
                "identity_sha256": canonical_sha256({"source": source, "vector": base}),
            },
            "boundary": {
                **boundary_core,
                "identity_sha256": canonical_sha256(boundary_core),
            },
            "state_time_s": 0.0,
            "global_step": 0,
            "case_config_sha256": self.config.config_sha256,
            "source_case_config_sha256": self.config.config_sha256,
            "source_model_identity_sha256": self.config.model_identity_sha256,
            "model_identity_sha256": resolved_identity,
            "resolved_static_model_identity_sha256": resolved_identity,
            "producer": {
                "commit": producer_commit,
                "component": "ancf_static_prestress_v1",
            },
            "static_protocol_sha256": protocol_sha256,
            "prestress": {
                "mode": self.spec["mode"],
                "DeltaL_m": delta,
                "H_m": height,
                "target_reaction_N": self.spec["target_reaction_N"],
                "actual_top_reaction_N": final["top_tension_N"],
                "installation_axis": list(axis),
            },
            "provenance": {
                "top_reaction": final["top_reaction"],
                "bottom_reaction": final["bottom_reaction"],
                "global_balance_error": final["global_balance_error"],
                "max_abs_lambda_minus_1": final["max_abs_lambda_minus_1"],
                "static_Newton_iterations": final["iterations"],
            },
        }
        return artifact


def make_synthetic_case(*, section_mode: str = "legacy_physical",
                        base_load_source: str = "model_static",
                        base_load: Sequence[float] | None = None,
                        state_file: str = "ANCF_GENERIC_STATIC_PRESTRESS_INITIALIZER_V1_STATIC_STATE.json") -> dict[str, Any]:
    """Return the frozen 10 m synthetic case as a generic external config."""

    legacy = {
        "E_Pa": 2.0e9, "D_m": 0.05, "Di_m": 0.04,
        "rho_material_kg_m3": 4000.0,
    }
    diameter = legacy["D_m"]
    inner = legacy["Di_m"]
    area = math.pi * (diameter * diameter - inner * inner) / 4.0
    inertia = math.pi * (diameter**4 - inner**4) / 64.0
    explicit = {
        "EA_N": legacy["E_Pa"] * area,
        "EI_Nm2": legacy["E_Pa"] * inertia,
        "mass_per_length_kg_m": legacy["rho_material_kg_m3"] * area,
        "displaced_area_m2": math.pi * diameter * diameter / 4.0,
    }
    ndof = 6 * (16 + 1)
    return {
        "schema_version": 1,
        "case_identity": {"case_id": "generic_synthetic_top_tension_v1",
                          "run_id": "generic_synthetic_top_tension_v1"},
        "model": {"length_m": 10.0, "elements": 16},
        "section": {"mode": section_mode, "legacy": legacy, "explicit": explicit},
        "environment": {"rho_fluid_kg_m3": 1000.0, "gravity_m_s2": 9.81},
        "base_load": {
            "source": base_load_source,
            **({"vector": list(base_load)} if base_load_source == "caller_supplied" else {}),
        },
        "boundary": {
            "contract_id": "prestress_position_both_ends_v1",
            "preset": "pinned_position_both_ends",
            "bottom_position_m": [0.0, 0.0, 0.0],
            "top_position_m": [0.0, 0.0, 10.0],
        },
        "initial_state": {
            "kind": "prestressed_start",
            "state_file": state_file,
            "reference_geometry": "case_geometry",
            "reference_positions_m": [[0.0, 0.0, 5.0]],
        },
        "coupling": {
            "slices": [{
                "slice_id": 0, "s_ref_m": 5.0,
                "slice_length_m": 10.0, "unit_span_m": 1.0,
            }],
            "force_representation": "integrated_slice_force_N",
            "motion_components": ["x", "y"],
        },
        "numerics": {
            "dt_s": 0.00125, "beta": 0.25, "gamma": 0.5,
            "newton_tolerance": 1.0e-8, "max_newton": 40,
            "gauss_order": 3, "mass_gauss_order": 5,
            "damping_alpha": 0.0, "damping_beta": 0.0,
        },
        "prestress": {
            "mode": "installed_stretch_target_top_reaction",
            "target_reaction_N": 5000.0,
            "installation_axis": [0.0, 0.0, 1.0],
            "delta_length_low_m": 0.0087670037828830698,
            "delta_length_high_m": 0.070136030263064558,
            "relative_target_tolerance": 1.0e-6,
            "max_iterations": 40,
            "static_load_steps": 40,
        },
    }


def compare_calibrations(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, float]:
    left_final = left["final"]
    right_final = right["final"]
    return {
        "DeltaL_abs_m": abs(float(left["final_delta_length_m"]) -
                            float(right["final_delta_length_m"])),
        "T_top_abs_N": abs(float(left_final["top_tension_N"]) -
                           float(right_final["top_tension_N"])),
        "q_relative_max": _relative_difference(left_final["q"], right_final["q"]),
        "global_balance_abs": abs(float(left_final["global_balance_error"]) -
                                  float(right_final["global_balance_error"])),
    }
