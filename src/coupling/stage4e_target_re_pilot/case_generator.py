"""Generate fresh, independent OpenFOAM fixed-cylinder pilot cases."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .identity import finite, sha256_file, sha256_json

UPSTREAM_TEMPLATE = (
    Path(__file__).resolve().parents[3]
    / "cases" / "openfoam" / "stage4e_route_g_reverse_flow_template" / "base"
    / "system" / "blockMeshDict"
)


def _fmt(value: float) -> str:
    return f"{value:.15g}"


def _fresh_dir(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to reuse existing pilot case: {path}")
    path.mkdir(parents=True)


def _block_mesh_text(mesh_cells: int, x_extent: float, y_extent: float) -> str:
    text = UPSTREAM_TEMPLATE.read_text(encoding="utf-8")
    text = text.replace("convertToMeters 1;", "convertToMeters 0.02841;")
    text = re.sub(
        r"\) \(16 16 1\) simpleGrading",
        f") ({mesh_cells} {mesh_cells} 1) simpleGrading",
        text,
    )
    vertex_pattern = re.compile(
        r"^(\s*\()\s*([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)\s*(\).*)$"
    )
    lines: list[str] = []
    for line in text.splitlines():
        match = vertex_pattern.match(line)
        if match:
            x, y, z = (float(match.group(i)) for i in (2, 3, 4))
            if abs(abs(x) - 10.0) < 1e-12:
                x = (1.0 if x > 0 else -1.0) * x_extent
            if abs(abs(y) - 5.0) < 1e-12:
                y = (1.0 if y > 0 else -1.0) * y_extent
            line = f"{match.group(1)} {_fmt(x)} {_fmt(y)} {_fmt(z)}{match.group(5)}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def _field_header(cls: str, obj: str, location: str = '"0"') -> str:
    return f'''FoamFile
{{
    format ascii;
    class {cls};
    location {location};
    object {obj};
}}
'''


def _u_field(U: float, direction: int) -> str:
    signed = float(direction) * float(U)
    inlet, outlet = ("left", "right") if direction > 0 else ("right", "left")
    return _field_header("volVectorField", "U") + f'''dimensions [0 1 -1 0 0 0 0];
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
    return _field_header("volScalarField", "p") + f'''dimensions [0 2 -2 0 0 0 0];
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
    return _field_header("volScalarField", "k") + f'''dimensions [0 2 -2 0 0 0 0];
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
    omega = max(1.0, 20.0 * U / 0.02841)
    return _field_header("volScalarField", "omega") + f'''dimensions [0 0 -1 0 0 0 0];
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
    return _field_header("volScalarField", "nut") + '''dimensions [0 2 -1 0 0 0 0];
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


def _momentum_transport(model: str) -> str:
    if model == "laminar":
        return _field_header("dictionary", "momentumTransport", '"constant"') + "simulationType laminar;\n"
    if model != "kOmegaSST":
        raise ValueError(f"unsupported model: {model}")
    return _field_header("dictionary", "momentumTransport", '"constant"') + '''simulationType RAS;
RAS
{
    model kOmegaSST;
    turbulence on;
    printCoeffs on;
}
'''


def _fv_schemes(model: str) -> str:
    extra = ""
    if model == "kOmegaSST":
        extra = "    div(phi,k) Gauss upwind;\n    div(phi,omega) Gauss upwind;\n"
    return _field_header("dictionary", "fvSchemes", '"system"') + f'''ddtSchemes {{ default Euler; }}
gradSchemes {{ default Gauss linear; }}
divSchemes
{{
    default none;
    div(phi,U) Gauss linearUpwind grad(U);
{extra}    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}}
laplacianSchemes {{ default Gauss linear corrected; }}
interpolationSchemes {{ default linear; }}
snGradSchemes {{ default corrected; }}
wallDist {{ method meshWave; }}
'''


def _fv_solution() -> str:
    return _field_header("dictionary", "fvSolution", '"system"') + '''solvers
{
    p { solver PCG; preconditioner DIC; tolerance 1e-8; relTol 0.05; }
    pFinal { $p; relTol 0; }
    U { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-9; relTol 0; }
    UFinal { $U; relTol 0; }
    k { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0; }
    kFinal { $k; relTol 0; }
    omega { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0; }
    omegaFinal { $omega; relTol 0; }
}
PIMPLE
{
    nOuterCorrectors 1;
    nCorrectors 2;
    nNonOrthogonalCorrectors 0;
    pRefCell 0;
    pRefValue 0;
}
'''


def _control_dict(U: float, dt: float, end_time: float, model: str, direction: int, domain_name: str, mesh_level: str) -> str:
    return _field_header("dictionary", "controlDict", '"system"') + f'''application pimpleFoam;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime {_fmt(end_time)};
deltaT {_fmt(dt)};
adjustTimeStep no;
maxCo 0.7;
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
        rhoInf 1000;
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
        rhoInf 1000;
        CofR (0 0 0);
        liftDir (0 1 0);
        dragDir (1 0 0);
        pitchAxis (0 0 1);
        magUInf {_fmt(U)};
        lRef 0.02841;
        Aref 0.02841;
        writeControl timeStep;
        writeInterval 1;
        log yes;
    }}
}}
// B2-A metadata: model={model}, direction={direction:+d}, domain={domain_name}, mesh={mesh_level}
'''


def generate_case(
    case_dir: Path,
    *,
    model: str,
    mesh_level: str,
    domain: str,
    U: float,
    dt: float,
    end_time: float,
    direction: int = 1,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a fresh case and return path-independent metadata."""
    _fresh_dir(case_dir)
    cells = {"coarse": 8, "medium": 16, "fine": 24}[mesh_level]
    extents = {"baseline": (10.0, 5.0), "expanded": (20.0, 10.0)}
    if domain not in extents:
        raise ValueError(f"unsupported domain: {domain}")
    x_extent, y_extent = extents[domain]
    for rel in ("0", "constant", "system"):
        (case_dir / rel).mkdir()
    (case_dir / "0" / "U").write_text(_u_field(U, direction), encoding="utf-8")
    (case_dir / "0" / "p").write_text(_p_field(direction), encoding="utf-8")
    if model == "kOmegaSST":
        (case_dir / "0" / "k").write_text(_k_field(U), encoding="utf-8")
        (case_dir / "0" / "omega").write_text(_omega_field(U), encoding="utf-8")
        (case_dir / "0" / "nut").write_text(_nut_field(), encoding="utf-8")
    (case_dir / "constant" / "momentumTransport").write_text(_momentum_transport(model), encoding="utf-8")
    (case_dir / "constant" / "physicalProperties").write_text(
        _field_header("dictionary", "physicalProperties", '"constant"')
        + "viscosityModel constant;\nnu [0 2 -1 0 0 0 0] 1e-6;\n", encoding="utf-8"
    )
    (case_dir / "system" / "blockMeshDict").write_text(_block_mesh_text(cells, x_extent, y_extent), encoding="utf-8")
    (case_dir / "system" / "controlDict").write_text(
        _control_dict(U, dt, end_time, model, direction, domain, mesh_level), encoding="utf-8"
    )
    (case_dir / "system" / "fvSchemes").write_text(_fv_schemes(model), encoding="utf-8")
    (case_dir / "system" / "fvSolution").write_text(_fv_solution(), encoding="utf-8")
    (case_dir / "system" / "meshQualityDict").write_text(
        (UPSTREAM_TEMPLATE.parent / "meshQualityDict").read_text(encoding="utf-8"), encoding="utf-8"
    )
    relative_files = sorted(str(p.relative_to(case_dir)).replace("\\", "/") for p in case_dir.rglob("*") if p.is_file())
    hashes = {rel: sha256_file(case_dir / rel) for rel in relative_files}
    payload: dict[str, Any] = {
        "schema_version": "stage4e-b2-a-case-metadata-0.1.0",
        "model": model, "mesh_level": mesh_level, "domain": domain,
        "U_mps": float(U) * int(direction), "U_abs_mps": float(U), "direction": int(direction),
        "diameter_m": 0.02841, "rho_kgpm3": 1000.0, "nu_m2ps": 1.0e-6,
        "Re": float(U) * 0.02841 / 1.0e-6, "deltaT_s": float(dt), "endTime_s": float(end_time),
        "mesh_cells_per_block": cells,
        "mesh_family_hash": sha256_json({"mesh_level": mesh_level, "domain": domain, "blockMeshDict_sha256": hashes["system/blockMeshDict"]}),
        "dictionary_hashes": hashes, "force_output_coordinate_system": "global_cartesian_x_y_z",
        "force_coordinate_rotation": False,
    }
    if metadata:
        payload["metadata"] = finite(metadata)
    (case_dir / "case_metadata.json").write_text(json.dumps(finite(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def set_end_time(case_dir: Path, end_time: float) -> None:
    path = case_dir / "system" / "controlDict"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^endTime\s+[^;]+;", f"endTime {_fmt(end_time)};", text, flags=re.MULTILINE)
    path.write_text(text, encoding="utf-8")
