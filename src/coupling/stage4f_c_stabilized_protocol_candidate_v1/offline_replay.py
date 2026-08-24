"""使用已保存 repair2/D1 证据回放 0.3.0 candidate。"""
from __future__ import annotations
import math
from typing import Any, Mapping, Sequence
from .protocol import ALPHA, CD_LIMIT, VELOCITY_LIMIT, CFL_LIMIT

def replay(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    previous: list[float] | None = None
    accepted=[]; rejected=None
    for index,row in enumerate(rows):
        cds=[float(v) for v in row["Cd"]]
        velocity=float(row["velocity_error"]); cfl=float(row["max_cfl"])
        if any(not math.isfinite(v) for v in (*cds,velocity,cfl)): raise ValueError("non-finite replay evidence")
        reasons=[]
        if max(abs(v) for v in cds)>CD_LIMIT: reasons.append("raw_abs_Cd")
        if abs(velocity)>VELOCITY_LIMIT: reasons.append("velocity_consistency")
        if cfl>=CFL_LIMIT: reasons.append("CFL")
        if reasons:
            rejected={"index":index,"step":int(row["step"]),"reasons":reasons,"raw_Cd":cds,"velocity_error":velocity,"max_cfl":cfl,"commit":False}
            break
        if previous is None: previous=[0.0]*len(cds)
        applied=[(1-ALPHA)*old+ALPHA*raw for old,raw in zip(previous,cds)]
        accepted.append({"index":index,"step":int(row["step"]),"raw_Cd":cds,"applied_Cd":applied,"commit":True})
        previous=applied
    return {"accepted_steps":len(accepted),"accepted":accepted,"first_rejected":rejected,
            "alternating_suppression_proven":False,"probe_authorized":rejected is None}

def repair2_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    steps=summary["branches"]["A"]["steps"]
    return [{"step":x["step"],"Cd":[f["Cd"] for f in x["force_audit"]],
             "velocity_error":max(g["committed_predictor_velocity_gap_over_U"] for g in x["geometry_audit"]),
             "max_cfl":x["log_audit"]["max_cfl"]} for x in steps]

def d1_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{"step":x["step"],"Cd":x["Cd"],"velocity_error":x["velocity_consistency_error"],"max_cfl":x["max_cfl"]} for x in summary["steps"]]
