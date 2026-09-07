"""Fresh, no-ANCF OF10 lifecycle and nonzero-motion rollback qualification.

This wrapper deliberately reuses only the frozen case preparation mechanics;
it creates a new runtime and changes the fixture timing contract before launch:
initial data plus a +A, +A, -A, -A trial schedule.  Thus the one physical
window exercises both same-input retry and different-input rollback isolation.
"""
from __future__ import annotations

import json
from pathlib import Path

import run_real_precice_rollback_qualification as base


RUN = "openfoam10_checkpoint_lifecycle_motion_timing_closure_v1_run_001"
DIAG_LIBRARY_WSL = "/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_004/lib"
DIAG_LIBRARY = Path(DIAG_LIBRARY_WSL)
DIAG_LIBRARY_FILE = DIAG_LIBRARY / "libpreciceAdapterFunctionObject.so"
AMPLITUDE_Y_M = 0.002


def xml(exchange_dir: Path) -> str:
    return "\n".join((
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">',
        '<data:vector name="Displacement" waveform-degree="0"/><data:vector name="Force" waveform-degree="0"/>',
        '<mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh><mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh>',
        f'<m2n:sockets acceptor="Structure" connector="Fluid" exchange-directory="{base.wsl(exchange_dir)}"/>',
        '<participant name="Structure"><provide-mesh name="Structure-Mesh"/><write-data name="Displacement" mesh="Structure-Mesh"/><read-data name="Force" mesh="Structure-Mesh"/></participant>',
        '<participant name="Fluid"><receive-mesh name="Structure-Mesh" from="Structure"/><provide-mesh name="Fluid-Mesh"/><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent"/><mapping:nearest-neighbor direction="write" from="Fluid-Mesh" to="Structure-Mesh" constraint="conservative"/><write-data name="Force" mesh="Fluid-Mesh"/><read-data name="Displacement" mesh="Fluid-Mesh"/></participant>',
        # The pre-frozen test scale A=2 mm makes +A -> -A non-convergent at
        # abs-limit 1e-4, while the repeated +A and -A attempts converge.
        '<coupling-scheme:parallel-implicit><participants first="Structure" second="Fluid"/><time-window-size value="0.005"/><max-time value="0.005"/><min-iterations value="2"/><max-iterations value="8"/><absolute-or-relative-convergence-measure data="Displacement" mesh="Structure-Mesh" abs-limit="0.0001" rel-limit="0.01"/><absolute-or-relative-convergence-measure data="Force" mesh="Structure-Mesh" abs-limit="10000000" rel-limit="1"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure" to="Fluid" initialize="yes" substeps="false"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid" to="Structure" substeps="false"/></coupling-scheme:parallel-implicit>',
        '</precice-configuration>',
    ))


def participant_code() -> str:
    return r'''from __future__ import annotations
import json, math, sys
from pathlib import Path
import precice

config, evidence = map(Path, sys.argv[1:3])
A=0.002
vertices=[(0.5*math.cos(2*math.pi*i/40),0.5*math.sin(2*math.pi*i/40)) for i in range(40)]
participant=precice.Participant("Structure",str(config),0,1)
mesh=participant.set_mesh_vertices("Structure-Mesh",vertices)
rows=[]
initial_requested=participant.requires_initial_data()
if initial_requested:
    participant.write_data("Structure-Mesh","Displacement",mesh,[[0.0,A] for _ in vertices])
    rows.append({"event":"INITIAL_DISPLACEMENT_WRITTEN","trial_displacement_y_m":A,"physical_time_s":0.0})
participant.initialize()
iteration=0; rollback_count=0
# Initial +A is read by Fluid before trial 1.  The following writes are read
# after each advance, producing trial inputs +A, +A, -A, -A.
schedule=(A,-A,-A)
while participant.is_coupling_ongoing():
    if participant.requires_writing_checkpoint():
        rows.append({"event":"STRUCTURE_CHECKPOINT_WRITE","iteration":iteration,"physical_time_s":0.0})
    y=schedule[min(iteration,len(schedule)-1)]
    participant.write_data("Structure-Mesh","Displacement",mesh,[[0.0,y] for _ in vertices])
    iteration += 1
    participant.advance(0.005)
    force=participant.read_data("Structure-Mesh","Force",mesh,0.0)
    force_sum=[sum(float(row[d]) for row in force) for d in range(2)]
    rows.append({"event":"TRIAL_ADVANCED","iteration":iteration,"trial_displacement_y_m":y,"force_sum_N":force_sum,"physical_time_s":0.005})
    if participant.requires_reading_checkpoint():
        rollback_count += 1
        rows.append({"event":"STRUCTURE_CHECKPOINT_READ","iteration":iteration,"rollback_count":rollback_count,"physical_time_restored_s":0.0})
        continue
    rows.append({"event":"FINAL_COMMIT","iteration":iteration,"physical_time_s":0.005})
    break
participant.finalize()
with evidence.open("w",encoding="utf-8",newline="\n") as stream:
    json.dump({"initial_data_requested":initial_requested,"iterations":iteration,"rollbacks":rollback_count,"rows":rows},stream,indent=2)
    stream.write("\n")
'''


def main() -> int:
    base.RUN = RUN
    base.RUNTIME, base.RESULTS = base.ROOT / "runtime" / RUN, base.ROOT / "results" / RUN
    base.DIAG_LIBRARY_WSL = DIAG_LIBRARY_WSL
    base.DIAG_LIBRARY = DIAG_LIBRARY
    base.DIAG_LIBRARY_FILE = DIAG_LIBRARY_FILE
    base.TRIAL_Y_M = (AMPLITUDE_Y_M, -AMPLITUDE_Y_M)
    base.xml = xml
    base.participant_code = participant_code
    case = base.prepare()
    contract_path = base.RUNTIME / "contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract.update({
        "schema_version": "openfoam10-checkpoint-lifecycle-motion-timing-closure-v1",
        "initial_displacement_y_m": AMPLITUDE_Y_M,
        "trial_input_schedule_y_m": [AMPLITUDE_Y_M, AMPLITUDE_Y_M, -AMPLITUDE_Y_M, -AMPLITUDE_Y_M],
        "displacement_semantics": "total_displacement",
        "fixture_convergence_abs_limit_m": 0.0001,
        "qualification": "no-ANCF one physical window only",
    })
    base.write(contract_path, json.dumps(contract, indent=2) + "\n")
    code = base.run(case)
    trace_path = base.RUNTIME / "adapter_rollback_trace.jsonl"
    trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()] if trace_path.is_file() else []
    participant_path = base.RUNTIME / "participant_evidence.json"
    participant = json.loads(participant_path.read_text(encoding="utf-8")) if participant_path.is_file() else {}
    base.RESULTS.mkdir(parents=True, exist_ok=True)
    base.write(base.RESULTS / "real_rollback_raw.json", json.dumps({
        "return_code": code, "adapter_trace": trace, "participant": participant,
        "runtime": str(base.RUNTIME), "diagnostic_library_sha256": base.sha256(DIAG_LIBRARY_FILE),
    }, indent=2) + "\n")
    print(json.dumps({"return_code": code, "events": [x.get("event") for x in trace], "participant_iterations": participant.get("iterations")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
