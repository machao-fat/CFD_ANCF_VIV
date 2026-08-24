"""Fresh medium-grid cases with separated warm-up and production output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.coupling.stage4e_target_re_pilot_v2.case_generator_v2 import (
    DOMAIN_EXTENTS,
    MESH_LEVELS,
    _block_mesh_text,
    _fv_schemes,
    _fv_solution,
    _header,
    _k_field,
    _momentum_transport,
    _p_field,
    _physical_properties,
    _set_fields,
    _u_field,
    _omega_field,
    _nut_field,
    _fresh_dir,
    _write_text,
)
from src.coupling.stage4e_target_re_pilot_v2.identity_v2 import D, NU, RHO, finite, sha256_file, sha256_json


PROJECT = Path(__file__).resolve().parents[3]
CASE_ROOT = PROJECT / "cases" / "openfoam" / "stage4e_target_re_fixed_cylinder_v2_1"
FIELD_WRITE_INTERVAL_STEPS = 1000
FORCE_WRITE_INTERVAL_STEPS = 5
WARMUP_END_S = 0.2
PRODUCTION_DT_S = 4.0e-4
MAX_CO = 0.5
HARD_CFL = 0.8


def _fmt(value: float) -> str:
    return f"{float(value):.15g}"


def _functions(model: str, *, U: float, force_interval: int, include_yplus: bool) -> str:
    yplus = "" if not include_yplus else f'''    yPlus
    {{
        type yPlus;
        libs ("libfieldFunctionObjects.so");
        patches (cylinder);
        writeControl timeStep;
        writeInterval 1;
    }}
'''
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
        Aref {_fmt(D * D)};
        writeControl timeStep;
        writeInterval {int(force_interval)};
        log yes;
    }}
{yplus}}}
'''


def control_dict_v2_1(
    U: float,
    *,
    end_time: float,
    model: str,
    direction: int = 1,
    mode: str = "warmup",
    include_yplus: bool = False,
    force_interval: int = FORCE_WRITE_INTERVAL_STEPS,
    field_interval: int = FIELD_WRITE_INTERVAL_STEPS,
) -> str:
    if mode not in {"warmup", "production", "io_benchmark_old", "io_benchmark_new"}:
        raise ValueError(mode)
    if mode == "warmup":
        start_from = "startTime"
        start_time = 0.0
        dt = 1.0e-5
        adjust = "yes"
        max_delta = "maxDeltaT 0.0004;"
        field_control = "runTime"
        field_interval_text = "0.2"
    else:
        start_from = "latestTime"
        start_time = WARMUP_END_S
        dt = PRODUCTION_DT_S
        adjust = "no"
        max_delta = ""
        field_control = "timeStep"
        field_interval_text = str(int(field_interval))
    if mode.startswith("io_benchmark"):
        start_from = "startTime"
        start_time = 0.0
        # The 1000-step I/O comparison must not be contaminated by the known
        # startup spike of the old 0.0004 s direct-start protocol.
        dt = 1.0e-4
        adjust = "no"
        max_delta = ""
        field_control = "timeStep"
        field_interval_text = "1000"
    signed = float(direction) * abs(float(U))
    return _header("dictionary", "controlDict", '"system"') + f'''application pimpleFoam;
startFrom {start_from};
startTime {_fmt(start_time)};
stopAt endTime;
endTime {_fmt(end_time)};
deltaT {_fmt(dt)};
adjustTimeStep {adjust};
maxCo {_fmt(MAX_CO)};
{max_delta}
writeControl {field_control};
writeInterval {field_interval_text};
purgeWrite 0;
writeFormat ascii;
writePrecision 16;
writeCompression off;
timeFormat general;
timePrecision 16;
runTimeModifiable false;
{_functions(model, U=U, force_interval=force_interval, include_yplus=include_yplus)}
// v2.1 mode={mode}, model={model}, direction={direction:+d}, U={_fmt(signed)},
// field_write_interval={field_control}:{field_interval_text}, force_write_interval={force_interval},
// Aref={_fmt(D * D)}, b_mesh={_fmt(D)}, production_dt={_fmt(PRODUCTION_DT_S)}
'''


def _write_case_metadata(case_dir: Path, meta: dict[str, Any]) -> dict[str, Any]:
    files = {str(path.relative_to(case_dir)).replace("\\", "/"): sha256_file(path) for path in sorted(case_dir.rglob("*")) if path.is_file()}
    meta = dict(meta)
    meta["case_file_hashes_before_metadata"] = files
    meta["case_identity_sha256"] = sha256_json({key: meta[key] for key in ("model", "mesh_level", "domain", "U_mps", "epsilon", "direction", "mode", "mesh_geometry", "case_file_hashes_before_metadata")})
    _write_text(case_dir / "case_metadata.json", json.dumps(finite(meta), ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return finite(meta)


def generate_case(
    case_dir: Path,
    *,
    model: str,
    mesh_level: str = "medium",
    domain: str = "baseline",
    U: float,
    epsilon: float = 0.005,
    direction: int = 1,
    mode: str = "warmup",
    end_time: float = WARMUP_END_S,
    include_yplus: bool = False,
    force_interval: int = FORCE_WRITE_INTERVAL_STEPS,
    field_interval: int = FIELD_WRITE_INTERVAL_STEPS,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _fresh_dir(case_dir)
    if model not in {"laminar", "kOmegaSST"} or mesh_level not in MESH_LEVELS or domain not in DOMAIN_EXTENTS:
        raise ValueError("unsupported case parameter")
    for rel in ("0", "constant", "system"):
        (case_dir / rel).mkdir()
    block_text, mesh_meta = _block_mesh_text(mesh_level, domain)
    _write_text(case_dir / "system" / "blockMeshDict", block_text)
    _write_text(case_dir / "system" / "controlDict", control_dict_v2_1(U, end_time=end_time, model=model, direction=direction, mode=mode, include_yplus=include_yplus, force_interval=force_interval, field_interval=field_interval))
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
    meta = {
        "schema_version": "stage4e-b2-a-v2.1-case-0.1.0",
        "model": model,
        "mesh_level": mesh_level,
        "domain": domain,
        "mode": mode,
        "U_mps": direction * abs(float(U)),
        "U_abs_mps": abs(float(U)),
        "Re": abs(float(U)) * D / NU,
        "epsilon": float(epsilon),
        "direction": int(direction),
        "inlet_patch": "left" if direction > 0 else "right",
        "outlet_patch": "right" if direction > 0 else "left",
        "mesh_geometry": mesh_meta,
        "diameter_m": D,
        "b_mesh_m": D,
        "Aref_OF_m2": D * D,
        "force_output_total_N": True,
        "slice_length_used": False,
        "metadata": metadata or {},
    }
    return _write_case_metadata(case_dir, meta)


def switch_to_production(case_dir: Path, *, model: str, U: float, end_time: float, force_interval: int = FORCE_WRITE_INTERVAL_STEPS, field_interval: int = FIELD_WRITE_INTERVAL_STEPS) -> dict[str, Any]:
    text = control_dict_v2_1(U, end_time=end_time, model=model, direction=1, mode="production", include_yplus=False, force_interval=force_interval, field_interval=field_interval)
    _write_text(case_dir / "system" / "controlDict", text)
    return {"controlDict_sha256": sha256_file(case_dir / "system" / "controlDict"), "mode": "production", "end_time_s": float(end_time), "production_dt_s": PRODUCTION_DT_S, "force_write_interval_steps": int(force_interval), "field_write_interval_steps": int(field_interval), "yplus_in_control_dict": False}


def case_freshness(case_dir: Path) -> dict[str, Any]:
    forbidden = ["postProcessing", "processor0", "processor1", "log.pimpleFoam", "log.checkMesh", "log.blockMesh", "checkpoint"]
    found = [name for name in forbidden if (case_dir / name).exists()]
    numeric = [p.name for p in case_dir.iterdir()] if case_dir.exists() else []
    numeric = [name for name in numeric if name not in {"0", "constant", "system", "case_metadata.json"} and name.replace(".", "", 1).isdigit()]
    links = [str(p) for p in case_dir.rglob("*") if p.is_symlink()] if case_dir.exists() else []
    return finite({"case_relative_name": case_dir.name, "fresh_case_created": case_dir.is_dir(), "forbidden_existing_before_run": found, "numeric_time_directories_before_run": numeric, "unexpected_symlinks": links, "passed": case_dir.is_dir() and (case_dir / "0").is_dir() and not found and not numeric and not links})
