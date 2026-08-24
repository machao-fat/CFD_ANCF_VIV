from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path


def rows(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        def convert(k, v):
            if k in {"compression_risk", "structure_converged", "status"}:
                return v
            return float(v)
        return [{k: convert(k, v) for k, v in r.items()} for r in csv.DictReader(stream)]


def rms(values):
    return math.sqrt(sum(v*v for v in values)/max(1,len(values)))


def main():
    root=Path(__file__).resolve().parents[2]
    e=rows(root/"results/04_eb_ancf_physical_comparison/eb_topT1e6_100/coupling_audit.csv")
    a=rows(root/"results/04_eb_ancf_physical_comparison/ancf_topT1e6_100/coupling_audit.csv")
    n=min(len(e),len(a)); e=e[:n];a=a[:n]
    ey=[r["corrected_y_m"] for r in e]; ay=[r["corrected_y_m"] for r in a]
    ef=[r["force_y_N"] for r in e]; af=[r["force_y_N"] for r in a]
    def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    mesh_e=root/"cases/openfoam/single_slice_eb_fsi_physical100/constant/polyMesh/points"
    mesh_a=root/"cases/openfoam/single_slice_ancf_fsi_physical100/constant/polyMesh/points"
    out={
        "status":"interface_only_near_zero_response",
        "steps":n,"time_end_s":e[-1]["time_s"],"dt_s":e[0]["time_s"],
        "parameters":{"topTension_N":1e6,"youngs_modulus_Pa":2.07e11,"L_m":1.0,"D_m":1.0,"dInner_m":0.9},
        "same_mesh_hash":sha(mesh_e)==sha(mesh_a),
        "same_force_time_grid":all(abs(x["time_s"]-y["time_s"])<1e-14 for x,y in zip(e,a)),
        "eb_rms_y_m":rms(ey),"ancf_rms_y_m":rms(ay),"y_rms_relative_difference":abs(rms(ey)-rms(ay))/max(rms(ey),1e-30),
        "eb_peak_y_m":max(abs(v) for v in ey),"ancf_peak_y_m":max(abs(v) for v in ay),
        "force_y_relative_rms_difference":rms([x-y for x,y in zip(ef,af)])/max(rms(ef),1e-30),
        "eb_mean_power_W_last_half":sum(r["power_structure_corrected_W"] for r in e[n//2:])/max(1,n-n//2),
        "ancf_mean_power_W_last_half":sum(r["power_structure_corrected_W"] for r in a[n//2:])/max(1,n-n//2),
        "eb_min_tension_N":min(r["min_tension_N"] for r in e),"ancf_min_tension_N":min(r["min_tension_N"] for r in a),
        "ancf_max_relative_residual":max(r["structure_relative_residual"] for r in a),
        "limitation":"Both responses remain near 1e-10 m; this is an interface diagnostic, not an accepted physical-amplitude comparison.",
        "visible_response_attempt":"results/04_eb_ancf_physical_comparison/online_comparison_status.json"
    }
    outdir=root/"results/04_eb_ancf_physical_comparison"; (outdir/"online_comparison_100.json").write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8");print(json.dumps(out,indent=2))

if __name__=="__main__":main()
