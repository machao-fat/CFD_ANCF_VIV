#!/usr/bin/env python3
"""Standalone legacy ANCF section/property compatibility checker.

This tool is deliberately independent of the ANCF production kernel. It
implements only the frozen physical-section algebra used by the legacy Model:

    A  = pi/4  * (D**2 - Di**2)
    I  = pi/64 * (D**4 - Di**4)
    EA = E*A
    EI = E*I
    m  = rho_m*A
    Ad = pi/4  * D_hydro**2

It accepts literature fields as explicit known/unknown/not_reported records,
performs algebraic inference where the supplied data determine a solution,
and never calls or modifies production code.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


TOOL_VERSION = "ANCF_LITERATURE_SECTION_COMPATIBILITY_TOOL_V1"
RELATIVE_TOLERANCE = 1.0e-10
PI = math.pi

PRODUCTION_COMMIT = "32c740ef8a620323fe4660389c7ef77c405eafe1"
PRODUCTION_CPP_SHA256 = (
    "5A05AC427DFE15AD281446342D7C9A0822CD3068E2BE1B541BCCB530C6FF113B"
)
PRODUCTION_HPP_SHA256 = (
    "6E5697C002DAC1D374EC0EB07EDEC22FD5E01D606F5C1030819B0C180FA00682"
)
CAPABILITY_PRECHECK_PROTOCOL_SHA256 = (
    "86CA64CFA11A304C94D57C57071205335D9C4575E44290F28586C48AB707A231"
)

FIELD_NAMES = (
    "D_hydro_m",
    "D_struct_m",
    "Di_m",
    "E_Pa",
    "rho_material_kg_m3",
    "EA_N",
    "EI_Nm2",
    "mass_per_length_kg_m",
    "displaced_area_m2",
    "submerged_mass_per_length_kg_m",
    "submerged_weight_per_length_N_m",
    "rho_fluid_kg_m3",
)

CLASSIFICATIONS = (
    "LEGACY_EXACTLY_REPRESENTABLE",
    "LEGACY_REPRESENTABLE_WITH_UNREPORTED_PARAMETER_INFERRED",
    "LEGACY_STRUCTURALLY_REPRESENTABLE_BUT_BUOYANCY_MISMATCH",
    "LEGACY_STRUCTURALLY_REPRESENTABLE_BUT_MASS_MISMATCH",
    "LEGACY_HYDRO_DIAMETER_CONFLICT",
    "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
    "INSUFFICIENT_INFORMATION",
    "EXPLICIT_SECTION_PROPERTIES_REQUIRED",
)


def is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def relative_error(actual: float | None, reference: float | None) -> float | None:
    if actual is None or reference is None:
        return None
    if not is_finite_number(actual) or not is_finite_number(reference):
        return None
    scale = max(abs(float(reference)), 1.0e-300)
    return abs(float(actual) - float(reference)) / scale


def close_enough(actual: float | None, reference: float | None) -> bool:
    error = relative_error(actual, reference)
    return error is not None and error <= RELATIVE_TOLERANCE


def field_record(status: str, value: Any = None) -> dict[str, Any]:
    status = str(status).lower()
    if status not in {"known", "unknown", "not_reported"}:
        raise ValueError(f"invalid field status: {status}")
    record: dict[str, Any] = {"status": status}
    if status == "known":
        if not is_finite_number(value):
            raise ValueError("known literature field must contain a finite number")
        record["value"] = float(value)
    return record


def normalize_fields(
    case: dict[str, Any],
) -> tuple[str, dict[str, dict[str, Any]], bool]:
    case_id = str(case.get("case_id", "unnamed_case"))
    source = case.get("fields", case)
    if not isinstance(source, dict):
        raise ValueError("input fields must be an object")
    normalized: dict[str, dict[str, Any]] = {}
    for name in FIELD_NAMES:
        if name not in source:
            normalized[name] = field_record("not_reported")
            continue
        raw = source[name]
        if raw is None:
            normalized[name] = field_record("not_reported")
        elif isinstance(raw, dict):
            status = raw.get("status", "known" if "value" in raw else "not_reported")
            normalized[name] = field_record(status, raw.get("value"))
        else:
            normalized[name] = field_record("known", raw)
    assumptions = case.get("assumptions", {})
    if not isinstance(assumptions, dict):
        assumptions = {}
    assumption = bool(
        case.get("assume_solid_equivalent_section", False)
        or assumptions.get("solid_equivalent_section", False)
    )
    return case_id, normalized, assumption


def known_values(fields: dict[str, dict[str, Any]]) -> dict[str, float]:
    return {
        name: float(record["value"])
        for name, record in fields.items()
        if record.get("status") == "known"
    }


def output_value(value: float | None) -> float | None:
    return None if value is None else float(value)


def make_base_result(
    case_id: str,
    fields: dict[str, dict[str, Any]],
    assumption_solid: bool,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "classification": None,
        "input_fields": fields,
        "reported_values": known_values(fields),
        "inferred_values": {},
        "assumptions": (
            ["solid_equivalent_section"] if assumption_solid else []
        ),
        "derived_properties": {},
        "forward_consistency_errors": {},
        "missing_information": [],
        "reason": "",
        "physical_material_density_plausibility": {
            "status": "diagnostic_only",
            "positive_finite": None,
            "note": (
                "A positive inferred density is mathematical compatibility "
                "evidence, not material identification."
            ),
        },
    }


def finish(
    result: dict[str, Any],
    classification: str,
    reason: str,
    missing: list[str] | None = None,
) -> dict[str, Any]:
    if classification not in CLASSIFICATIONS:
        raise ValueError(f"unknown classification {classification}")
    result["classification"] = classification
    result["reason"] = reason
    result["missing_information"] = list(missing or [])
    return result


def compatibility_check(case: dict[str, Any]) -> dict[str, Any]:
    case_id, fields, assumption_solid = normalize_fields(case)
    result = make_base_result(case_id, fields, assumption_solid)
    values = known_values(fields)

    dh_reported = values.get("D_hydro_m")
    ds_reported = values.get("D_struct_m")
    di = values.get("Di_m")
    E = values.get("E_Pa")
    rho = values.get("rho_material_kg_m3")
    ea_target = values.get("EA_N")
    ei_target = values.get("EI_Nm2")
    mass_target = values.get("mass_per_length_kg_m")
    adisp_target = values.get("displaced_area_m2")

    if dh_reported is not None and dh_reported <= 0.0:
        return finish(
            result,
            "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
            "D_hydro must be positive.",
        )
    if ds_reported is not None and ds_reported <= 0.0:
        return finish(
            result,
            "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
            "D_struct must be positive.",
        )
    if (
        dh_reported is not None
        and ds_reported is not None
        and not close_enough(dh_reported, ds_reported)
    ):
        result["derived_properties"]["D_hydro_m"] = dh_reported
        result["derived_properties"]["D_struct_m"] = ds_reported
        reason = (
            "The literature fixes different hydrodynamic and structural "
            "diameters, while the legacy model has one diameter in both roles."
        )
        missing = [
            "An explicit section/property API separating D_hydro from structural section geometry."
        ]
        return finish(result, "LEGACY_HYDRO_DIAMETER_CONFLICT", reason, missing)

    ds = ds_reported if ds_reported is not None else dh_reported
    if ds is None and assumption_solid and ea_target is not None and ei_target is not None:
        if ea_target <= 0.0 or ei_target <= 0.0:
            return finish(
                result,
                "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
                "EA and EI must be positive for a solid equivalent section.",
            )
        ds = 4.0 * math.sqrt(ei_target / ea_target)
        result["inferred_values"]["D_struct_m"] = ds
    if ds is None:
        missing = ["D_hydro_m or D_struct_m"]
        if not assumption_solid:
            missing.append("or an explicit solid-equivalent-section assumption")
        return finish(
            result,
            "INSUFFICIENT_INFORMATION",
            "A structural diameter is not reported and cannot be inferred without an explicit section assumption.",
            missing,
        )
    result["derived_properties"]["D_struct_m"] = ds

    if ds <= 0.0 or not math.isfinite(ds):
        return finish(
            result,
            "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
            "Structural diameter is not positive and finite.",
        )

    di2_inferred: float | None = None
    di4_inferred: float | None = None
    if di is None and assumption_solid:
        di = 0.0
        result["inferred_values"]["Di_m"] = di
    elif di is None and ea_target is not None and ei_target is not None:
        if ea_target <= 0.0 or ei_target <= 0.0:
            return finish(
                result,
                "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
                "EA and EI must be positive.",
            )
        di2_inferred = 16.0 * ei_target / ea_target - ds * ds
    elif di is None and E is not None and ei_target is not None:
        if E <= 0.0 or ei_target <= 0.0:
            return finish(
                result,
                "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
                "E and EI must be positive.",
            )
        di4_inferred = ds**4 - 64.0 * ei_target / (math.pi * E)
    elif di is None and E is not None and ea_target is not None:
        if E <= 0.0 or ea_target <= 0.0:
            return finish(
                result,
                "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
                "E and EA must be positive.",
            )
        di2_inferred = ds * ds - 4.0 * ea_target / (math.pi * E)

    if di is None and di2_inferred is not None:
        if not math.isfinite(di2_inferred):
            return finish(
                result,
                "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
                "Inferred Di^2 is non-finite.",
            )
        if di2_inferred < 0.0 or di2_inferred >= ds * ds:
            return finish(
                result,
                "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
                f"Physical annular-section check failed: inferred Di^2={di2_inferred:.17g} is outside [0,D^2).",
            )
        di = math.sqrt(max(0.0, di2_inferred))
        result["inferred_values"]["Di_m"] = di
    elif di is None and di4_inferred is not None:
        if not math.isfinite(di4_inferred):
            return finish(
                result,
                "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
                "Inferred Di^4 is non-finite.",
            )
        if di4_inferred < 0.0 or di4_inferred >= ds**4:
            return finish(
                result,
                "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
                f"Physical annular-section check failed: inferred Di^4={di4_inferred:.17g} is outside [0,D^4).",
            )
        di = math.sqrt(math.sqrt(max(0.0, di4_inferred)))
        result["inferred_values"]["Di_m"] = di

    if di is None:
        return finish(
            result,
            "INSUFFICIENT_INFORMATION",
            "Di cannot be determined from the reported fields and no solid-section assumption was supplied.",
            ["Di_m, or a sufficient pair among EA/EI/E/section geometry."],
        )
    if not math.isfinite(di) or di < 0.0 or di >= ds:
        return finish(
            result,
            "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
            f"Physical annular-section check failed: require 0 <= Di < D, got Di={di:.17g}, D={ds:.17g}.",
        )
    result["derived_properties"]["Di_m"] = di

    area = PI * (ds * ds - di * di) / 4.0
    inertia = PI * (ds**4 - di**4) / 64.0
    if area <= 0.0 or inertia < 0.0 or not math.isfinite(area + inertia):
        return finish(
            result,
            "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
            "The inferred annular section has invalid A or I.",
        )

    if E is None:
        if ea_target is not None:
            E = ea_target / area
            result["inferred_values"]["E_Pa"] = E
        elif ei_target is not None and inertia > 0.0:
            E = ei_target / inertia
            result["inferred_values"]["E_Pa"] = E
    if E is None:
        return finish(
            result,
            "INSUFFICIENT_INFORMATION",
            "E cannot be determined from the reported section and stiffness properties.",
            ["E_Pa, or EA_N/EI_Nm2 together with enough section geometry."],
        )
    if not math.isfinite(E) or E <= 0.0:
        return finish(
            result,
            "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
            "E must be positive and finite.",
        )
    result["derived_properties"]["E_Pa"] = E

    EA = E * area
    EI = E * inertia
    mass = None
    if rho is None and mass_target is not None:
        rho = mass_target / area
        result["inferred_values"]["rho_material_kg_m3"] = rho
    if rho is not None:
        if not math.isfinite(rho) or rho <= 0.0:
            return finish(
                result,
                "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
                "rho_material must be positive and finite.",
            )
        mass = rho * area
    elif mass_target is not None:
        return finish(
            result,
            "INSUFFICIENT_INFORMATION",
            "mass_per_length was reported but could not infer rho_material.",
        )

    if dh_reported is None:
        dh = ds
        result["inferred_values"]["D_hydro_m"] = dh
        result["assumptions"].append(
            "D_hydro_equals_D_struct_under_legacy_coupling"
        )
    else:
        dh = dh_reported
    if dh <= 0.0 or not math.isfinite(dh):
        return finish(
            result,
            "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
            "D_hydro must be positive and finite.",
        )
    displaced_area = PI * dh * dh / 4.0

    result["derived_properties"].update(
        {
            "A_m2": area,
            "I_m4": inertia,
            "EA_N": EA,
            "EI_Nm2": EI,
            "mass_per_length_kg_m": mass,
            "D_hydro_m": dh,
            "displaced_area_m2": displaced_area,
        }
    )
    result["physical_material_density_plausibility"] = {
        "status": "diagnostic_only",
        "positive_finite": rho is not None and math.isfinite(rho) and rho > 0.0,
        "rho_material_kg_m3": output_value(rho),
        "note": "No common-material database is consulted; equivalent/composite density is allowed.",
    }

    forward_targets = {
        "EA_N": (EA, ea_target),
        "EI_Nm2": (EI, ei_target),
        "mass_per_length_kg_m": (mass, mass_target),
        "displaced_area_m2": (displaced_area, adisp_target),
    }
    structural_mismatches: list[str] = []
    for name, (actual, reported) in forward_targets.items():
        if reported is None:
            continue
        error = relative_error(actual, reported)
        result["forward_consistency_errors"][name] = error
        if error is None or error > RELATIVE_TOLERANCE:
            if name in {"EA_N", "EI_Nm2"}:
                structural_mismatches.append(name)

    mass_mismatch = (
        mass_target is not None
        and mass is not None
        and not close_enough(mass, mass_target)
    )
    buoyancy_mismatch = (
        adisp_target is not None
        and not close_enough(displaced_area, adisp_target)
    )
    if structural_mismatches:
        reason = (
            "Reported EA/EI cannot be reproduced with the fixed hydrodynamic "
            "diameter and one legacy annular section."
        )
        missing = [
            "Independent EA, EI, structural section geometry, and hydrodynamic displaced area."
        ]
        return finish(result, "EXPLICIT_SECTION_PROPERTIES_REQUIRED", reason, missing)
    if buoyancy_mismatch:
        return finish(
            result,
            "LEGACY_STRUCTURALLY_REPRESENTABLE_BUT_BUOYANCY_MISMATCH",
            "Structural EA/EI/mass are representable, but reported displaced area differs from pi*D_hydro^2/4.",
        )
    if mass_mismatch:
        return finish(
            result,
            "LEGACY_STRUCTURALLY_REPRESENTABLE_BUT_MASS_MISMATCH",
            "Structural section and stiffness are representable, but reported mass_per_length is inconsistent.",
        )

    unreported_missing: list[str] = []
    if rho is None:
        unreported_missing.append(
            "rho_material_kg_m3 or mass_per_length_kg_m"
        )
    if dh_reported is None:
        unreported_missing.append(
            "D_hydro_m if hydrodynamic displaced area must be independently reported"
        )
    fully_determined = (
        ds is not None
        and di is not None
        and E is not None
        and rho is not None
        and not assumption_solid
        and (dh_reported is not None or ds_reported is not None)
    )
    if fully_determined:
        return finish(
            result,
            "LEGACY_EXACTLY_REPRESENTABLE",
            "All reported structural/hydrodynamic quantities forward-recompute consistently under the legacy formulas.",
        )
    return finish(
        result,
        "LEGACY_REPRESENTABLE_WITH_UNREPORTED_PARAMETER_INFERRED",
        "The supplied fields determine a valid legacy representation, with at least one required parameter inferred or assumed.",
        unreported_missing,
    )


def valid_case() -> tuple[dict[str, Any], dict[str, float]]:
    D = 0.05
    Di = 0.04
    E = 2.0e9
    rho = 4000.0
    A = PI * (D * D - Di * Di) / 4.0
    I = PI * (D**4 - Di**4) / 64.0
    expected = {
        "A_m2": A,
        "I_m4": I,
        "EA_N": E * A,
        "EI_Nm2": E * I,
        "mass_per_length_kg_m": rho * A,
        "displaced_area_m2": PI * D * D / 4.0,
    }
    case = {
        "case_id": "case_1_valid_recovery",
        "fields": {
            "D_hydro_m": {"status": "known", "value": D},
            "EA_N": {"status": "known", "value": expected["EA_N"]},
            "EI_Nm2": {"status": "known", "value": expected["EI_Nm2"]},
            "mass_per_length_kg_m": {
                "status": "known",
                "value": expected["mass_per_length_kg_m"],
            },
            "E_Pa": {"status": "unknown"},
            "Di_m": {"status": "not_reported"},
            "rho_material_kg_m3": {"status": "not_reported"},
        },
    }
    return case, expected


def self_tests() -> dict[str, Any]:
    valid, expected = valid_case()
    cases: list[tuple[str, dict[str, Any], str]] = [
        ("case_1_valid_recovery", valid, "LEGACY_EXACTLY_REPRESENTABLE"),
        (
            "case_2_negative_Di2",
            {
                "case_id": "case_2_negative_Di2",
                "fields": {
                    "D_hydro_m": {"status": "known", "value": 0.05},
                    "EA_N": {"status": "known", "value": 1.0e6},
                    "EI_Nm2": {"status": "known", "value": 1.0},
                },
            },
            "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
        ),
        (
            "case_3_Di_ge_D",
            {
                "case_id": "case_3_Di_ge_D",
                "fields": {
                    "D_hydro_m": {"status": "known", "value": 0.05},
                    "EA_N": {"status": "known", "value": 1.0e6},
                    "EI_Nm2": {"status": "known", "value": 400.0},
                },
            },
            "LEGACY_SECTION_GEOMETRY_INFEASIBLE",
        ),
        (
            "case_4_buoyancy_mismatch",
            {
                "case_id": "case_4_buoyancy_mismatch",
                "fields": {
                    "D_hydro_m": {"status": "known", "value": 0.05},
                    "EA_N": {"status": "known", "value": expected["EA_N"]},
                    "EI_Nm2": {"status": "known", "value": expected["EI_Nm2"]},
                    "mass_per_length_kg_m": {
                        "status": "known",
                        "value": expected["mass_per_length_kg_m"],
                    },
                    "displaced_area_m2": {"status": "known", "value": 0.001},
                },
            },
            "LEGACY_STRUCTURALLY_REPRESENTABLE_BUT_BUOYANCY_MISMATCH",
        ),
        (
            "case_5_EA_EI_without_D",
            {
                "case_id": "case_5_EA_EI_without_D",
                "fields": {
                    "EA_N": {"status": "known", "value": expected["EA_N"]},
                    "EI_Nm2": {"status": "known", "value": expected["EI_Nm2"]},
                },
            },
            "INSUFFICIENT_INFORMATION",
        ),
        (
            "case_6_solid_equivalent_assumption",
            {
                "case_id": "case_6_solid_equivalent_assumption",
                "fields": {
                    "EA_N": {"status": "known", "value": 3926990.8169872414},
                    "EI_Nm2": {"status": "known", "value": 6135.923151538814},
                },
                "assume_solid_equivalent_section": True,
            },
            "LEGACY_REPRESENTABLE_WITH_UNREPORTED_PARAMETER_INFERRED",
        ),
        (
            "case_7_D_EI_E_partial",
            {
                "case_id": "case_7_D_EI_E_partial",
                "fields": {
                    "D_hydro_m": {"status": "known", "value": 0.05},
                    "EI_Nm2": {"status": "known", "value": expected["EI_Nm2"]},
                    "E_Pa": {"status": "known", "value": 2.0e9},
                },
            },
            "LEGACY_REPRESENTABLE_WITH_UNREPORTED_PARAMETER_INFERRED",
        ),
        (
            "case_8_D_Di_E_rho_full",
            {
                "case_id": "case_8_D_Di_E_rho_full",
                "fields": {
                    "D_hydro_m": {"status": "known", "value": 0.05},
                    "Di_m": {"status": "known", "value": 0.04},
                    "E_Pa": {"status": "known", "value": 2.0e9},
                    "rho_material_kg_m3": {"status": "known", "value": 4000.0},
                },
            },
            "LEGACY_EXACTLY_REPRESENTABLE",
        ),
        (
            "case_9_hydro_structural_diameter_conflict",
            {
                "case_id": "case_9_hydro_structural_diameter_conflict",
                "fields": {
                    "D_hydro_m": {"status": "known", "value": 0.05},
                    "D_struct_m": {"status": "known", "value": 0.06},
                    "Di_m": {"status": "known", "value": 0.04},
                    "E_Pa": {"status": "known", "value": 2.0e9},
                    "rho_material_kg_m3": {"status": "known", "value": 4000.0},
                },
            },
            "LEGACY_HYDRO_DIAMETER_CONFLICT",
        ),
        (
            "case_10_mass_mismatch",
            {
                "case_id": "case_10_mass_mismatch",
                "fields": {
                    "D_hydro_m": {"status": "known", "value": 0.05},
                    "Di_m": {"status": "known", "value": 0.04},
                    "E_Pa": {"status": "known", "value": 2.0e9},
                    "rho_material_kg_m3": {"status": "known", "value": 4000.0},
                    "mass_per_length_kg_m": {
                        "status": "known",
                        "value": expected["mass_per_length_kg_m"] * 1.1,
                    },
                },
            },
            "LEGACY_STRUCTURALLY_REPRESENTABLE_BUT_MASS_MISMATCH",
        ),
    ]
    reports = []
    failures = []
    for name, case, expected_classification in cases:
        report = compatibility_check(case)
        report["self_test_expected_classification"] = expected_classification
        report["self_test_pass"] = report["classification"] == expected_classification
        reports.append(report)
        if not report["self_test_pass"]:
            failures.append(
                f"{name}: expected {expected_classification}, got {report['classification']}"
            )

    return {
        "tool": TOOL_VERSION,
        "production_identity": {
            "commit": PRODUCTION_COMMIT,
            "cpp_sha256": PRODUCTION_CPP_SHA256,
            "hpp_sha256": PRODUCTION_HPP_SHA256,
            "production_modified": False,
            "compile_run": False,
            "numerical_run": False,
            "OpenFOAM_run": False,
            "preCICE_run": False,
            "CFD_FSI_run": False,
        },
        "rules": {
            "legacy_formulas": {
                "A": "pi/4*(D^2-Di^2)",
                "I": "pi/64*(D^4-Di^4)",
                "EA": "E*A",
                "EI": "E*I",
                "mass_per_length": "rho_material*A",
                "displaced_area": "pi*D_hydro^2/4",
            },
            "forward_relative_tolerance": RELATIVE_TOLERANCE,
            "D_hydro_is_not_silently_changed": True,
            "material_density_plausibility_is_diagnostic_only": True,
        },
        "cases": reports,
        "self_test_pass": not failures,
        "self_test_failures": failures,
        "final_decision": {
            "legacy_parameters_cover_all_physically_reasonable_literature_sets": False,
            "answer": (
                "No. The legacy E/D/Di/rho parameterization covers cases where one "
                "annular structural diameter is also the hydrodynamic diameter and "
                "the supplied properties satisfy the coupled formulas. It does not "
                "cover independent structural/hydrodynamic geometry or arbitrary "
                "independently reported EA, EI, mass_per_length, and displaced_area."
            ),
            "explicit_property_api_required_when": [
                "D_hydro differs from the structural outer diameter needed by EA/EI.",
                "EA, EI, and mass_per_length cannot be produced by one E, one annular D/Di, and one rho_material.",
                "Reported displaced_area differs from pi*D_hydro^2/4 while the structural properties remain valid.",
                "Structural EA/EI/mass and hydrodynamic displaced area or diameter must be independently specified.",
            ],
        },
    }


def write_self_test_outputs(output_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = self_tests()
    json_path = output_dir / "ANCF_LITERATURE_SECTION_COMPATIBILITY_SELFTEST_V1.json"
    txt_path = output_dir / "ANCF_LITERATURE_SECTION_COMPATIBILITY_SELFTEST_V1.txt"
    json_path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        TOOL_VERSION,
        "SELF_TEST_MATRIX",
        f"self_test_pass={str(data['self_test_pass']).lower()}",
        f"relative_tolerance={RELATIVE_TOLERANCE:.17g}",
        "",
    ]
    for report in data["cases"]:
        lines.extend(
            [
                f"case_id={report['case_id']}",
                f"classification={report['classification']}",
                f"expected={report['self_test_expected_classification']}",
                f"pass={str(report['self_test_pass']).lower()}",
                f"reason={report['reason']}",
                f"derived_properties={json.dumps(report['derived_properties'], sort_keys=True)}",
                f"forward_consistency_errors={json.dumps(report['forward_consistency_errors'], sort_keys=True)}",
                f"missing_information={json.dumps(report['missing_information'], ensure_ascii=False)}",
                "",
            ]
        )
    lines.extend(
        [
            "FINAL_DECISION",
            "legacy_parameters_cover_all_physically_reasonable_literature_sets=false",
            data["final_decision"]["answer"],
            "explicit_property_api_required_when:",
        ]
    )
    lines.extend(
        f"- {item}" for item in data["final_decision"]["explicit_property_api_required_when"]
    )
    if data["self_test_failures"]:
        lines.extend(["", "FAILURES"])
        lines.extend(data["self_test_failures"])
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, txt_path, data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("runtime/ANCF_validation")
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        json_path, txt_path, data = write_self_test_outputs(args.output_dir)
        print(f"self_test_pass={str(data['self_test_pass']).lower()}")
        print(f"json={json_path}")
        print(f"text={txt_path}")
        return 0 if data["self_test_pass"] else 1
    if args.input is None:
        parser.error("use --self-test or provide --input")
    case = json.loads(args.input.read_text(encoding="utf-8"))
    report = compatibility_check(case)
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
