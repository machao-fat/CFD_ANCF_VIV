"""Read-only parsers and gates for cross-slice force independence evidence."""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Iterable

NUMBER = re.compile(r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_forces(path: Path) -> dict[float, dict[str, tuple[float, float, float]]]:
    """Return raw pressure, viscous and summed force by 1 ns display tick."""
    result: dict[float, dict[str, tuple[float, float, float]]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"):
            continue
        values = [float(value) for value in NUMBER.findall(line)]
        if len(values) < 13:
            raise ValueError(f"unparseable forces row in {path}: {line!r}")
        pressure = tuple(values[1:4])
        viscous = tuple(values[4:7])
        result[round(values[0], 9)] = {
            "pressure_N": pressure,
            "viscous_N": viscous,
            "total_N": tuple(pressure[i] + viscous[i] for i in range(3)),
        }
    if not result:
        raise ValueError(f"no force rows in {path}")
    return result


def force_samples(paths: Iterable[Path], times_s: Iterable[float]) -> dict[str, object]:
    parsed = [parse_forces(path) for path in paths]
    result: dict[str, object] = {}
    for time_s in times_s:
        key = round(float(time_s), 9)
        rows = [item.get(key) for item in parsed]
        if any(row is None for row in rows):
            raise ValueError(f"force sample {time_s} s is absent")
        assert all(row is not None for row in rows)
        fy = [row["total_N"][1] for row in rows]
        result[f"{time_s:g}"] = {
            "pressure_N": rows[0]["pressure_N"],
            "viscous_N": rows[0]["viscous_N"],
            "total_N": rows[0]["total_N"],
            "Fy_pair_differences_N": {"0-1": fy[0] - fy[1], "0-2": fy[0] - fy[2], "1-2": fy[1] - fy[2]},
        }
    return result


def exact_file_equality(paths: Iterable[Path]) -> bool:
    items = [path.read_bytes() for path in paths]
    return bool(items) and all(item == items[0] for item in items[1:])


def precice_binding(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    participant = re.search(r'participant\s+(Fluid_\d{4})\s*;', text)
    mesh = re.search(r'\bmesh\s+(\S+)\s*;', text)
    read_data = re.search(r'readData\s*\(([^)]*)\)', text)
    write_data = re.search(r'writeData\s*\(([^)]*)\)', text)
    point = re.search(r'namePointDisplacement\s+(\S+)\s*;', text)
    cell = re.search(r'nameCellDisplacement\s+(\S+)\s*;', text)
    if not all((participant, mesh, read_data, write_data, point, cell)):
        raise ValueError(f"incomplete preCICE dictionary: {path}")
    return {
        "participant": participant.group(1), "mesh": mesh.group(1),
        "read_data": read_data.group(1).strip(), "write_data": write_data.group(1).strip(),
        "point_displacement_field": point.group(1), "cell_displacement_field": cell.group(1),
    }


def xml_pair(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    sockets = re.search(r'<m2n:sockets acceptor="(Structure_\d{4})" connector="(Fluid_\d{4})"', text)
    displacement = re.search(r'<exchange data="Displacement" mesh="Structure-Mesh" from="(Structure_\d{4})" to="(Fluid_\d{4})"', text)
    force = re.search(r'<exchange data="Force" mesh="Structure-Mesh" from="(Fluid_\d{4})" to="(Structure_\d{4})"', text)
    if not all((sockets, displacement, force)):
        raise ValueError(f"incomplete preCICE XML: {path}")
    return {"socket_structure": sockets.group(1), "socket_fluid": sockets.group(2),
            "displacement_from": displacement.group(1), "displacement_to": displacement.group(2),
            "force_from": force.group(1), "force_to": force.group(2)}


def synthetic_channel_probe(pairs: Iterable[dict[str, str]]) -> dict[str, object]:
    """Exercise the declared routing graph with intentionally distinct values.

    This is a configuration-level probe: it detects cross-indexing or broadcast
    in the declared pair graph without starting CFD or modifying a runtime.
    """
    items = list(pairs)
    displacement_out = {f"Structure_{index:04d}": value for index, value in enumerate((1.0, 0.0, -1.0))}
    expected_fluid = {f"Fluid_{index:04d}": value for index, value in enumerate((1.0, 0.0, -1.0))}
    force_out = {f"Fluid_{index:04d}": value for index, value in enumerate((1.0, 2.0, 3.0))}
    expected_structure = {f"Structure_{index:04d}": value for index, value in enumerate((1.0, 2.0, 3.0))}
    received_fluid: dict[str, float] = {}
    received_structure: dict[str, float] = {}
    for pair in items:
        received_fluid[pair["displacement_to"]] = displacement_out[pair["displacement_from"]]
        received_structure[pair["force_to"]] = force_out[pair["force_from"]]
    passed = received_fluid == expected_fluid and received_structure == expected_structure and len(items) == 3
    return {"status": "pass" if passed else "fail", "displacement_written_by_structure_m": {"Structure_0000": 1.0, "Structure_0001": 0.0, "Structure_0002": -1.0},
            "displacement_received_by_fluid_m": received_fluid, "force_written_by_fluid_N": {"Fluid_0000": 1.0, "Fluid_0001": 2.0, "Fluid_0002": 3.0},
            "force_received_by_structure_N": received_structure,
            "scope": "declared preCICE pair graph; not a CFD run"}


def motion_path_status(binding: dict[str, str], dynamic_mesh_dict: Path, final_point_field: Path, final_mesh_points: Path) -> dict[str, object]:
    dynamic = dynamic_mesh_dict.read_text(encoding="utf-8", errors="replace")
    requires_point = "displacementLaplacian" in dynamic
    bound = binding["point_displacement_field"] == "pointDisplacement"
    return {"motion_solver": "displacementLaplacian" if requires_point else "other", "point_displacement_bound": bound,
            "final_pointDisplacement_present": final_point_field.is_file(), "final_polyMesh_points_present": final_mesh_points.is_file(),
            "status": "pass" if (not requires_point or bound) else "fail"}


def force_object_status(control_dict: Path) -> dict[str, object]:
    text = control_dict.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'cylinderForces\s*\{(.*?)\}', text)
    if not match:
        raise ValueError(f"cylinderForces is absent: {control_dict}")
    block = match.group(1)
    patches = re.search(r'patches\s*\(([^)]*)\)', block)
    if not patches:
        raise ValueError(f"forces patches are absent: {control_dict}")
    return {"function_object": "cylinderForces", "patches": patches.group(1).split(),
            "rho": "rhoInf" if "rho rhoInf" in block else "other", "rhoInf": 1000.0 if "rhoInf 1000" in block else None,
            "CofR": "(0 0 0)" if "CofR (0 0 0)" in block else "other", "region": "default region0 (not explicitly overridden)",
            "status": "pass" if patches.group(1).split() == ["cylinder"] else "fail"}


def finite_force_differences(paths: Iterable[Path]) -> float:
    records = [parse_forces(path) for path in paths]
    common = set.intersection(*(set(item) for item in records))
    if not common:
        raise ValueError("no common force times")
    maximum = 0.0
    for time_s in common:
        values = [item[time_s]["total_N"][1] for item in records]
        maximum = max(maximum, max(values) - min(values))
    return maximum if math.isfinite(maximum) else math.inf


def sensitivity_evidence_status(*, geometry_distinct: bool, u_distinct: bool, p_distinct: bool, fy_difference_N: float) -> str:
    """Fail closed unless a controlled CFD run proves all causal links."""
    return "pass" if geometry_distinct and u_distinct and p_distinct and math.isfinite(fy_difference_N) and abs(fy_difference_N) > 0.0 else "fail"
