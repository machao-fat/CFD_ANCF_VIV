"""One frozen no-ANCF preCICE fixture for the OF10-owned prototype.

This wrapper reuses the existing prescribed-motion participant, XML contract,
and case preparation.  Its only substitutions are the isolated OF10 ABI
environment and adapter build005.  The Fluid participant remains the normal
preCICE Adapter path: it receives displacement, updates its usual fields, and
the solver invokes fvMesh::move().
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "reproducible_openfoam10_adapter_rollback_qualification_v1"))

import run_real_precice_rollback_qualification as base
import run_checkpoint_lifecycle_motion_qualification as lifecycle


# `_001` stopped during local file preparation before either participant
# launched.  `_002` is the sole physical fixture invocation.
RUN = os.environ.get(
    "OF10_OWNED_FIXTURE_RUN",
    "of10_owned_atomic_mesh_history_restore_prototype_v1_precice_fixture_002",
)
PROTOTYPE_ROOT_WSL = os.environ.get(
    "OF10_OWNED_PROTOTYPE_ROOT",
    "/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1",
)
ADAPTER_BUILD = os.environ.get("OF10_OWNED_ADAPTER_BUILD", "adapter_build_005")
FIXTURE_MODE = os.environ.get("OF10_OWNED_FIXTURE_MODE", "implicit-abb-min3")
ADAPTER_LIBRARY_WSL = os.environ.get(
    "OF10_OWNED_ADAPTER_LIBRARY_WSL",
    PROTOTYPE_ROOT_WSL + f"/{ADAPTER_BUILD}/lib",
)
ENV_SCRIPT_WSL = (
    "/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/tools/"
    "of10_owned_atomic_mesh_history_restore_prototype_v1/prototype_env.sh"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def host_path(wsl_path: str) -> Path:
    if os.name != "nt":
        return Path(wsl_path)
    return Path(r"\\wsl$\Ubuntu-22.04") / wsl_path.lstrip("/").replace("/", "\\")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # The deployed Python version lacks Path.write_text(newline=...).  Use the
    # same explicit text-mode contract as the frozen fixture helper.
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def participant_code_a_restore_b_restore_b() -> str:
    """Keep the normal preCICE participant, but freeze the intended trials.

    preCICE delivers the initialized +A sample to Fluid for trial one.  The
    write before that first advance is delivered after rollback, so its first
    scheduled value must already be B.  The resulting Fluid inputs are
    +A, -A, -A: checkpoint -> A -> restore -> B -> restore -> B.
    """
    code = lifecycle.participant_code()
    marker = "schedule=(A,-A,-A)"
    if marker not in code:
        raise RuntimeError("unexpected frozen lifecycle participant source")
    code = code.replace(
        "# after each advance, producing trial inputs +A, +A, -A, -A.\n"
        "schedule=(A,-A,-A)",
        "# after each advance, producing Fluid trial inputs +A, -A, -A.\n"
        "schedule=(-A,-A,-A)",
    )
    return code


def test_only_xml_min_three(exchange_dir: Path) -> str:
    """Require the third, already-scheduled B trial without changing gates."""
    source = lifecycle.xml(exchange_dir)
    marker = '<min-iterations value="2"/>'
    if source.count(marker) != 1:
        raise RuntimeError("unexpected frozen lifecycle XML min-iterations")
    return source.replace(marker, '<min-iterations value="3"/>')


def explicit_one_step_xml(exchange_dir: Path) -> str:
    """Reuse the fixture plumbing for the existing non-rollback explicit check."""
    source = lifecycle.xml(exchange_dir)
    implicit = re.compile(
        r'<coupling-scheme:parallel-implicit>.*?</coupling-scheme:parallel-implicit>'
    )
    replacement = (
        '<coupling-scheme:parallel-explicit><participants first="Structure" '
        'second="Fluid"/><time-window-size value="0.005"/><max-time '
        'value="0.005"/><exchange data="Displacement" mesh="Structure-Mesh" '
        'from="Structure" to="Fluid" initialize="yes" substeps="false"/>'
        '<exchange data="Force" mesh="Structure-Mesh" from="Fluid" '
        'to="Structure" substeps="false"/></coupling-scheme:parallel-explicit>'
    )
    result, count = implicit.subn(replacement, source)
    if count != 1:
        raise RuntimeError("unexpected frozen lifecycle XML coupling scheme")
    return result


def run(case: Path) -> int:
    runtime = base.RUNTIME
    write(runtime / "participant.py", base.participant_code())
    trace = runtime / "adapter_rollback_trace.jsonl"
    adapter_sha = sha256(base.DIAG_LIBRARY_FILE)
    script = "\n".join((
        "set -o pipefail",
        f"source '{ENV_SCRIPT_WSL}' '{PROTOTYPE_ROOT_WSL}'",
        # Keep the isolated adapter first; prototype_env already sets the
        # complete independent OpenFOAM prefix.
        f"export LD_LIBRARY_PATH='{ADAPTER_LIBRARY_WSL}':$LD_LIBRARY_PATH",
        f"export PYTHONPATH='{base.wsl(base.PYDEPS)}'",
        f"export PRECICE_ADAPTER_ROLLBACK_DIAGNOSTICS_PATH='{base.wsl(trace)}'",
        f"export PRECICE_ADAPTER_BUILD_SHA256='{adapter_sha}'",
        "command -v pimpleFoam > '" + base.wsl(runtime / "pimpleFoam.path") + "'",
        "ldd \"$(command -v pimpleFoam)\" > '" + base.wsl(runtime / "pimpleFoam.ldd") + "'",
        "set +e",
        f"python3 '{base.wsl(runtime / 'participant.py')}' '{base.wsl(case / 'precice-config.xml')}' '{base.wsl(runtime / 'participant_evidence.json')}' > '{base.wsl(runtime / 'structure.stdout')}' 2> '{base.wsl(runtime / 'structure.stderr')}' & structure_pid=$!",
        f"(cd '{base.wsl(case)}' && pimpleFoam > '{base.wsl(runtime / 'fluid.stdout')}' 2> '{base.wsl(runtime / 'fluid.stderr')}') & fluid_pid=$!",
        "wait $structure_pid; structure_rc=$?",
        "wait $fluid_pid; fluid_rc=$?",
        f"printf 'structure=%s\\nfluid=%s\\n' \"$structure_rc\" \"$fluid_rc\" > '{base.wsl(runtime / 'returns.txt')}'",
        "[ $structure_rc -eq 0 ] && [ $fluid_rc -eq 0 ]",
    )) + "\n"
    write(runtime / "launch.sh", script)
    command = ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", base.wsl(runtime / "launch.sh")]
    completed = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=300)
    write(runtime / "launcher.stdout", completed.stdout)
    write(runtime / "launcher.stderr", completed.stderr)
    return completed.returncode


def main() -> int:
    base.RUN = RUN
    base.RUNTIME = ROOT / "runtime" / RUN
    base.RESULTS = ROOT / "results" / RUN
    base.DIAG_LIBRARY_WSL = ADAPTER_LIBRARY_WSL
    base.DIAG_LIBRARY = host_path(ADAPTER_LIBRARY_WSL)
    base.DIAG_LIBRARY_FILE = base.DIAG_LIBRARY / "libpreciceAdapterFunctionObject.so"
    base.TRIAL_Y_M = (lifecycle.AMPLITUDE_Y_M, -lifecycle.AMPLITUDE_Y_M)
    if FIXTURE_MODE == "implicit-abb-min3":
        base.xml = test_only_xml_min_three
        base.participant_code = participant_code_a_restore_b_restore_b
        fixture_metadata = {
            "participant_write_schedule_y_m": [-0.002, -0.002, -0.002],
            "expected_fluid_trial_inputs_y_m": [0.002, -0.002, -0.002],
            "test_only_min_iterations": 3,
            "production_min_iterations": 2,
            "test_only_reason": "force scheduled B replay coverage; convergence criteria unchanged",
            "fixed_point_iterations": {"min": 3, "max": 8},
            "production_fixed_point_iterations": {"min": 2, "max": 8},
        }
    elif FIXTURE_MODE == "explicit-one-step":
        base.xml = explicit_one_step_xml
        base.participant_code = lifecycle.participant_code
        fixture_metadata = {
            "participant_write_schedule_y_m": [0.002],
            "expected_fluid_trial_inputs_y_m": [0.002],
            "test_only_reason": "existing prescribed-motion normal-path explicit regression",
            "fixed_point_iterations": "NOT_APPLICABLE_PARALLEL_EXPLICIT",
            "production_fixed_point_iterations": {"min": 2, "max": 8},
        }
    else:
        raise RuntimeError(f"unsupported OF10-owned fixture mode: {FIXTURE_MODE}")

    case = base.prepare()
    contract_path = base.RUNTIME / "contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract.update({
        "schema_version": "of10-owned-atomic-mesh-history-restore-prototype-v1",
        "fixture": "real-precice-no-ancf-prescribed-motion",
        "fixture_mode": FIXTURE_MODE,
        "adapter_library_sha256": sha256(base.DIAG_LIBRARY_FILE),
        "openfoam_abi_prefix": PROTOTYPE_ROOT_WSL + "/openfoam10",
        "physical_windows": 1,
        "source_openfoam_time_s": 0.100,
        "target_openfoam_time_s": 0.105,
        "dt_s": 0.005,
        "acceleration": "forbidden",
    })
    contract.update(fixture_metadata)
    write(contract_path, json.dumps(contract, indent=2) + "\n")

    code = run(case)
    trace_path = base.RUNTIME / "adapter_rollback_trace.jsonl"
    trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()] if trace_path.is_file() else []
    participant_path = base.RUNTIME / "participant_evidence.json"
    participant = json.loads(participant_path.read_text(encoding="utf-8")) if participant_path.is_file() else {}
    base.RESULTS.mkdir(parents=True, exist_ok=True)
    write(base.RESULTS / "real_rollback_raw.json", json.dumps({
        "return_code": code,
        "adapter_trace": trace,
        "participant": participant,
        "adapter_library_wsl": ADAPTER_LIBRARY_WSL,
        "adapter_library_sha256": sha256(base.DIAG_LIBRARY_FILE),
        "runtime": str(base.RUNTIME),
    }, indent=2) + "\n")
    print(json.dumps({
        "return_code": code,
        "events": [row.get("event") for row in trace],
        "participant_iterations": participant.get("iterations"),
    }))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
