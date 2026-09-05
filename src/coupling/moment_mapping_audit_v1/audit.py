from __future__ import annotations

import math
from typing import Any, Sequence

from coupling.stage303_interface_mapping_repair_v1.canonical_projection import canonical_h_row, project_interface


def cross(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def dot(a: Sequence[float], b: Sequence[float], *, compensated: bool = False) -> float:
    values = [float(x)*float(y) for x, y in zip(a, b)]
    return math.fsum(values) if compensated else sum(values)


def norm(a: Sequence[float]) -> float:
    return math.sqrt(math.fsum(float(value)*float(value) for value in a))


def mapped_force(rows: Sequence[Sequence[float]], forces: Sequence[Sequence[float]], *, compensated: bool) -> tuple[float, ...]:
    ndof = len(rows[0]); result = []
    for dof in range(ndof):
        component = dof % 6
        terms = []
        if component in (0, 1, 2, 3, 4, 5):
            force_component = component if component < 3 else component - 3
            terms = [float(row[dof])*float(force[force_component]) for row, force in zip(rows, forces)]
        result.append(math.fsum(terms) if compensated else sum(terms))
    return tuple(result)


def rigid_rotation_virtual(q: Sequence[float], axis: Sequence[float], origin: Sequence[float]) -> tuple[float, ...]:
    result = [0.0]*len(q)
    for node in range(len(q)//6):
        base = 6*node; point = tuple(float(q[base+i])-float(origin[i]) for i in range(3)); slope = q[base+3:base+6]
        result[base:base+3] = cross(axis, point); result[base+3:base+6] = cross(axis, slope)
    return tuple(result)


def translation_virtual(q: Sequence[float], direction: Sequence[float]) -> tuple[float, ...]:
    result = [0.0]*len(q)
    for node in range(len(q)//6): result[6*node:6*node+3] = direction
    return tuple(result)


def audit(q: Sequence[float], forces: Sequence[Sequence[float]], *, positions_m: Sequence[float], length_m: float = 50.0,
          elements: int = 16, origin: Sequence[float] = (0.0, 0.0, 0.0), delta_q: Sequence[float] | None = None,
          compensated: bool = False) -> dict[str, Any]:
    zero = [0.0]*len(q); _, _, points, _ = project_interface(q, zero, slice_positions_m=positions_m, length_m=length_m, elements=elements)
    rows = [canonical_h_row(position, length_m=length_m, elements=elements) for position in positions_m]
    generalized = mapped_force(rows, forces, compensated=compensated)
    fluid_force = tuple(math.fsum(force[i] for force in forces) if compensated else sum(force[i] for force in forces) for i in range(3))
    mapped_force_result = tuple(dot(generalized, translation_virtual(q, direction), compensated=compensated) for direction in ((1,0,0),(0,1,0),(0,0,1)))
    fluid_moment = tuple(math.fsum(cross(tuple(point[i]-origin[i] for i in range(3)), force)[component] for point, force in zip(points, forces)) if compensated else sum(cross(tuple(point[i]-origin[i] for i in range(3)), force)[component] for point, force in zip(points, forces)) for component in range(3))
    mapped_moment = tuple(dot(generalized, rigid_rotation_virtual(q, axis, origin), compensated=compensated) for axis in ((1,0,0),(0,1,0),(0,0,1)))
    moment_abs = norm(tuple(a-b for a,b in zip(fluid_moment,mapped_moment)))
    contribution_scale = math.fsum(norm(tuple(point[i]-origin[i] for i in range(3)))*norm(force) for point,force in zip(points,forces))
    force_abs = norm(tuple(a-b for a,b in zip(fluid_force,mapped_force_result)))
    output: dict[str, Any] = {
        "fluid_resultant_N": fluid_force, "mapped_resultant_N": mapped_force_result,
        "fluid_moment_Nm": fluid_moment, "mapped_moment_Nm": mapped_moment,
        "force_error_absolute_N": force_abs, "force_error_normalized": force_abs/max(norm(fluid_force),contribution_scale/length_m,1.0),
        "moment_error_absolute_Nm": moment_abs, "moment_error_scale_Nm": contribution_scale,
        "moment_error_normalized_v2": moment_abs/max(contribution_scale,1.0),
        "legacy_z_relative_error": abs(fluid_moment[2]-mapped_moment[2])/max(abs(fluid_moment[2]),abs(mapped_moment[2]),1.0e-30),
        "generalized_force": generalized, "projected_points_m": points,
    }
    if delta_q is not None:
        def projected_delta(row: Sequence[float], component: int) -> float:
            terms = [float(row[index])*float(delta_q[index]) for index in range(len(row))
                     if index % 6 in (component, component + 3)]
            return math.fsum(terms) if compensated else sum(terms)
        slice_work = sum(dot(force, [projected_delta(row, component) for component in range(3)], compensated=compensated) for row,force in zip(rows,forces))
        mapped_work = dot(generalized,delta_q,compensated=compensated); error = abs(slice_work-mapped_work)
        output["virtual_work"] = {"slice_J":slice_work,"mapped_J":mapped_work,"absolute_error_J":error,"normalized_error":error/max(abs(slice_work),abs(mapped_work),1.0)}
    return output


def legacy_historical_z_condition(points: Sequence[Sequence[float]], forces: Sequence[Sequence[float]]) -> dict[str, float]:
    terms = [float(force[0])*(-float(point[1])) + float(force[1])*float(point[0]) for point,force in zip(points,forces)]
    moment = sum(terms); stable = math.fsum(terms); scale = math.fsum(abs(value) for value in terms)
    return {"naive_fluid_moment_z_Nm":moment,"compensated_fluid_moment_z_Nm":stable,"contribution_absolute_scale_Nm":scale,
            "cancellation_condition_number":scale/max(abs(stable),1.0e-30),"naive_vs_compensated_absolute_Nm":abs(moment-stable)}
