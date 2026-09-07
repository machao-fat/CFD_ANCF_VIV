"""Frozen V4 evaluator: auxiliary PCG work is observable but not a validity proxy."""
from __future__ import annotations
import math
from typing import Any, Mapping
from coupling.openfoam_numerical_quality_contract_v2.audit import AuditError

def _n(value: object, name: str) -> float:
    try: answer=float(value)
    except (TypeError, ValueError) as exc: raise AuditError(f"{name} is not numeric") from exc
    if not math.isfinite(answer): raise AuditError(f"{name} is non-finite")
    return answer

def _allowed(rule: Mapping[str, object], initial: float) -> float:
    return max(_n(rule['absolute_tolerance'],'absolute tolerance'), _n(rule['relative_tolerance'],'relative tolerance')*initial)

def evaluate_quality_v4(audit: Mapping[str,Any], contract: Mapping[str,Any]) -> dict[str,Any]:
    records=audit.get('time_records')
    if not isinstance(records,list) or not records: raise AuditError('missing time records')
    groups=contract['solve_groups']; lookup={field:name for name,rule in groups.items() for field in rule['fields']}
    failures=[]; warnings=[]; classifications=[]; max_final={}; max_co=0.; max_cont=0.
    for rec in records:
        time=_n(rec['time_s'],'time')
        # A log cut off by another participant is not a completed physical
        # solve.  Its last p line is an intermediate correction, not a PIMPLE
        # terminal residual.  Preserve a fail-closed quality result, but do
        # not mislabel the intermediate line as a terminal numerical failure.
        if not bool(rec.get('physical_timestep_completed', False)):
            failures.append(f'incomplete physical timestep at {time}')
            classifications.append({'time_s': time, 'group': 'timestep_completion', 'solver_validity': 'fail'})
            continue
        if rec.get('courant_max') is None: failures.append(f'missing Courant at {time}')
        else: max_co=max(max_co,_n(rec['courant_max'],'Courant'))
        cont=rec.get('continuity')
        if not isinstance(cont,list) or not cont: failures.append(f'missing continuity at {time}')
        else: max_cont=max(max_cont,max(abs(_n(v['global'],'continuity')) for v in cont))
        solved={str(x['field']) for x in rec['solves']}
        for group,rule in groups.items():
            for expected in rule['fields']:
                if expected not in solved: failures.append(f'missing {group} solve {expected} at {time}')
        for solve in rec['solves']:
            field=str(solve['field']); group=lookup.get(field)
            if group is None:
                failures.append(f'unclassified solve {field} at {time}'); continue
            rule=groups[group]; initial=_n(solve['initial_residual'],'initial residual'); final=_n(solve['final_residual'],'final residual'); it=int(solve['linear_iterations'])
            max_final[field]=max(max_final.get(field,0.),final)
            trivial=group=='mesh_motion_auxiliary' and initial==0 and final==0 and it==0
            converged=trivial or (it>0 and final<=_allowed(rule,initial))
            if group!='mesh_motion_auxiliary' and not trivial: converged=converged and it<=int(rule['max_iterations'])
            if not converged: failures.append(f'{group} solver validity failure for {field} at {time}')
            if group=='mesh_motion_auxiliary' and it>int(rule['iteration_warning_threshold']): warnings.append(f'{field} iterations {it} at {time}')
            classifications.append({'time_s':time,'field':field,'group':group,'initial_residual':initial,'final_residual':final,'linear_iterations':it,'solver_validity':'pass' if converged else 'fail','efficiency_warning':group=='mesh_motion_auxiliary' and it>int(rule['iteration_warning_threshold'])})
        terminals=rec['metrics']['field_terminal_final_residual']
        for field,limit in contract['primary_terminal_residual_limit'].items():
            if field not in terminals: failures.append(f'missing primary terminal {field} at {time}')
            elif _n(terminals[field],f'terminal {field}')>_n(limit,f'terminal limit {field}'): failures.append(f'primary terminal {field} exceeds limit at {time}')
    if max_co>_n(contract['courant_max_limit'],'Courant limit'): failures.append('Courant quality failure')
    if max_cont>_n(contract['continuity_global_abs_limit'],'continuity limit'): failures.append('continuity quality failure')
    return {'schema_version':'openfoam-numerical-quality-evidence-v4','status':'pass' if not failures else 'fail','failures':failures,'warnings':warnings,'classifications':classifications,'max_final_residual_by_field':max_final,'max_courant':max_co,'max_abs_continuity_global':max_cont,'observability_completeness':'pass' if not any('missing' in x or 'unclassified' in x for x in failures) else 'fail','linear_solver_validity':'pass' if not any('solver validity' in x for x in failures) else 'fail','auxiliary_efficiency_status':'warning' if warnings else 'pass','pimple_terminal_convergence':'pass' if not any('primary terminal' in x for x in failures) else 'fail'}
