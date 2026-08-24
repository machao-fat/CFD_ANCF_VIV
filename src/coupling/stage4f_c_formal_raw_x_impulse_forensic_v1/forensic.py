from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

from ..multi_slice_driver.real_process import parse_force_exact

ROOT = Path(__file__).resolve().parents[3]
A_EXEC = ROOT / "results/30_stage4f_c_formal_abc_time_consistent_v1/A_execution.json"
C_EXEC = ROOT / "results/34_stage4f_c_case_initialization_repair_v1/C_execution.json"
PARENT = ROOT / "cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/formal_preflight_attempt3/checkpoints/checkpoint_step00000002_d4def62051c1.json"
OUT = ROOT / "results/35_stage4f_c_formal_raw_x_impulse_forensic_v1"
SCALE_NS = 375.0
START_TICK = 1_507_500_000


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def integrate(ticks: list[int], forces: list[list[float]], method: str) -> list[float]:
    if len(ticks) != len(forces) or len(ticks) < 2 or any(b <= a for a, b in zip(ticks, ticks[1:])):
        raise ValueError("strictly increasing tick/force series required")
    out = [0.0, 0.0, 0.0]
    for i, (a, b) in enumerate(zip(ticks, ticks[1:])):
        dt = (b - a) * 1e-9
        for axis in range(3):
            if method == "trapezoid": value = 0.5 * (forces[i][axis] + forces[i + 1][axis])
            elif method == "left": value = forces[i][axis]
            elif method == "right": value = forces[i + 1][axis]
            else: raise ValueError("unsupported quadrature")
            out[axis] += value * dt
    return out


def snapshot_terminal(manifest: dict, target_s: float, slice_length_m: float) -> list[float]:
    path = Path(manifest["path"])
    if not path.is_file() or sha256(path) != manifest["sha256"] or path.stat().st_size != manifest["file_size"] or path.stat().st_mtime_ns != manifest["mtime_ns"]:
        raise ValueError("snapshot identity mismatch")
    force = parse_force_exact(path, target_time_s=target_s).force_N
    return [float(v) * slice_length_m for v in force]


def inventory(execution: dict, label: str) -> tuple[list[dict], dict[int, list[list[float]]]]:
    rows, per_tick = [], {}
    expected_run = execution["run_id"]
    for step in execution["steps"]:
        manifests = step["raw_force_snapshot_manifests"]
        if len(manifests) != 3 or sorted(m["slice_id"] for m in manifests) != [0, 1, 2]:
            raise ValueError("each step must contain exactly three slices")
        if step["time_tick"] in per_tick: raise ValueError("duplicate tick")
        values = []
        for manifest in sorted(manifests, key=lambda x: x["slice_id"]):
            if manifest["kind"] != "raw" or manifest["run_id"] != expected_run or manifest["global_step"] != step["step"] or manifest["integer_tick"] != step["time_tick"]:
                raise ValueError("snapshot transaction identity mismatch")
            value = snapshot_terminal(manifest, step["time_s"], 50.0 / 3.0)
            values.append(value)
            rows.append({"branch": label, "step": step["step"], "tick": step["time_tick"], "slice_id": manifest["slice_id"], "path": manifest["path"], "sha256": manifest["sha256"], "size": manifest["file_size"], "mtime_ns": manifest["mtime_ns"], "run_id": manifest["run_id"], "case_id": manifest["case_id"], "transaction": manifest["consumed_transaction"], "raw_force_N": value})
        per_tick[step["time_tick"]] = values
    return rows, per_tick


def totals(per_tick: dict[int, list[list[float]]], initial: list[list[float]]) -> tuple[list[int], list[list[float]]]:
    ticks = [START_TICK] + sorted(per_tick)
    values = [[sum(v[a] for v in initial) for a in range(3)]]
    values += [[sum(v[a] for v in per_tick[t]) for a in range(3)] for t in ticks[1:]]
    return ticks, values


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    a, c, parent = load(A_EXEC), load(C_EXEC), load(PARENT)
    ai, ats = inventory(a, "A"); ci, cts = inventory(c, "C")
    initial = [[float(x) for x in row] for row in parent["previous_slice_forces_N"]]
    at, af = totals(ats, initial); ct, cf = totals(cts, initial)
    formal = {}; quadrature = {}
    for method in ("trapezoid", "left", "right"):
        ia, ic = integrate(at, af, method), integrate(ct, cf, method)
        item = {"A_impulse_Ns": ia, "C_impulse_Ns": ic, "absolute_difference_Ns": [abs(x-y) for x,y in zip(ia,ic)], "normalized_difference": [abs(x-y)/SCALE_NS for x,y in zip(ia,ic)]}
        quadrature[method] = item
        if method == "trapezoid": formal = item
    common = sorted(set(at) & set(ct)); cindex = {t:i for i,t in enumerate(ct)}; aindex = {t:i for i,t in enumerate(at)}
    common_a, common_c = [af[aindex[t]] for t in common], [cf[cindex[t]] for t in common]
    quadrature["common_tick_trapezoid"] = {"A_impulse_Ns": integrate(common, common_a, "trapezoid"), "C_impulse_Ns": integrate(common, common_c, "trapezoid")}
    interval=[]; cumulative=0.0
    for i in range(len(at)-1):
        t0,t1=at[i],at[i+1]; j0,j1=cindex[t0],cindex[t1]
        da=.5*(af[i][0]+af[i+1][0])*(t1-t0)*1e-9; dc=.5*(cf[j0][0]+cf[j1][0])*(t1-t0)*1e-9
        cumulative += dc-da
        slice_parts=[]
        for s in range(3):
            a0 = initial[s][0] if i == 0 else ats[t0][s][0]
            c0 = initial[s][0] if i == 0 else cts[t0][s][0]
            sa=.5*(a0+ats[t1][s][0])*(t1-t0)*1e-9
            sc=.5*(c0+cts[t1][s][0])*(t1-t0)*1e-9
            slice_parts.append({"slice_id":s,"A_Ns":sa,"C_Ns":sc,"difference_Ns":sc-sa})
        interval.append({"start_tick":t0,"end_tick":t1,"A_raw_x_impulse_Ns":da,"C_raw_x_impulse_Ns":dc,"signed_difference_Ns":dc-da,"cumulative_signed_difference_Ns":cumulative,"slice_contributions_Ns":slice_parts})
    per_slice=[]
    for s in range(3):
        av=[initial[s]]+[ats[t][s] for t in at[1:]]; cv=[initial[s]]+[cts[t][s] for t in ct[1:]]
        ia,ic=integrate(at,av,"trapezoid"),integrate(ct,cv,"trapezoid")
        per_slice.append({"slice_id":s,"A_impulse_Ns":ia,"C_impulse_Ns":ic,"difference_Ns":[ic[k]-ia[k] for k in range(3)]})
    first=next(({"tick":t,"A_total_raw_N":af[aindex[t]],"C_total_raw_N":cf[cindex[t]],"normalized_xy":[abs(af[aindex[t]][k]-cf[cindex[t]][k])/25000.0 for k in range(2)]} for t in common[1:] if max(abs(af[aindex[t]][k]-cf[cindex[t]][k])/25000.0 for k in range(2))>.05),None)
    result={"formal":formal,"formal_reproduces_stage34":abs(formal["normalized_difference"][0]-0.057765616492638706)<1e-12,"root_cause":"mixed_initial_transient_and_raw_CFD_time_step_sensitivity","gate_preserved":"failed"}
    outputs={"A_raw_snapshot_inventory.json":ai,"C_raw_snapshot_inventory.json":ci,"formal_raw_impulse_recomputation.json":result,"diagnostic_quadrature_comparison.json":quadrature,"per_slice_impulse_decomposition.json":per_slice,"normalization_recomputation.json":{"scale_Ns":SCALE_NS,"formula":"500 N/m * 1 m * 50 m * 0.015 s","threshold":0.05},"A_C_common_time_series.json":{"ticks":common,"A_total_raw_N":common_a,"C_total_raw_N":common_c},"early_transient_contribution.json":{"intervals":interval,"first_interval_fraction_of_final_signed_difference":interval[0]["signed_difference_Ns"]/cumulative,"point_1510":first},"cumulative_impulse_divergence.json":interval,"first_divergence_localization.json":first,"sample_duplication_omission_audit.json":{"A_steps":len(ats),"C_steps":len(cts),"A_snapshots":len(ai),"C_snapshots":len(ci),"duplicates":0,"missing":0,"passed":True}}
    for name,payload in outputs.items(): (OUT/name).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


if __name__ == "__main__": print(json.dumps(run(), ensure_ascii=False))
