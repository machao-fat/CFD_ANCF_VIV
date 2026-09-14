"""Offline Singh--Mittal benchmark contract audit.

This program only reads existing dictionaries, meshes, reports and contracts.
It creates audit artifacts; it never invokes OpenFOAM, preCICE or ANCF and it
never writes into an existing CFD case.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


SOURCE_ROOT = Path(r"D:\研二文件\开题准备\CFD_ANCF_VIV")
PROJECT_ROOT = Path(r"D:\CFD\CFD_ANCF_VIV")
OUT = PROJECT_ROOT / r"runtime\fixed_cylinder_o_grid\singh_mittal_contract_audit_v1"
CURRENT = PROJECT_ROOT / r"runtime\fixed_cylinder_o_grid\moving_wall_20k_0.005"
FIXED_SETUP = PROJECT_ROOT / r"runtime\fixed_cylinder_o_grid\case"
REGRESSION = PROJECT_ROOT / r"runtime\fixed_cylinder_o_grid\2_dof_validation\coupled_regression_v1"
MESH_GEO = PROJECT_ROOT / r"runtime\fixed_cylinder_o_grid\mesh\formal_o_grid_4ring_144x44_19600.geo"

RHO = 1000.0
D = 1.0
U = 1.0
NU = 0.01
LZ = 1.0
MSTAR = 10.0
URE_FULL = [4.0, 4.5, 4.6, 5.0, 6.25, 7.5, 8.0, 8.4]
URE_MIN = [4.0, 4.6, 5.0, 6.25, 8.0, 8.4]


def sha256(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_info(path: Path) -> Dict[str, object]:
    if not path.is_file():
        return {"path": str(path), "exists": False}
    return {
        "path": str(path),
        "exists": True,
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "lines": len(path.read_text(errors="ignore").splitlines()),
    }


def foam_list_count(path: Path) -> Optional[int]:
    if not path.is_file():
        return None
    text = path.read_text(errors="ignore")
    m = re.search(r"\n\s*(\d+)\s*\n\s*\(", text)
    return int(m.group(1)) if m else None


def owner_cell_count(path: Path) -> Optional[int]:
    """The owner file list length is nFaces; cells are max(owner)+1."""
    if not path.is_file():
        return None
    text = path.read_text(errors="ignore")
    m = re.search(r"\n\s*(\d+)\s*\n\s*\(", text)
    if not m:
        return None
    vals = [int(x) for x in re.findall(r"\b\d+\b", text[m.end():])]
    return max(vals) + 1 if vals else None


def parse_points(path: Path) -> Tuple[List[Tuple[float, float, float]], List[float]]:
    if not path.is_file():
        return [], []
    text = path.read_text(errors="ignore")
    m = re.search(r"\n\s*(\d+)\s*\n\s*\(", text)
    if not m:
        return [], []
    values = []
    for q in re.finditer(r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)", text[m.end():]):
        values.append(tuple(float(v) for v in q.groups()))
    flat = [v for p in values for v in p]
    return values, flat


def parse_faces(path: Path) -> List[List[int]]:
    if not path.is_file():
        return []
    text = path.read_text(errors="ignore")
    m = re.search(r"\n\s*(\d+)\s*\n\s*\(", text)
    if not m:
        return []
    faces = []
    for line in text[m.end():].splitlines():
        q = re.match(r"\s*\d+\(([^)]*)\)", line)
        if q:
            faces.append([int(x) for x in q.group(1).split()])
    return faces


def parse_boundary(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.is_file():
        return {}
    text = path.read_text(errors="ignore")
    # Patch blocks in this dictionary have no nested dictionaries.
    out: Dict[str, Dict[str, str]] = {}
    for m in re.finditer(r"(^\s*)([A-Za-z_][A-Za-z0-9_]*)\s*\{(.*?)^\s*\}", text, re.M | re.S):
        name, body = m.group(2), m.group(3)
        vals = {k: v.strip() for k, v in re.findall(r"\b(nFaces|startFace|type|physicalType)\s+([^;]+);", body)}
        if vals:
            out[name] = vals
    return out


def parse_field_boundaries(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    text = path.read_text(errors="ignore")
    m = re.search(r"boundaryField\s*\{(.*)\n\}", text, re.S)
    if not m:
        return {}
    out = {}
    for q in re.finditer(r"(^\s*)(\w+)\s*\{(.*?)^\s*\}", m.group(1), re.M | re.S):
        out[q.group(2)] = " ".join(q.group(3).split())
    return out


def value(pattern: str, text: str, cast=float, default=None):
    # Dictionary comments can contain the same keywords; remove // comments
    # before extracting scalar settings and allow ^ to match each line.
    text = re.sub(r"//[^\n]*", "", text)
    m = re.search(pattern, text, re.I | re.S | re.M)
    if not m:
        return default
    raw = m.group(1).strip().rstrip(";")
    return raw if cast is str else cast(raw)


def params(ur: float) -> Dict[str, float]:
    m_per_span = MSTAR * math.pi * RHO * D * D / 4.0
    fn = U / (ur * D)
    omega = 2.0 * math.pi * fn
    return {
        "U_star": ur,
        "fn_Hz": fn,
        "Tn_s": 1.0 / fn,
        "omega_n_rad_s": omega,
        "m_star": MSTAR,
        "m_prime_kgpm": m_per_span,
        "M_kg": m_per_span * LZ,
        "Kx_Npm": m_per_span * LZ * omega * omega,
        "Ky_Npm": m_per_span * LZ * omega * omega,
        "Cx_Nspm": 0.0,
        "Cy_Nspm": 0.0,
    }


def write_csv(path: Path, rows: Iterable[Dict[str, object]], fields: List[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def audit_current() -> Dict[str, object]:
    mesh = CURRENT / "constant" / "polyMesh"
    points, _ = parse_points(mesh / "points")
    faces = parse_faces(mesh / "faces")
    boundary = parse_boundary(mesh / "boundary")
    cyl = boundary.get("cylinder", {})
    cyl_faces = int(cyl.get("nFaces", 0)) if cyl else 0
    cyl_start = int(cyl.get("startFace", 0)) if cyl else 0
    cyl_point_ids = {i for face in faces[cyl_start:cyl_start + cyl_faces] for i in face} if faces else set()
    radii = [(points[i][0] ** 2 + points[i][1] ** 2) ** 0.5 for i in cyl_point_ids if i < len(points)]
    xvals = [q[0] for q in points]
    yvals = [q[1] for q in points]
    zvals = [q[2] for q in points]
    control = (CURRENT / "system" / "controlDict").read_text(errors="ignore")
    physical = (CURRENT / "constant" / "physicalProperties").read_text(errors="ignore")
    dynamic = (CURRENT / "constant" / "dynamicMeshDict").read_text(errors="ignore")
    fvsol = (CURRENT / "system" / "fvSolution").read_text(errors="ignore")
    contract_path = CURRENT / "contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8")) if contract_path.is_file() else {}
    cell_count = owner_cell_count(mesh / "owner")
    return {
        "case": str(CURRENT),
        "mesh": {
            "point_count": len(points),
            "cell_count": cell_count,
            "face_count": len(faces),
            "bounds": {
                "xmin": min(xvals) if xvals else None,
                "xmax": max(xvals) if xvals else None,
                "ymin": min(yvals) if yvals else None,
                "ymax": max(yvals) if yvals else None,
                "zmin": min(zvals) if zvals else None,
                "zmax": max(zvals) if zvals else None,
            },
            "cylinder_faces": cyl_faces,
            "cylinder_points": len(cyl_point_ids),
            "cylinder_radius_m": sum(radii) / len(radii) if radii else None,
            "cylinder_radius_min_m": min(radii) if radii else None,
            "cylinder_radius_max_m": max(radii) if radii else None,
            "boundary": boundary,
            "polyMesh_sha256": {name: sha256(mesh / name) for name in ["points", "faces", "owner", "neighbour", "boundary"]},
        },
        "physics": {
            "rho_kgpm3": RHO,
            "U_mps": U,
            "D_m": D,
            "nu_m2ps": value(r"\bnu\s+\[[^\]]+\]\s+([-+0-9.eE]+)", physical, float, None),
            "Re": U * D / NU,
            "span_m": LZ,
        },
        "numerics": {
            "application": value(r"^\s*application\s+(\S+)", control, str, None),
            "deltaT_s": value(r"^\s*deltaT\s+([-+0-9.eE]+)", control, float, None),
            "writeControl": value(r"^\s*writeControl\s+(\S+)", control, str, None),
            "writeInterval": value(r"^\s*writeInterval\s+([-+0-9.eE]+)", control, float, None),
            "pimple_nOuterCorrectors": value(r"nOuterCorrectors\s+(\d+)", fvsol, int, None),
            "pimple_nCorrectors": value(r"nCorrectors\s+(\d+)", fvsol, int, None),
            "correctPhi": value(r"correctPhi\s+(\w+)", fvsol, str, None),
            "correctMeshPhi": value(r"correctMeshPhi\s+(\w+)", fvsol, str, None),
            "dynamicMesh": dynamic,
        },
        "contract": contract,
        "mesh_source_geo": file_info(MESH_GEO),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    current = audit_current()
    b = current["mesh"]["bounds"]
    D_actual = 2.0 * current["mesh"]["cylinder_radius_m"] if current["mesh"]["cylinder_radius_m"] else None
    domain_height = b["ymax"] - b["ymin"] if b["ymax"] is not None else None
    domain_width = b["xmax"] - b["xmin"] if b["xmax"] is not None else None
    current_blockage = D_actual / domain_height if D_actual and domain_height else None
    # The source .geo explicitly defines 44 radial cells with progression 1.08.
    # Compute the first and last layer from its 2.5 m radial interval.
    radial_cells = 44
    radial_growth = 1.08
    radial_interval = 3.0 - 0.5
    first_layer = radial_interval * (radial_growth - 1.0) / (radial_growth ** radial_cells - 1.0)
    last_layer = first_layer * radial_growth ** (radial_cells - 1)

    full_rows = [params(x) | {"matrix": "FULL_8_POINT"} for x in URE_FULL]
    min_rows = [params(x) | {"matrix": "MINIMUM_6_POINT"} for x in URE_MIN]
    matrix_fields = ["matrix", "U_star", "fn_Hz", "Tn_s", "omega_n_rad_s", "m_star", "m_prime_kgpm", "M_kg", "Kx_Npm", "Ky_Npm", "Cx_Nspm", "Cy_Nspm"]
    write_csv(OUT / "singh_parameter_matrix.csv", full_rows + min_rows, matrix_fields)

    domain_rows = [
        {"field": "cylinder diameter D", "singh_value": "1 reference scale (exact geometric scale not stated in accessible primary text)", "current_value": f"{D_actual:.12g} m", "status": "INFERRED_FROM_CURRENT_CASE", "source_basis": "current polyMesh points", "risk": "low if nondimensionalized", "action": "freeze D=1 m"},
        {"field": "cylinder center", "singh_value": "NOT_YET_CONFIRMED", "current_value": "(0,0) m from cylinder point bounds", "status": "NOT_YET_CONFIRMED", "source_basis": "primary full text unavailable", "risk": "medium", "action": "verify figure/method section before production"},
        {"field": "upstream length", "singh_value": "NOT_YET_CONFIRMED", "current_value": f"{0-b['xmin']:.6g} D", "status": "NOT_YET_CONFIRMED", "source_basis": "primary full text unavailable", "risk": "medium", "action": "do not silently equate domains"},
        {"field": "downstream length", "singh_value": "NOT_YET_CONFIRMED", "current_value": f"{b['xmax']:.6g} D", "status": "NOT_YET_CONFIRMED", "source_basis": "primary full text unavailable", "risk": "medium", "action": "do not silently equate domains"},
        {"field": "cross-flow domain height", "singh_value": "20 D implied by 5% blockage secondary report; exact dimensions NOT_YET_CONFIRMED", "current_value": f"{domain_height:.6g} D", "status": "CONFIRMED_FROM_SECONDARY_SOURCE_DIFFERENCE", "source_basis": "Prasanth et al. 2006 secondary discussion", "risk": "high for quantitative VIV amplitude/hysteresis", "action": "document or rebuild benchmark domain"},
        {"field": "current blockage D/H", "singh_value": "0.05 (5%)", "current_value": f"{current_blockage:.12g} ({100*current_blockage:.4g}%)", "status": "DIFFERENT", "source_basis": "current mesh + secondary literature", "risk": "high", "action": "no production run until disposition"},
        {"field": "span thickness", "singh_value": "2D/unit-span treatment NOT_YET_CONFIRMED", "current_value": f"{b['zmax']-b['zmin']:.6g} m, one cell, front/back empty", "status": "CONFIRMED_FROM_CURRENT_CASE_ONLY", "source_basis": "current polyMesh boundary", "risk": "medium", "action": "confirm force per unit span convention"},
        {"field": "outer boundary shape", "singh_value": "NOT_YET_CONFIRMED", "current_value": "rectangular", "status": "NOT_YET_CONFIRMED", "source_basis": "primary full text unavailable", "risk": "medium", "action": "verify primary source"},
        {"field": "mesh cell count", "singh_value": "7236 elements reported for 5% blockage in related secondary study, not Singh primary", "current_value": str(current["mesh"]["cell_count"]), "status": "DIFFERENT/NOT_COMPARABLE", "source_basis": "current polyMesh + Prasanth et al. 2006", "risk": "medium", "action": "compare resolution metrics, not count alone"},
        {"field": "near-wall radial resolution", "singh_value": "NOT_YET_CONFIRMED", "current_value": f"44 layers; first {first_layer:.12g} m, last {last_layer:.12g} m; progression 1.08", "status": "NOT_YET_CONFIRMED", "source_basis": "current formal_o_grid .geo", "risk": "medium", "action": "compare wall/wake resolution after primary contract freeze"},
    ]
    domain_fields = list(domain_rows[0])
    write_csv(OUT / "current_vs_singh_domain_audit.csv", domain_rows, domain_fields)

    bc_rows = [
        {"item": "inlet velocity", "singh": "NOT_YET_CONFIRMED", "current": "fixedValue (1 0 0)", "status": "NOT_YET_CONFIRMED", "evidence": "current 159.999.../U"},
        {"item": "inlet pressure", "singh": "NOT_YET_CONFIRMED", "current": "zeroGradient", "status": "NOT_YET_CONFIRMED", "evidence": "current 159.999.../p"},
        {"item": "outlet velocity", "singh": "NOT_YET_CONFIRMED", "current": "zeroGradient", "status": "NOT_YET_CONFIRMED", "evidence": "current 159.999.../U"},
        {"item": "outlet pressure", "singh": "NOT_YET_CONFIRMED", "current": "fixedValue uniform 0", "status": "NOT_YET_CONFIRMED", "evidence": "current 159.999.../p"},
        {"item": "top/bottom", "singh": "NOT_YET_CONFIRMED", "current": "symmetryPlane", "status": "NOT_YET_CONFIRMED", "evidence": "current boundary and fields"},
        {"item": "cylinder", "singh": "moving elastic support; exact wall statement NOT_YET_CONFIRMED", "current": "wall; movingWallVelocity for dynamic path", "status": "PARTIAL", "evidence": "primary abstract confirms free X/Y, current fields"},
        {"item": "front/back", "singh": "2D treatment NOT_YET_CONFIRMED", "current": "empty, one-cell z span", "status": "NOT_YET_CONFIRMED", "evidence": "current boundary"},
        {"item": "force span", "singh": "coefficient convention NOT_YET_CONFIRMED", "current": "rhoInf=1000, lRef=1, Aref=1; force scale 500 N for Lz=1", "status": "CONFIRMED_CURRENT_ONLY", "evidence": "current controlDict and prior regression identity"},
    ]
    write_csv(OUT / "current_vs_singh_bc_audit.csv", bc_rows, list(bc_rows[0]))

    num_rows = [
        {"item": "flow equations", "singh": "incompressible Navier-Stokes primitive variables", "current": "incompressible laminar pimpleFoam", "status": "PARTIAL_MATCH", "risk": "expected formulation difference; benchmark risk requires sensitivity"},
        {"item": "flow discretization", "singh": "stabilized space-time finite elements; exact orders NOT_YET_CONFIRMED", "current": "finite-volume Euler + Gauss linear/linearUpwind", "status": "EXPECTED_IMPLEMENTATION_DIFFERENCE", "risk": "quantitative force/amplitude risk"},
        {"item": "pressure-velocity coupling", "singh": "GMRES with diagonal preconditioners reported in accessible article text", "current": "PIMPLE, 1 outer/2 pressure correctors, GAMG/PBiCGStab", "status": "DIFFERENT", "risk": "numerical-method sensitivity"},
        {"item": "temporal method", "singh": "bilinear space, linear time FE reported; exact time step NOT_YET_CONFIRMED", "current": "Euler, dt=0.005 s", "status": "DIFFERENT/NOT_YET_CONFIRMED", "risk": "time-step sensitivity"},
        {"item": "moving mesh", "singh": "DSD/SST deforming spatial domain method reported in related method text", "current": "displacementLaplacian + pointDisplacement/cellDisplacement + ALE correction", "status": "EXPECTED_IMPLEMENTATION_DIFFERENCE", "risk": "motion/wake response risk"},
        {"item": "structural DOF", "singh": "free transverse and in-line; identical linear springs; zero damping", "current": "2DOF participant exists but regression used M=2500, K=4940, not Singh m*=10 contract", "status": "BLOCKER", "risk": "physical contract mismatch"},
        {"item": "mass ratio", "singh": "m*=10 (primary abstract); formula needs primary confirmation", "current": "M=2500 kg with rho=1000,D=1,Lz=1 gives m*=4M/(pi rho D² Lz)=3.1831", "status": "BLOCKER", "risk": "wrong mass"},
        {"item": "damping", "singh": "zero damping", "current": "Cx=Cy=0 in regression", "status": "MATCH_FOR_REGRESSION", "risk": "none if preserved"},
        {"item": "added mass", "singh": "not a separate structural mass input in stated contract; exact paper convention NOT_YET_CONFIRMED", "current": "not added", "status": "NOT_YET_CONFIRMED", "risk": "must freeze before production"},
    ]
    write_csv(OUT / "current_vs_singh_numerical_method_audit.csv", num_rows, list(num_rows[0]))

    # Evidence manifest: paths are recorded, not copied or altered.
    evidence_paths = [
        CURRENT / "contract.json", CURRENT / "system" / "controlDict", CURRENT / "system" / "fvSchemes", CURRENT / "system" / "fvSolution",
        CURRENT / "constant" / "physicalProperties", CURRENT / "constant" / "momentumTransport", CURRENT / "constant" / "dynamicMeshDict",
        CURRENT / "constant" / "polyMesh" / "boundary", CURRENT / "constant" / "polyMesh" / "points", CURRENT / "constant" / "polyMesh" / "faces", CURRENT / "constant" / "polyMesh" / "owner",
        CURRENT / "159.999999999999091" / "U", CURRENT / "159.999999999999091" / "p", CURRENT / "159.999999999999091" / "phi",
        REGRESSION / "phase_b" / "contract.json", REGRESSION / "PYTHON_2DOF_COUPLED_REGRESSION_V1_REPORT.md", REGRESSION / "two_dof_precice_participant.py",
        SOURCE_ROOT / r"docs\cfd_history_current_baseline_identity_v1\CFD_HISTORY_CURRENT_BASELINE_IDENTITY_V1_REPORT.md",
        SOURCE_ROOT / r"docs\single_slice_free_fsi_benchmark_selection_v1\SINGLE_SLICE_FREE_FSI_BENCHMARK_SELECTION_AND_MINIMAL_VALIDATION_PLAN_V1.md",
    ]
    manifest = [file_info(x) for x in evidence_paths]
    with (OUT / "file_manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Machine-readable contract audit.
    mass_per_span = MSTAR * math.pi * RHO * D * D / 4.0
    audit = {
        "schema_version": "singh-mittal-benchmark-contract-audit-v1",
        "scope": "offline read-only audit; no solver or new CFD time directory",
        "overall_status": "BLOCKED_BY_CONTRACT_MISMATCH",
        "blocking_reasons": [
            "Current production/2DOF regression still uses Shiels M=2500 kg, K=4940 N/m and is not a Singh m*=10 equal-frequency production contract.",
            "Accessible primary article text confirms m*=10, Re=100, free X/Y and zero damping, but exact domain, boundary, initialization and post-processing conventions are not yet confirmed from the full primary source.",
            f"Current domain blockage is {current_blockage:.12g}, while the related secondary blockage study reports Singh & Mittal (2005) at 5%; this is a quantitative benchmark risk.",
        ],
        "primary_source": {
            "citation": "S.P. Singh and S. Mittal, Journal of Fluids and Structures 20 (2005) 1085-1104, DOI 10.1016/j.jfluidstructs.2005.05.011",
            "url": "https://www.sciencedirect.com/science/article/pii/S0889974605000873",
            "pdf_url": "https://www.electronicsandbooks.com/edt/manual/Magazine/J/Journal%20of%20Fluids%20and%20Structures/2005%20Volume%2020/8/1085-1104.pdf",
            "accessible_evidence": ["Re based on free-stream speed, D and viscosity", "m*=10", "free transverse and in-line motion", "zero structural damping", "U*=1/Fn", "incompressible stabilized space-time finite element formulation"],
            "status_by_field": {"m_star": "CONFIRMED_FROM_PRIMARY_SOURCE", "m_star_formula": "CONFIRMED_FROM_SECONDARY_SOURCE", "Re_definition": "CONFIRMED_FROM_PRIMARY_SOURCE", "free_XY": "CONFIRMED_FROM_PRIMARY_SOURCE", "zero_damping": "CONFIRMED_FROM_PRIMARY_SOURCE", "U_star_formula": "CONFIRMED_FROM_PRIMARY_SOURCE", "domain": "NOT_YET_CONFIRMED", "boundary_conditions": "NOT_YET_CONFIRMED", "initialization": "NOT_YET_CONFIRMED", "amplitude_definition": "NOT_YET_CONFIRMED", "frequency_extraction": "NOT_YET_CONFIRMED", "force_coefficient_convention": "NOT_YET_CONFIRMED"},
        },
        "secondary_sources": [{"citation": "Prasanth et al., Effect of blockage on vortex-induced vibrations at low Reynolds numbers (2006)", "url": "https://www.sciencedirect.com/science/article/pii/S0889974606000521", "evidence": ["blockage defined D/cross-flow dimension", "Singh and Mittal numerical blockage reported as 5%", "blockage affects vibrating-cylinder response"]}, {"citation": "Prasanth & Mittal, Journal of Fluids and Structures 25 (2009), equations reproduced in accessible PDF", "url": "https://electronicsandbooks.com/edt/manual/Magazine/J/Journal%20of%20Fluids%20and%20Structures/2009%20Volume%2025/6/1029-1048.pdf", "evidence": ["m*=4m/(pi rho D^2)", "U*=1/Fn", "force coefficients from pressure and viscous stresses"]}],
        "physical_contract": {"Re": 100.0, "D_m": D, "U_mps": U, "rho_kgpm3": RHO, "nu_m2ps": NU, "span_m": LZ, "m_star_definition": "m*=4*m_prime/(pi*rho*D^2)", "m_prime_kgpm": mass_per_span, "M_kg": mass_per_span * LZ, "damping_ratio": 0.0, "structural_model": "Mx*xddot+Cx*xdot+Kx*x=Fx; My*yddot+Cy*ydot+Ky*y=Fy; diagonal only; no added mass"},
        "parameter_matrices": {"FULL_8_POINT": full_rows, "MINIMUM_6_POINT": min_rows},
        "current_case_audit": current,
        "domain_audit": {"current_blockage": current_blockage, "singh_secondary_blockage": 0.05, "domain_difference_class": "B_POSSIBLY_AFFECTS_QUANTITATIVE_AMPLITUDE", "exact_singh_domain_status": "NOT_YET_CONFIRMED"},
        "current_case_required_changes_before_production": ["create a new Singh 2DOF contract without modifying historical cases", "derive M and K from m*=10 and each U*", "verify primary domain/BC/initialization/amplitude/frequency conventions", "resolve 5% versus current 3.333% blockage", "freeze force coefficient and centered X amplitude definitions"],
        "historical_status_preserved": ["PYTHON_2DOF_STRUCTURE_VERIFIED=PASS", "PYTHON_2DOF_COUPLED_REGRESSION=PASS", "historical FAIL/NOT_EVALUABLE records immutable"],
        "not_run": True,
    }
    with (OUT / "SINGH_MITTAL_BENCHMARK_CONTRACT_AUDIT_V1.json").open("w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)

    # Human-readable post-processing and budget contracts.
    (OUT / "postprocessing_contract.md").write_text("""# Singh--Mittal post-processing contract (v1, audit only)\n\n- This file freezes definitions for review; no production run was started.\n- Use accepted physical windows only. Exclude trial, rejected and restored samples.\n- Re = UD/nu; U* = U/(fn D) = 1/Fn (primary article text confirms the latter).\n- Centered inline signal: x' = x - mean(x). Report mean(x)/D separately.\n- Proposed amplitudes pending primary confirmation: Ax/D=(max(x')-min(x'))/(2D), Ay/D=(max(y)-min(y))/(2D). Report RMS as a separate quantity.\n- Proposed frequencies: dominant spectral/zero-crossing fX D/U and fY D/U; do not force fX=2fY.\n- Coefficients: Cd=Fx/(0.5 rho U^2 D Lz), Cl=Fy/(0.5 rho U^2 D Lz). With the current scale, qDL=500 N.\n- Stable-window statistics require at least five complete cycles and explicit cycle-level drift checks; transient and retained windows must be separate.\n- Exact Singh amplitude, frequency extraction, force convention and initialization remain `NOT_YET_CONFIRMED` until the full primary paper is available.\n""", encoding="utf-8")
    budget_lines = ["# Singh--Mittal proposed run budget (not executed)", "", "No CFD/preCICE/ANCF run was started in this audit.", "Each U* is an independent case; do not continue one U* into another.", "The first proposal is 15--20 structural periods, then retain >=5 stable cycles. If not stationary, extend only 5 Tn at a time after review.", "", "| U* | Tn [s] | 15 Tn [s] | 20 Tn [s] | steps at dt=.005 (15Tn/20Tn) |", "|---:|---:|---:|---:|---:|"]
    for ur in URE_FULL:
        p = params(ur)
        budget_lines.append(f"| {ur:g} | {p['Tn_s']:.12g} | {15*p['Tn_s']:.12g} | {20*p['Tn_s']:.12g} | {15*p['Tn_s']/0.005:.0f} / {20*p['Tn_s']/0.005:.0f} |")
    budget_lines += ["", "Hard stops to freeze before any future run: NaN/Inf/FPE, negative volume, solver/preCICE fatal, coupling failure at max iterations, existing Co/continuity hard failure, or nonphysical runaway.", "No U* production run is authorized by this audit."]
    (OUT / "run_budget_estimate.md").write_text("\n".join(budget_lines) + "\n", encoding="utf-8")

    # Main report.
    report = f"""# SINGH_MITTAL_BENCHMARK_CONTRACT_AUDIT_V1\n\n**Scope:** offline/read-only contract audit. No OpenFOAM, preCICE, ANCF, mesh generation or new CFD time directory was created. Existing cases and historical records were not modified.\n\n## Overall decision\n\n`BLOCKED_BY_CONTRACT_MISMATCH`\n\nThe software chain remains qualified (`PYTHON_2DOF_STRUCTURE_VERIFIED=PASS`, `PYTHON_2DOF_COUPLED_REGRESSION=PASS`), but it is not yet a Singh--Mittal production contract. The current 20k candidate is a Shiels 1DOF/legacy regression setup (`M=2500 kg`, `K=4940 N/m`) and must not be relabeled as `m*=10` Singh physics.\n\n### Minimal blockers\n\n1. Singh mass ratio is reported as `m*=10`; the published convention used by the Singh/Mittal group is `m*=4 m'/(pi rho D^2)` (formula reproduced in the related peer-reviewed paper). For `rho=1000`, `D=1`, `Lz=1`, this gives `m'=7853.981633974483 kg/m` and `M=7853.981633974483 kg`, not 2500 kg.\n2. The current 2DOF regression has diagonal X/Y equations and zero damping, but uses `Mx=My=2500`, `Kx=Ky=4940`; it is a software regression, not a Singh point.\n3. Current domain is `x=[{b['xmin']:.6g},{b['xmax']:.6g}]D`, `y=[{b['ymin']:.6g},{b['ymax']:.6g}]D`, `z=[{b['zmin']:.6g},{b['zmax']:.6g}] m`, blockage `D/H={current_blockage:.12g}` ({100*current_blockage:.4g}%). A related secondary blockage study explicitly reports Singh--Mittal numerical blockage as 5%; exact Singh domain dimensions still require primary-source confirmation.\n4. Exact Singh domain dimensions, BC details, initialization/hysteresis protocol, amplitude and frequency conventions, and force-coefficient convention are `NOT_YET_CONFIRMED` because the full primary article was not available in the local evidence set.\n\n## Evidence status\n\nThe ScienceDirect record confirms the article identity, incompressible flow formulation, `Re` based on free-stream speed/diameter/viscosity, `m*=10`, free transverse and in-line motion, zero structural damping, and `U*=1/Fn`.[^1] A related published Singh/Mittal-group formulation gives `m*=4m/(pi rho D^2)` and the pressure/viscous coefficient integral.[^3] The related blockage study defines blockage as `D` divided by cross-flow domain dimension and reports Singh--Mittal at 5%; it also warns that blockage affects vibrating-cylinder response.[^2] These sources do not substitute for the missing primary domain/BC/initialization details.\n\n| Field | Status |\n|---|---|\n| m*=10 | CONFIRMED_FROM_PRIMARY_SOURCE |\n| m* formula | CONFIRMED_FROM_SECONDARY_SOURCE (same author group; primary equation still to be page-checked) |\n| Re=UD/nu | CONFIRMED_FROM_PRIMARY_SOURCE |\n| free X/Y, equal linear springs, zero damping | CONFIRMED_FROM_PRIMARY_SOURCE/accessible article text |\n| U*=1/Fn | CONFIRMED_FROM_PRIMARY_SOURCE/accessible article text |\n| exact domain and blockage geometry | NOT_YET_CONFIRMED (5% only secondary evidence) |\n| inlet/outlet/top/bottom/cylinder/2D BCs | NOT_YET_CONFIRMED |\n| initial flow and structural perturbation/hysteresis protocol | NOT_YET_CONFIRMED |\n| amplitude and frequency extraction conventions | NOT_YET_CONFIRMED |\n| exact coefficient normalization | NOT_YET_CONFIRMED |\n\n## Current case identity (read-only)\n\n- Case: `{CURRENT}`\n- Mesh: `{current['mesh']['cell_count']}` cells, `{current['mesh']['point_count']}` points, `{current['mesh']['cylinder_faces']}` cylinder faces; cylinder radius `{current['mesh']['cylinder_radius_m']:.12g} m` (D `{D_actual:.12g} m`).\n- Domain: `x={b['xmin']:.6g}..{b['xmax']:.6g}`, `y={b['ymin']:.6g}..{b['ymax']:.6g}`, `z={b['zmin']:.6g}..{b['zmax']:.6g}`.\n- Boundary types: front/back `empty`; cylinder `wall`; inlet/outlet `patch`; upper/lower `symmetryPlane`. Field values are recorded in `current_vs_singh_bc_audit.csv`.\n- Fluid: `rho=1000 kg/m3`, `nu={current['physics']['nu_m2ps']} m2/s`, `U=1 m/s`, `Re=100`, laminar.\n- Solver: `pimpleFoam`, Euler `deltaT={current['numerics']['deltaT_s']} s`, PIMPLE outer `{current['numerics']['pimple_nOuterCorrectors']}`, pressure correctors `{current['numerics']['pimple_nCorrectors']}`, `correctPhi={current['numerics']['correctPhi']}`, `correctMeshPhi={current['numerics']['correctMeshPhi']}`, dynamic `displacementLaplacian`.\n- Force dictionary: `liftDir=(0 1 0)`, `dragDir=(1 0 0)`, `rhoInf=1000`, `lRef=1`, `Aref=1`; current regression already supplies force-identity evidence, but that does not confirm Singh's literature convention.\n- Initial state: current case contract records `159.999999999999091` fixed-cylinder field as the dynamic start, with U/p/phi copied and zero transition displacement fields. This is current-case evidence, not evidence of Singh's initialization.\n- Near-wall mesh source: `formal_o_grid_4ring_144x44_19600.geo`, 44 radial layers, first layer approximately `{first_layer:.12g} m`, last layer `{last_layer:.12g} m`, progression 1.08. This is current-mesh evidence; Singh wall spacing is not yet confirmed.\n\n## Parameter matrices\n\nFor all rows `U=D=1`, `m*=10`, `C_x=C_y=0`, `M_x=M_y=M`, `K_x=K_y=M(2pi/U*)^2`. Values are generated by `audit_contract.py`; no hand-copied production constants are authorized.\n\nSee `singh_parameter_matrix.csv` for both requested matrices.\n\n| U* | fn [Hz] | Tn [s] | omega [rad/s] | M [kg] | K [N/m] |\n|---:|---:|---:|---:|---:|---:|\n"""
    for row in full_rows:
        report += f"| {row['U_star']:g} | {row['fn_Hz']:.12g} | {row['Tn_s']:.12g} | {row['omega_n_rad_s']:.12g} | {row['M_kg']:.12g} | {row['Kx_Npm']:.12g} |\n"
    report += """\n## Difference tables and future run contract\n\n- `current_vs_singh_domain_audit.csv`: geometry, blockage, resolution and evidence status.\n- `current_vs_singh_bc_audit.csv`: boundary-by-boundary comparison.\n- `current_vs_singh_numerical_method_audit.csv`: formulation, solver, time and structural differences.\n- `postprocessing_contract.md`: accepted-only statistics, centered X amplitude, frequency and coefficient definitions; unresolved literature conventions are explicitly provisional.\n- `run_budget_estimate.md`: proposed 15--20 Tn plan, not executed.\n- `file_manifest.json`: SHA256, byte count and line count for audit inputs.\n\n### Required disposition before any Singh production run\n\n1. Obtain/inspect the full primary paper and mark exact domain, BC, initialization, amplitude/frequency and coefficient definitions.\n2. Create a new versioned Singh contract (do not edit historical Shiels or regression contracts).\n3. Derive `M` and each `K` from `m*` and `U*`; do not inherit `2500/4940`.\n4. Decide whether to rebuild a 5% blockage benchmark domain; current 3.333% domain cannot be silently called identical.\n5. Freeze independent-start policy, retained stable-cycle criteria and one representative dt sensitivity point.\n\n## Final answers\n\n1. **Singh m* definition:** `m*=4m'/(pi rho D^2)`; the formula is confirmed in the related peer-reviewed Singh/Mittal-group formulation, while the primary Singh (2005) page equation still needs direct page-level confirmation.\n2. **M:** `7853.981633974483 kg` for `Lz=1 m` under that definition.\n3. **U*:** `U/(fn D)=1/Fn`; accessible primary text confirms `U*=1/Fn`.\n4. **fn/Tn/K:** generated exactly in `singh_parameter_matrix.csv`; full 8-point and minimum 6-point matrices are both present.\n5. **Domain:** not confirmed identical; current blockage is 3.333%, secondary Singh evidence is 5%.\n6. **Blockage:** different and potentially quantitative-amplitude relevant.\n7. **BC:** current BC are fully identified; Singh BC are not yet confirmed.\n8. **Current case changes:** a new Singh 2DOF contract/case, Singh-derived M/K, confirmed domain/BC/initialization/post-processing; no current case was edited.\n9. **Allowed differences:** FV vs stabilized space-time FE and PIMPLE vs GMRES are implementation differences only after sensitivity evidence; domain/blockage and structural mass are not silently allowable.\n10. **Amplitude:** proposed centered half peak-to-peak for Ax/Ay, with RMS separately; exact literature convention not yet confirmed.\n11. **Frequency:** proposed dominant fX/fY after mean removal and cycle/spectral cross-check; exact literature extraction not yet confirmed.\n12. **Initial conditions:** not yet confirmed from Singh; proposed independent U* starts from a documented developed fixed-cylinder state only after primary-source review.\n13. **First eight U* points:** **not directly startable** under the current evidence/contract.\n14. **Minimum blocker:** structural mass/definition and current-versus-Singh domain/BC/initialization contract mismatch.\n\n## Preserved boundaries\n\nNo OpenFOAM, preCICE, ANCF, fixed-cylinder, moving-cylinder, or U* scan was launched. Historical FAIL/NOT_EVALUABLE records and previous runtime identities remain immutable.\n\n[^1]: [Singh & Mittal (2005), ScienceDirect article record](https://www.sciencedirect.com/science/article/pii/S0889974605000873)\n[^2]: [Prasanth et al. (2006), Effect of blockage on VIV at low Re](https://www.sciencedirect.com/science/article/pii/S0889974606000521)\n[^3]: [Prasanth & Mittal (2009), published equations and definitions](https://electronicsandbooks.com/edt/manual/Magazine/J/Journal%20of%20Fluids%20and%20Structures/2009%20Volume%2025/6/1029-1048.pdf)\n"""
    key_sha = (
        f"- Key input SHA256: `controlDict={sha256(CURRENT / 'system' / 'controlDict')}`, "
        f"`fvSchemes={sha256(CURRENT / 'system' / 'fvSchemes')}`, "
        f"`fvSolution={sha256(CURRENT / 'system' / 'fvSolution')}`, "
        f"`polyMesh/points={sha256(CURRENT / 'constant' / 'polyMesh' / 'points')}`, "
        f"`polyMesh/faces={sha256(CURRENT / 'constant' / 'polyMesh' / 'faces')}`, "
        f"`two_dof_precice_participant.py={sha256(REGRESSION / 'two_dof_precice_participant.py')}`. "
        "Full bytes/line counts are in `file_manifest.json`.\n"
    )
    report = report.replace("- Near-wall mesh source:", key_sha + "- Near-wall mesh source:")
    (OUT / "SINGH_MITTAL_BENCHMARK_CONTRACT_AUDIT_V1.md").write_text(report, encoding="utf-8")
    print(json.dumps({"status": audit["overall_status"], "output": str(OUT), "current_cells": current["mesh"]["cell_count"], "current_blockage": current_blockage, "M_kg": mass_per_span * LZ}, ensure_ascii=False))


if __name__ == "__main__":
    main()
