"""Systematic O-grid-equivalent laminar case generator for v2.2."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from src.coupling.stage4e_target_re_pilot_v2.case_generator_v2 import (
    _fv_schemes,
    _fv_solution,
    _header,
    _momentum_transport,
    _p_field,
    _physical_properties,
    _set_fields,
    _u_field,
    _write_text,
)
from .identity_v2_2 import AREF, B_MESH, D, EPSILON, FIELD_INTERVAL_STEPS, FORCE_INTERVAL_STEPS, NU, PRODUCTION_CFL_TARGET, RHO, finite, sha256_file, sha256_json

PROJECT = Path(__file__).resolve().parents[3]
UPSTREAM_TEMPLATE = PROJECT / "cases" / "openfoam" / "stage4e_route_g_reverse_flow_template" / "base" / "system" / "blockMeshDict"
DOMAIN_EXTENTS = {"baseline": (25.0, 15.0), "expanded": (35.0, 20.0)}
NEAR_RADIUS = 1.5
INNER_BLOCKS = {0, 1, 5, 6, 10, 11, 15, 16}
INNER_BLOCKS_REVERSE = {5, 6, 15, 16}

# The radial grading values solve the blockMesh geometric-series formula for
# first-cell-center targets 7.5e-5, 3.75e-5 and 1.875e-5 m.  The attached
# topology uses conformal 12/16/24 counts in each in-plane block direction;
# wall distance and grading are the controlled refinement ratio, not the old
# unrelated 6/100/1000 grading triplet.
MESH_LEVELS: dict[str, dict[str, Any]] = {
    "coarse": {"radial_layers": 12, "cells_per_sector": 12, "outer_cells": 12, "radial_grading": 59.44324739112206, "target_first_center_m": 7.5e-5},
    "medium": {"radial_layers": 16, "cells_per_sector": 16, "outer_cells": 16, "radial_grading": 101.07182024711074, "target_first_center_m": 3.75e-5},
    "fine": {"radial_layers": 24, "cells_per_sector": 24, "outer_cells": 24, "radial_grading": 148.9181482630833, "target_first_center_m": 1.875e-5},
}


def _fmt(value: float) -> str:
    return f"{float(value):.15g}"


def _map_xy(x: float, y: float, x_extent: float, y_extent: float) -> tuple[float, float]:
    radius = math.hypot(x, y)
    if abs(radius - 0.5) < 1.0e-4:
        return 0.5 * x / radius, 0.5 * y / radius
    if abs(radius - 1.0) < 1.0e-4:
        return NEAR_RADIUS * x / radius, NEAR_RADIUS * y / radius
    if abs(abs(x) - 10.0) < 1.0e-9:
        x = math.copysign(x_extent, x)
    if abs(abs(y) - 5.0) < 1.0e-9:
        y = math.copysign(y_extent, y)
    return x, y


def _block_mesh_text(mesh_level: str, domain: str) -> tuple[str, dict[str, Any]]:
    if not UPSTREAM_TEMPLATE.exists():
        raise FileNotFoundError(UPSTREAM_TEMPLATE)
    params = MESH_LEVELS[mesh_level]
    x_extent, y_extent = DOMAIN_EXTENTS[domain]
    source = UPSTREAM_TEMPLATE.read_text(encoding="utf-8")
    source = re.sub(r"convertToMeters\s+[^;]+;", f"convertToMeters {_fmt(D)};", source, count=1)
    decimal = r"[-+]?\d*\.?\d+"
    vertex_re = re.compile(r"^(\s*\()\s*(%s)\s+(%s)\s+(%s)(\s*\).*)$" % (decimal, decimal, decimal))
    arc_re = re.compile(r"^(\s*arc\s+\d+\s+\d+\s+\()\s*(%s)\s+(%s)\s+(%s)(\).*)$" % (decimal, decimal, decimal))
    lines: list[str] = []
    for line in source.splitlines():
        match = vertex_re.match(line) or arc_re.match(line)
        if match:
            x, y, z = (float(match.group(i)) for i in (2, 3, 4))
            x, y = _map_xy(x, y, x_extent, y_extent)
            line = f"{match.group(1)} {_fmt(x)} {_fmt(y)} {_fmt(z)}{match.group(5)}"
        lines.append(line)
    out: list[str] = []
    block_index = 0
    in_blocks = False
    for line in lines:
        stripped = line.strip()
        if stripped == "blocks":
            in_blocks = True
        if in_blocks and stripped.startswith("hex "):
            grade = float(params["radial_grading"])
            if block_index in INNER_BLOCKS_REVERSE:
                grade = 1.0 / grade
            elif block_index not in INNER_BLOCKS:
                grade = 1.0
            line = re.sub(r"\)\s+\(\d+\s+\d+\s+1\)\s+simpleGrading\s+\([^)]*\)", f") ({int(params['radial_layers'])} {int(params['cells_per_sector'])} 1) simpleGrading ({_fmt(grade)} 1 1)", line)
            block_index += 1
        out.append(line)
        if in_blocks and stripped == ");":
            in_blocks = False
    n = int(params["radial_layers"])
    ratio = float(params["radial_grading"])
    q = ratio ** (1.0 / max(n - 1, 1))
    first_width_dimless = (NEAR_RADIUS - 0.5) * (q - 1.0) / (q**n - 1.0)
    actual_center = 0.5 * first_width_dimless * D
    metadata = {
        "mesh_level": mesh_level,
        "domain": domain,
        "dimensionless_domain_x": [-x_extent, x_extent],
        "dimensionless_domain_y": [-y_extent, y_extent],
        "diameter_m": D,
        "z_dimensionless": [-0.5, 0.5],
        "b_mesh_m": B_MESH,
        "near_field_radius_D": NEAR_RADIUS,
        "radial_layers": n,
        "circumferential_cells_per_sector": int(params["cells_per_sector"]),
        "outer_cells_per_direction": int(params["outer_cells"]),
        "radial_growth_total_last_over_first": ratio,
        "target_first_cell_center_to_wall_m": float(params["target_first_center_m"]),
        "derived_first_cell_center_to_wall_m": actual_center,
        "refinement_ratio_target": 2.0,
        "topology": "eight-sector circular attached O-grid-equivalent with graded inner radial blocks and rectangular outer blocks",
    }
    return "\n".join(out) + "\n", finite(metadata)


def _functions(U: float, force_interval: int = FORCE_INTERVAL_STEPS) -> str:
    return f'''functions
{{
    forces
    {{
        type forces;
        libs ("libforces.so");
        patches (cylinder);
        rho rhoInf;
        rhoInf {_fmt(RHO)};
        CofR (0 0 0);
        writeControl timeStep;
        writeInterval {int(force_interval)};
        log yes;
    }}
    forceCoeffs
    {{
        type forceCoeffs;
        libs ("libforces.so");
        patches (cylinder);
        rho rhoInf;
        rhoInf {_fmt(RHO)};
        CofR (0 0 0);
        liftDir (0 1 0);
        dragDir (1 0 0);
        pitchAxis (0 0 1);
        magUInf {_fmt(abs(U))};
        lRef {_fmt(D)};
        Aref {_fmt(AREF)};
        writeControl timeStep;
        writeInterval {int(force_interval)};
        log yes;
    }}
}}
'''


def control_dict(*, U: float, dt: float, end_time: float, mode: str, start_time: float = 0.0, field_interval: int = FIELD_INTERVAL_STEPS, force_interval: int = FORCE_INTERVAL_STEPS) -> str:
    if mode not in {"warmup", "production"}:
        raise ValueError(mode)
    if mode == "warmup":
        start_from = "startTime"
        delta_t = 1.0e-5
        adjust = "yes"
        max_delta = "maxDeltaT 0.0004;"
        write_control = "runTime"
        write_interval = "0.2"
    else:
        start_from = "latestTime"
        delta_t = dt
        adjust = "no"
        max_delta = ""
        write_control = "timeStep"
        write_interval = str(int(field_interval))
    return _header("dictionary", "controlDict", '"system"') + f'''application pimpleFoam;
startFrom {start_from};
startTime {_fmt(start_time)};
stopAt endTime;
endTime {_fmt(end_time)};
deltaT {_fmt(delta_t)};
adjustTimeStep {adjust};
maxCo {_fmt(PRODUCTION_CFL_TARGET)};
{max_delta}
writeControl {write_control};
writeInterval {write_interval};
purgeWrite 0;
writeFormat ascii;
writePrecision 16;
writeCompression off;
timeFormat general;
timePrecision 16;
runTimeModifiable false;
{_functions(U, force_interval)}
// v2.2: mode={mode}, Aref={_fmt(AREF)}, b_mesh={_fmt(B_MESH)}, field_interval_steps={int(field_interval)}, force_interval_steps={int(force_interval)}
'''


def generate_case(case_dir: Path, *, mesh_level: str, domain: str, U: float, dt: float, end_time: float, mode: str = "warmup", start_time: float = 0.0, epsilon: float = EPSILON, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    if case_dir.exists():
        raise FileExistsError(f"refusing to reuse v2.2 case directory: {case_dir}")
    if mesh_level not in MESH_LEVELS or domain not in DOMAIN_EXTENTS:
        raise ValueError("unsupported mesh level or domain")
    case_dir.mkdir(parents=True)
    for rel in ("0", "constant", "system"):
        (case_dir / rel).mkdir()
    block_text, mesh_meta = _block_mesh_text(mesh_level, domain)
    _write_text(case_dir / "system" / "blockMeshDict", block_text)
    _write_text(case_dir / "system" / "controlDict", control_dict(U=U, dt=dt, end_time=end_time, mode=mode, start_time=start_time))
    _write_text(case_dir / "system" / "fvSchemes", _fv_schemes("laminar"))
    _write_text(case_dir / "system" / "fvSolution", _fv_solution("laminar"))
    _write_text(case_dir / "system" / "setFieldsDict", _set_fields(U, epsilon))
    _write_text(case_dir / "constant" / "physicalProperties", _physical_properties())
    _write_text(case_dir / "constant" / "momentumTransport", _momentum_transport("laminar"))
    _write_text(case_dir / "0" / "U", _u_field(U, 1))
    _write_text(case_dir / "0" / "p", _p_field(1))
    meta = {
        "schema_version": "stage4e-b2-a-v2.2-case-0.1.0",
        "model": "laminar",
        "mesh_level": mesh_level,
        "domain": domain,
        "mode": mode,
        "U_mps": float(abs(U)),
        "Re": float(abs(U) * D / NU),
        "deltaT_s": float(dt),
        "endTime_s": float(end_time),
        "epsilon": float(epsilon),
        "diameter_m": D,
        "b_mesh_m": B_MESH,
        "Aref_OF_m2": AREF,
        "slice_length_used": False,
        "mesh_geometry": mesh_meta,
        "metadata": metadata or {},
    }
    meta["case_file_hashes_before_metadata"] = {str(path.relative_to(case_dir)).replace("\\", "/"): sha256_file(path) for path in sorted(case_dir.rglob("*")) if path.is_file()}
    meta["case_identity_sha256"] = sha256_json({key: meta[key] for key in ("model", "mesh_level", "domain", "U_mps", "deltaT_s", "epsilon", "mesh_geometry", "case_file_hashes_before_metadata")})
    _write_text(case_dir / "case_metadata.json", json.dumps(finite(meta), ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return finite(meta)


def switch_to_production(case_dir: Path, *, U: float, dt: float, end_time: float, start_time: float) -> dict[str, Any]:
    _write_text(case_dir / "system" / "controlDict", control_dict(U=U, dt=dt, end_time=end_time, mode="production", start_time=start_time))
    return {"mode": "production", "start_time_s": float(start_time), "end_time_s": float(end_time), "dt_s": float(dt), "field_interval_steps": FIELD_INTERVAL_STEPS, "force_interval_steps": FORCE_INTERVAL_STEPS, "Aref_OF_m2": AREF, "b_mesh_m": B_MESH}


def mesh_family_definition() -> dict[str, Any]:
    levels = []
    for name, values in MESH_LEVELS.items():
        levels.append({"mesh_level": name, **values, "topology_same": True, "domain_fixed": True, "b_mesh_m": B_MESH})
    return finite({"schema_version": "stage4e-b2-a-v2.2-mesh-family-0.1.0", "levels": levels, "refinement_policy": "radial, circumferential and outer-block counts are doubled coarse-to-medium-to-fine; target first-center distance halves", "forbidden_prior_policy": "6/100/1000 grading is diagnostic only and is not a formal v2.2 family"})
