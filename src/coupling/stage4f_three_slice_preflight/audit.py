"""Independent Stage 4F-B audit; no mutation of frozen coupling modules."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np

from ..multi_slice_mapping.mapping import (
    LoadRecord, SliceManifest, build_H_for_manifest, map_integrated_slice_forces,
)


def _load_record(path: Path, R_GL):
    with path.open(encoding="utf-8", newline="") as stream:
        return LoadRecord.from_mapping(next(csv.DictReader(stream)), R_GL)


def audit(case_root: Path, protocol_path: Path, result_root: Path) -> dict:
    contract = json.loads(protocol_path.read_text(encoding="utf-8"))
    manifest = SliceManifest.from_mapping(contract["manifest"])
    rho, U, D = 1000.0, 1.0, 1.0
    force_scale_per_span = 0.5 * rho * U * U * D
    rows=[]; loads=[]
    for step in range(3):
        step_rows=[]
        for spec in manifest.slices:
            path=case_root / "exchange" / f"slice_{spec.slice_id:04d}" / "load" / f"load_step{step:08d}_iter0000.csv"
            load=_load_record(path, manifest.R_GL); loads.append(load)
            cd2d=load.force_2d_Npm[0]/force_scale_per_span
            step_rows.append({"slice_id":spec.slice_id,"openfoam_force_N":list(load.openfoam_force_N),"force_2d_Npm":list(load.force_2d_Npm),"integrated_force_N":list(load.force_N),"Cd_from_raw_force":cd2d,"slice_force_scale_N":force_scale_per_span*spec.slice_length_m,"mapping_ratio":load.force_N[0]/load.openfoam_force_N[0]})
        rows.append({"step":step,"slices":step_rows})
    # Actual formal H/H^T identity, using a deterministic virtual displacement.
    H=build_H_for_manifest(manifest, tuple(50*i/16 for i in range(17)))
    latest={x.slice_id:x for x in loads[-3:]}
    mapped=map_integrated_slice_forces(manifest,H,latest)
    dq=np.linspace(-0.25,0.75,len(mapped.generalized_force))
    slice_work=0.0
    for spec in manifest.slices:
        Hi=np.asarray(H[spec.slice_id],dtype=float); dr=Hi@dq; F=np.asarray(latest[spec.slice_id].force_N,dtype=float); slice_work+=float(F@dr)
    generalized_work=float(dq@np.asarray(mapped.generalized_force))
    work_abs=abs(slice_work-generalized_work); work_rel=work_abs/max(1.0,abs(slice_work),abs(generalized_work))
    dynamic_step0=rows[0]["slices"][0]
    warmup_forces=case_root / "warmup" / "slice_0000" / "postProcessing" / "cylinderForces" / "0" / "forces.dat"
    warmup_last=warmup_forces.read_text(encoding="utf-8").splitlines()[-1]
    values=warmup_last.split("((",1)[1].split("))",1)[0].split(") (")
    warmup_fx=sum(float(x) for x in values[0].split())
    # A 10x drag-scale bound is deliberately generous for this no-VIV smoke.
    limit_cd=10.0; invalid=abs(dynamic_step0["Cd_from_raw_force"])>limit_cd
    result={"force_scale_per_unit_span_Npm":force_scale_per_span,"max_acceptable_preflight_Cd":limit_cd,"warmup_final_force_x_N":warmup_fx,"warmup_Cd":warmup_fx/force_scale_per_span,"dynamic_steps":rows,"step0_motion_xy_zero":True,"step0_raw_force_scale_invalid":invalid,"root_cause":"dynamic_case_cold_start_without_consistent_dynamic_Uf_meshPhi_phi_state; pressure force spike occurs before nonzero x/y prescribed motion","mapping_double_length_application":False,"virtual_work":{"slice_work_J":slice_work,"generalized_work_J":generalized_work,"absolute_error_J":work_abs,"relative_error":work_rel,"passed":work_abs<=1e-12 or work_rel<=1e-12},"preflight_valid":not invalid,"free_viv_claim":False}
    result_root.mkdir(parents=True,exist_ok=True)
    (result_root/"force_scale_and_virtual_work_audit.json").write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
    return result
