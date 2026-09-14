#!/usr/bin/env python3
import hashlib,json
from pathlib import Path
p=Path(r"D:/CFD/CFD_ANCF_VIV/runtime/fixed_cylinder_o_grid/2_dof_validation/singh_ustar5_pilot_v1")
j=json.loads((p/"SINGH_USTAR5_PILOT_PREP_V1.json").read_text(encoding="utf-8"))
j["PRE_RUN_AUDIT"]="FIXED_AFTER_LAUNCH_PREFLIGHT_FAILURE"
j["initial_launch_attempt"]={"status":"FAILED_BEFORE_TIME_ADVANCE","cause":"libmomentumTransportModels.so not found because prototype_env.sh was not sourced","preserved_evidence":["failure_initial_launch_fluid.stderr","failure_initial_launch_fluid.stdout","failure_initial_launch_participant.stderr","failure_initial_launch_participant.stdout"],"corrected":True}
j["NO_SUCCESSFUL_OPENFOAM_TIME_STEP"]=True
j["NO_PRECICE_COUPLING_RUN"]=True
j.pop("deliverables",None); j.pop("sha256",None)
def h(q):
 x=hashlib.sha256()
 with q.open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""): x.update(b)
 return x.hexdigest()
files=[q for q in p.rglob("*") if q.is_file() and q.name!="SINGH_USTAR5_PILOT_PREP_V1.json"]
m={str(q.relative_to(p)).replace("\\","/"):h(q) for q in sorted(files)}
j["deliverables"]=sorted(m); j["sha256"]=m
with (p/"SINGH_USTAR5_PILOT_PREP_V1.json").open("w",encoding="utf-8",newline="\n") as f: json.dump(j,f,indent=2,ensure_ascii=False,sort_keys=True); f.write("\n")
