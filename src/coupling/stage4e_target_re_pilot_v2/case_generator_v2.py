"""Independent v2 OpenFOAM case generator with an O-grid-equivalent mesh family."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from .identity_v2 import D, NU, RHO, finite, sha256_file, sha256_json

PROJECT = Path(__file__).resolve().parents[3]
CASE_ROOT = PROJECT / "cases" / "openfoam" / "stage4e_target_re_fixed_cylinder_v2"
UPSTREAM_TEMPLATE = PROJECT / "cases" / "openfoam" / "stage4e_route_g_reverse_flow_template" / "base" / "system" / "blockMeshDict"
MESH_LEVELS = {
    # The prior v2 retry used 24/36/48 cells per in-plane block.  That was
    # useful for the short y+ probe but made the required >=15-cycle pilot
    # impractically slow.  This independent run keeps the same conformal
    # eight-sector topology and grading contract while reducing the outer
    # block cost; the actual y+ and CFL values remain measured from OpenFOAM.
    "coarse": {"radial_layers": 12, "circumferential_cells_per_sector": 12, "outer_cells": 12, "radial_grading": 6.0},
    "medium": {"radial_layers": 16, "circumferential_cells_per_sector": 16, "outer_cells": 16, "radial_grading": 100.0},
    "fine": {"radial_layers": 24, "circumferential_cells_per_sector": 24, "outer_cells": 24, "radial_grading": 1000.0},
}
DOMAIN_EXTENTS = {"baseline": (25.0, 15.0), "expanded": (35.0, 20.0)}
INNER_BLOCKS = {0, 1, 5, 6, 10, 11, 15, 16}
INNER_BLOCKS_REVERSE = {5, 6, 15, 16}
# blockMesh simpleGrading is the total last-cell/first-cell ratio.  A large
# ratio is required to create a genuinely thin first layer; it is not a
# per-layer geometric factor.
RADIAL_GROWTH = 1000.0
NEAR_RADIUS = 1.5


def _fmt(value: float) -> str:
    return f"{value:.15g}"


def _header(cls: str, obj: str, location: str) -> str:
    return f'''FoamFile
{{
    format ascii;
    class {cls};
    location {location};
    object {obj};
}}
'''


def _fresh_dir(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to reuse v2 case directory: {path}")
    path.mkdir(parents=True)


def _write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def _map_xy(x: float, y: float, x_extent: float, y_extent: float) -> tuple[float, float]:
    r = math.hypot(x, y)
    if abs(r - 0.5) < 1e-4:
        target = 0.5
        return target * x / r, target * y / r
    if abs(r - 1.0) < 1e-4:
        target = NEAR_RADIUS
        return target * x / r, target * y / r
    if abs(abs(x) - 10.0) < 1e-9:
        x = math.copysign(x_extent, x)
    if abs(abs(y) - 5.0) < 1e-9:
        y = math.copysign(y_extent, y)
    return x, y


def _block_mesh_text(mesh_level: str, domain: str) -> tuple[str, dict[str, Any]]:
    if not UPSTREAM_TEMPLATE.exists():
        raise FileNotFoundError(UPSTREAM_TEMPLATE)
    params = MESH_LEVELS[mesh_level]
    x_extent, y_extent = DOMAIN_EXTENTS[domain]
    text = UPSTREAM_TEMPLATE.read_text(encoding="utf-8")
    text = re.sub(r"convertToMeters\s+[^;]+;", f"convertToMeters {D:.15g};", text, count=1)
    vertex_re = re.compile(r"^(\s*\()\s*(%s)\s+(%s)\s+(%s)(\s*\).*)$" % (r"[-+]?\d*\.?\d+", r"[-+]?\d*\.?\d+", r"[-+]?\d*\.?\d+"))
    arc_re = re.compile(r"^(\s*arc\s+\d+\s+\d+\s+\()\s*(%s)\s+(%s)\s+(%s)(\).*)$" % (r"[-+]?\d*\.?\d+", r"[-+]?\d*\.?\d+", r"[-+]?\d*\.?\d+"))
    lines: list[str] = []
    for line in text.splitlines():
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
            level_grade = float(params["radial_grading"])
            if block_index in INNER_BLOCKS_REVERSE:
                grade = 1.0 / level_grade
            elif block_index in INNER_BLOCKS:
                grade = level_grade
            else:
                grade = 1.0
            # The source eight-sector topology rotates local block axes.  Equal
            # counts on both in-plane directions are required for conformal
            # shared faces; radial grading supplies the near-wall resolution.
            line = re.sub(r"\)\s+\(\d+\s+\d+\s+1\)\s+simpleGrading\s+\([^)]*\)", f") ({params['radial_layers']} {params['radial_layers']} 1) simpleGrading ({_fmt(grade)} 1 1)", line)
            block_index += 1
        out.append(line)
        if in_blocks and stripped == ");":
            in_blocks = False
    n = params["radial_layers"]
    level_grade = float(params["radial_grading"])
    q = level_grade ** (1.0 / max(n - 1, 1))
    first_width = (NEAR_RADIUS - 0.5) * (q - 1.0) / (q ** n - 1.0)
    metadata = {
        "mesh_level": mesh_level, "domain": domain, "dimensionless_domain_x": [-x_extent, x_extent], "dimensionless_domain_y": [-y_extent, y_extent],
        "diameter_m": D, "z_dimensionless": [-0.5, 0.5], "b_mesh_m": D, "near_field_radius_D": NEAR_RADIUS,
        "radial_layers": params["radial_layers"], "circumferential_cells_per_sector": params["circumferential_cells_per_sector"], "radial_growth": level_grade,
        "first_cell_width_m": first_width * D, "first_cell_center_to_wall_m": 0.5 * first_width * D,
        "topology": "eight-sector circular attached O-grid-equivalent with graded inner radial blocks and rectangular outer blocks",
    }
    return "\n".join(out) + "\n", metadata


def _u_field(U: float, direction: int) -> str:
    signed = float(direction) * abs(float(U))
    inlet, outlet = ("left", "right") if direction > 0 else ("right", "left")
    return _header("volVectorField", "U", '"0"') + f'''dimensions [0 1 -1 0 0 0 0];
internalField uniform ({_fmt(signed)} 0 0);
boundaryField
{{
    {inlet} {{ type fixedValue; value uniform ({_fmt(signed)} 0 0); }}
    {outlet} {{ type zeroGradient; }}
    lower {{ type symmetryPlane; }}
    upper {{ type symmetryPlane; }}
    cylinder {{ type noSlip; }}
    defaultFaces {{ type empty; }}
}}
'''


def _p_field(direction: int) -> str:
    inlet, outlet = ("left", "right") if direction > 0 else ("right", "left")
    return _header("volScalarField", "p", '"0"') + f'''dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField
{{
    {inlet} {{ type zeroGradient; }}
    {outlet} {{ type fixedValue; value uniform 0; }}
    lower {{ type symmetryPlane; }}
    upper {{ type symmetryPlane; }}
    cylinder {{ type zeroGradient; }}
    defaultFaces {{ type empty; }}
}}
'''


def _k_field(U: float) -> str:
    k = max(1.5e-4, 0.003 * U * U)
    return _header("volScalarField", "k", '"0"') + f'''dimensions [0 2 -2 0 0 0 0];
internalField uniform {_fmt(k)};
boundaryField
{{
    left {{ type fixedValue; value uniform {_fmt(k)}; }}
    right {{ type zeroGradient; }}
    lower {{ type symmetryPlane; }}
    upper {{ type symmetryPlane; }}
    cylinder {{ type kqRWallFunction; value uniform 0; }}
    defaultFaces {{ type empty; }}
}}
'''


def _omega_field(U: float) -> str:
    omega = max(1.0, 20.0 * U / D)
    return _header("volScalarField", "omega", '"0"') + f'''dimensions [0 0 -1 0 0 0 0];
internalField uniform {_fmt(omega)};
boundaryField
{{
    left {{ type fixedValue; value uniform {_fmt(omega)}; }}
    right {{ type zeroGradient; }}
    lower {{ type symmetryPlane; }}
    upper {{ type symmetryPlane; }}
    cylinder {{ type omegaWallFunction; value uniform {_fmt(omega)}; }}
    defaultFaces {{ type empty; }}
}}
'''


def _nut_field() -> str:
    return _header("volScalarField", "nut", '"0"') + '''dimensions [0 2 -1 0 0 0 0];
internalField uniform 0;
boundaryField
{
    left { type calculated; value uniform 0; }
    right { type calculated; value uniform 0; }
    lower { type symmetryPlane; }
    upper { type symmetryPlane; }
    cylinder { type nutkWallFunction; value uniform 0; }
    defaultFaces { type empty; }
}
'''


def _physical_properties() -> str:
    return _header("dictionary", "physicalProperties", '"constant"') + f'''viscosityModel constant;
nu [0 2 -1 0 0 0 0] {_fmt(NU)};
'''


def _momentum_transport(model: str) -> str:
    if model == "laminar":
        return _header("dictionary", "momentumTransport", '"constant"') + "simulationType laminar;\n"
    if model != "kOmegaSST":
        raise ValueError(model)
    return _header("dictionary", "momentumTransport", '"constant"') + '''simulationType RAS;
RAS
{
    model kOmegaSST;
    turbulence on;
    printCoeffs on;
}
'''


def _fv_schemes(model: str) -> str:
    turbulence = "    div(phi,k) Gauss upwind;\n    div(phi,omega) Gauss upwind;\n" if model == "kOmegaSST" else ""
    return _header("dictionary", "fvSchemes", '"system"') + f'''ddtSchemes {{ default Euler; }}
gradSchemes {{ default cellLimited Gauss linear 1; }}
divSchemes
{{
    default none;
    div(phi,U) bounded Gauss linearUpwind grad(U);
{turbulence}    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}}
laplacianSchemes {{ default Gauss linear corrected; }}
interpolationSchemes {{ default linear; }}
snGradSchemes {{ default corrected; }}
wallDist {{ method meshWave; }}
'''


def _fv_solution(model: str) -> str:
    fields = "    k { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0; }\n    kFinal { $k; relTol 0; }\n    omega { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0; }\n    omegaFinal { $omega; relTol 0; }\n" if model == "kOmegaSST" else ""
    return _header("dictionary", "fvSolution", '"system"') + f'''solvers
{{
    p {{ solver PCG; preconditioner DIC; tolerance 1e-8; relTol 0.05; }}
    pFinal {{ $p; relTol 0; }}
    U {{ solver smoothSolver; smoother symGaussSeidel; tolerance 1e-9; relTol 0; }}
    UFinal {{ $U; relTol 0; }}
{fields}}}
PIMPLE
{{
    nOuterCorrectors 1;
    nCorrectors 2;
    nNonOrthogonalCorrectors 0;
    pRefCell 0;
    pRefValue 0;
}}
'''


def _control_dict(U: float, dt: float, end_time: float, model: str, direction: int, domain: str, mesh_level: str) -> str:
    aref = D * D
    inlet, outlet = ("left", "right") if direction > 0 else ("right", "left")
    return _header("dictionary", "controlDict", '"system"') + f'''application pimpleFoam;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime {_fmt(end_time)};
deltaT {_fmt(dt)};
adjustTimeStep no;
maxCo 0.5;
writeControl timeStep;
writeInterval 100;
purgeWrite 0;
writeFormat ascii;
writePrecision 16;
writeCompression off;
timeFormat general;
timePrecision 16;
runTimeModifiable false;
functions
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
        writeInterval 1;
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
        Aref {_fmt(aref)};
        writeControl timeStep;
        writeInterval 1;
        log yes;
    }}
    yPlus
    {{
        type yPlus;
        libs ("libfieldFunctionObjects.so");
        patches (cylinder);
        writeControl timeStep;
        writeInterval 1;
    }}
}}
// v2 metadata: model={model}, direction={direction:+d}, inlet={inlet}, outlet={outlet}, domain={domain}, mesh={mesh_level}, Aref={_fmt(aref)}
'''


def _set_fields(U: float, epsilon: float) -> str:
    u = abs(float(U)); dx = D
    return _header("dictionary", "setFieldsDict", '"system"') + f'''defaultFieldValues
(
    volVectorFieldValue U ({_fmt(u)} 0 0)
);
regions
(
    boxToCell
    {{
        box ({_fmt(0.5*dx)} {_fmt(0.1*dx)} {_fmt(-0.5*dx)}) ({_fmt(2.5*dx)} {_fmt(0.6*dx)} {_fmt(0.5*dx)});
        fieldValues ( volVectorFieldValue U ({_fmt(u)} {_fmt(epsilon*u)} 0) );
    }}
    boxToCell
    {{
        box ({_fmt(0.5*dx)} {_fmt(-0.6*dx)} {_fmt(-0.5*dx)}) ({_fmt(2.5*dx)} {_fmt(-0.1*dx)} {_fmt(0.5*dx)});
        fieldValues ( volVectorFieldValue U ({_fmt(u)} {_fmt(-epsilon*u)} 0) );
    }}
);
'''


def generate_case(case_dir: Path, *, model: str, mesh_level: str, domain: str, U: float, dt: float, end_time: float, epsilon: float = 0.005, direction: int = 1, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    _fresh_dir(case_dir)
    if mesh_level not in MESH_LEVELS or domain not in DOMAIN_EXTENTS:
        raise ValueError("unsupported mesh or domain")
    for rel in ("0", "constant", "system"):
        (case_dir / rel).mkdir()
    block_text, mesh_meta = _block_mesh_text(mesh_level, domain)
    _write_text(case_dir / "system" / "blockMeshDict", block_text)
    _write_text(case_dir / "system" / "controlDict", _control_dict(U, dt, end_time, model, direction, domain, mesh_level))
    _write_text(case_dir / "system" / "fvSchemes", _fv_schemes(model))
    _write_text(case_dir / "system" / "fvSolution", _fv_solution(model))
    _write_text(case_dir / "system" / "setFieldsDict", _set_fields(U, epsilon))
    _write_text(case_dir / "constant" / "physicalProperties", _physical_properties())
    _write_text(case_dir / "constant" / "momentumTransport", _momentum_transport(model))
    _write_text(case_dir / "0" / "U", _u_field(U, direction))
    _write_text(case_dir / "0" / "p", _p_field(direction))
    if model == "kOmegaSST":
        _write_text(case_dir / "0" / "k", _k_field(abs(U)))
        _write_text(case_dir / "0" / "omega", _omega_field(abs(U)))
        _write_text(case_dir / "0" / "nut", _nut_field())
    meta = {"model": model, "mesh_level": mesh_level, "domain": domain, "U_mps": direction * abs(float(U)), "U_abs_mps": abs(float(U)), "Re": abs(float(U)) * D / NU, "deltaT_s": float(dt), "endTime_s": float(end_time), "epsilon": float(epsilon), "direction": int(direction), "inlet_patch": "left" if direction > 0 else "right", "outlet_patch": "right" if direction > 0 else "left", "mesh_geometry": mesh_meta, "physical_Aref_m2": D * D, "metadata": metadata or {}}
    meta["case_file_hashes"] = {str(path.relative_to(case_dir)).replace("\\", "/"): sha256_file(path) for path in sorted(case_dir.rglob("*")) if path.is_file()}
    meta["case_identity_sha256"] = sha256_json({key: meta[key] for key in ("model", "mesh_level", "domain", "U_mps", "deltaT_s", "epsilon", "direction", "mesh_geometry", "case_file_hashes")})
    _write_text(case_dir / "case_metadata.json", json.dumps(finite(meta), ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return finite(meta)


def case_freshness(case_dir: Path) -> dict[str, Any]:
    forbidden = ["postProcessing", "processor0", "processor1", "log.pimpleFoam", "log.checkMesh", "log.blockMesh", "checkpoint"]
    found = [name for name in forbidden if (case_dir / name).exists()]
    times = [p.name for p in case_dir.iterdir()] if case_dir.exists() else []
    numeric = [name for name in times if name not in {"0", "constant", "system"} and name.replace(".", "", 1).isdigit()]
    links = [str(p) for p in case_dir.rglob("*") if p.is_symlink()] if case_dir.exists() else []
    passed = case_dir.is_dir() and (case_dir / "0").is_dir() and not found and not numeric and not links
    return finite({"case_relative_name": case_dir.name, "fresh_case_created": case_dir.is_dir(), "forbidden_existing_before_run": found, "numeric_time_directories_before_run": numeric, "unexpected_symlinks": links, "passed": passed})
