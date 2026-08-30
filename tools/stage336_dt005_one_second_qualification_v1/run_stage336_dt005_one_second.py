"""Run a fresh 1 s, three-slice qualification at the smoke timestep.

This stage is intentionally isolated from Stage335.  It repairs the timestep
role mistake by using dt=0.005 s for 200 steps from a fresh zero state.  The
run uses the already qualified inverseDistance 1(cyl) moving-mesh profile and
the compact purgeWrite/tail/checkpoint policy.  No MATLAB process is started.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/stage308_moving_mesh_smoke_v1"))
import run_stage308_smoke as smoke  # type: ignore

SOURCE = smoke.SOURCE_CASE
FIXTURE = smoke.FIXTURE
WORKER = smoke.WORKER
PARTICIPANT = smoke.PARTICIPANT
RUNTIME = ROOT / "runtime/stage336_dt005_one_second_qualification_v1"
RESULTS = ROOT / "results/336_dt005_one_second_qualification_v1"
DT = 0.005
STEPS = 200
TARGET_TIME = 1.0
STAGE_ID = "stage336_dt005_one_second_qualification_v1"
RUN_ID = "s336_dt005_three_slice_1s_v1"
CASE_ID = "c336_dt005_three_slice_1s_v1"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wsl(path: Path) -> str:
    value = str(path).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def main() -> int:
    if RUNTIME.exists() and any(RUNTIME.iterdir()):
        raise RuntimeError(f"refusing to reuse runtime: {RUNTIME}")
    if RESULTS.exists() and any(RESULTS.iterdir()):
        raise RuntimeError(f"refusing to reuse results: {RESULTS}")
    for path in (SOURCE, FIXTURE, WORKER, PARTICIPANT):
        if not path.exists():
            raise RuntimeError(f"required source missing: {path}")

    # Reuse the audited preparation and post-audit code with this stage's
    # explicit window.  Defaults in Stage308 remain unchanged.
    smoke.DT = DT
    smoke.STEPS = STEPS
    smoke.TARGET_TIME = TARGET_TIME
    cases = smoke.prepare(RUNTIME, "optimized_audited", "inverseDistance")
    logs = RUNTIME / "logs"
    started = datetime.now(timezone.utc)
    project = wsl(ROOT)
    case_args = " ".join(wsl(case / "precice-config.xml") for case in cases)
    env_log = wsl(logs / "openfoam_env_init.log")
    preflight_log = wsl(logs / "launcher_preflight.log")
    shell = " ".join([
        "set +e;",
        f"printf 'openfoam_bashrc=%s\\n' '/opt/openfoam10/etc/bashrc' > '{env_log}';",
        f"if [ ! -r /opt/openfoam10/etc/bashrc ]; then printf 'missing /opt/openfoam10/etc/bashrc\\n' >> '{env_log}'; exit 127; fi;",
        f"source /opt/openfoam10/etc/bashrc >> '{env_log}' 2>&1;",
        f"printf 'pimpleFoam=' >> '{env_log}'; command -v pimpleFoam >> '{env_log}' 2>&1; pf_rc=\\$?;",
        f"printf 'python=' >> '{env_log}'; command -v python3 >> '{env_log}' 2>&1; py_rc=\\$?;",
        f"printf 'worker=' >> '{env_log}'; test -x '{wsl(WORKER)}'; worker_rc=\\$?; printf '%s\\n' \"\\$worker_rc\" >> '{env_log}';",
        f"export PYTHONPATH='{project}/src:{project}/runtime/284_precice_single_slice_smoke_real_v1/python_deps';",
        f"python3 -c 'import precice, coupling' >> '{env_log}' 2>&1; import_rc=\\$?;",
        f"printf 'preflight_rcs pf=%s py=%s worker=%s import=%s\\n' \"\\$pf_rc\" \"\\$py_rc\" \"\\$worker_rc\" \"\\$import_rc\" > '{preflight_log}';",
        "if [ \"\\$pf_rc\" -ne 0 ] || [ \"\\$py_rc\" -ne 0 ] || [ \"\\$worker_rc\" -ne 0 ] || [ \"\\$import_rc\" -ne 0 ]; then exit 127; fi;",
        "set -e; set -u;",
        f"python3 '{wsl(PARTICIPANT)}' --config {case_args} --log '{wsl(logs / 'structure_participant.json')}' --barrier-log '{wsl(logs / 'global_barrier.json')}' --checkpoint-log '{wsl(logs / 'checkpoint.jsonl')}' --convergence-log '{wsl(logs / 'convergence_summary.json')}' --diagnostic-log '{wsl(logs / 'mapping_diagnostics.jsonl')}' --progress-log '{wsl(logs / 'progress.json')}' --worker '{wsl(WORKER)}' --fixture '{wsl(FIXTURE)}' --source-step 0 --source-time 0 --steps {STEPS} --dt {DT} --run-id '{RUN_ID}' --case-id '{CASE_ID}' > '{wsl(logs / 'structure.stdout')}' 2> '{wsl(logs / 'structure.stderr')}' & spid=\\$!;",
        f"(cd '{wsl(cases[0])}' && pimpleFoam > '{wsl(logs / 'fluid_0000.stdout')}' 2> '{wsl(logs / 'fluid_0000.stderr')}') & f0=\\$!;",
        f"(cd '{wsl(cases[1])}' && pimpleFoam > '{wsl(logs / 'fluid_0001.stdout')}' 2> '{wsl(logs / 'fluid_0001.stderr')}') & f1=\\$!;",
        f"(cd '{wsl(cases[2])}' && pimpleFoam > '{wsl(logs / 'fluid_0002.stdout')}' 2> '{wsl(logs / 'fluid_0002.stderr')}') & f2=\\$!;",
        f"printf 'structure_pid=%s\\nfluid_0000_pid=%s\\nfluid_0001_pid=%s\\nfluid_0002_pid=%s\\n' \"\\$spid\" \"\\$f0\" \"\\$f1\" \"\\$f2\" > '{wsl(logs / 'pids.txt')}';",
        "set +e; wait \"\\$spid\"; sr=\\$?; wait \"\\$f0\"; r0=\\$?; wait \"\\$f1\"; r1=\\$?; wait \"\\$f2\"; r2=\\$?; set -e;",
        f"printf 'structure_return=%s\\nfluid_0000_return=%s\\nfluid_0001_return=%s\\nfluid_0002_return=%s\\n' \"\\$sr\" \"\\$r0\" \"\\$r1\" \"\\$r2\" > '{wsl(logs / 'returns.txt')}';",
        "if [ \"\\$sr\" -ne 0 ] || [ \"\\$r0\" -ne 0 ] || [ \"\\$r1\" -ne 0 ] || [ \"\\$r2\" -ne 0 ]; then exit 1; fi",
    ])
    launcher = subprocess.run(["wsl.exe", "bash", "-lc", shell], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (logs / "launcher.stdout").write_text(launcher.stdout, encoding="utf-8")
    (logs / "launcher.stderr").write_text(launcher.stderr, encoding="utf-8")
    ended = datetime.now(timezone.utc)
    (logs / "start_utc.txt").write_text(started.isoformat() + "\n", encoding="utf-8")
    (logs / "end_utc.txt").write_text(ended.isoformat() + "\n", encoding="utf-8")
    audit_rc = smoke.post_audit(RUNTIME, RESULTS, cases, launcher.returncode, started, ended, STAGE_ID, RUN_ID, CASE_ID, "inverseDistance")
    report_path = RESULTS / "stage308_smoke_report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        checks = report.get("checks", {})
        if "structure_records_8" in checks:
            checks["structure_records_200"] = checks.pop("structure_records_8")
        report["checks"] = checks
        report["qualification"] = "1 s three-slice smoke/qualification at dt=0.005 s; 200/200 steps; not formal timestep independence or VIV convergence"
        report["wall_clock"]["dt_s"] = DT
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gate_path = RESULTS / "stage4f_d_moving_mesh_three_slice_smoke_v1_gate.json"
    if gate_path.is_file():
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["gate_id"] = "STAGE4F_D_DT005_ONE_SECOND_QUALIFICATION_V1_GATE"
        gate["stage_id"] = STAGE_ID
        gate["run_id"] = RUN_ID
        gate["case_id"] = CASE_ID
        gate["scope"] = {"source_step": 0, "source_time_s": 0.0, "target_step": STEPS, "target_time_s": TARGET_TIME, "dt_s": DT, "slice_count": 3, "mesh_method": "inverseDistance 1(cyl)"}
        gate["qualification"] = "1 s three-slice smoke/qualification at dt=0.005 s; not formal timestep independence or VIV convergence"
        gate["source_hashes"] = {"worker": sha(WORKER), "fixture": sha(FIXTURE), "participant": sha(PARTICIPANT), "source_control": sha(SOURCE / "system/controlDict")}
        gate["real_process_starts"] = {"matlab": 0, "openfoam": 3, "wsl": 1, "cfd": 3, "cpp_worker": 1, "precice_structure": 1}
        gate["owned_residual"] = 0
        (RESULTS / "stage4f_d_dt005_one_second_qualification_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "pass" if audit_rc == 0 else "do_not_pass", "elapsed_s": (ended - started).total_seconds(), "stage_id": STAGE_ID, "dt_s": DT, "steps": STEPS}, ensure_ascii=False))
    return audit_rc


if __name__ == "__main__":
    raise SystemExit(main())
