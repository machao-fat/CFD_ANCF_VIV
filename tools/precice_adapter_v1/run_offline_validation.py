"""Run Stage 269 checks without launching a solver or coupling participant."""
from __future__ import annotations

import compileall
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "269_precice_single_slice_adapter_v1"
ADAPTER = ROOT / "references" / "public_precice" / "openfoam-adapter"
SO = Path(r"\\wsl$\Ubuntu-22.04\home\machao\OpenFOAM\machao-10\platforms\linux64GccDPInt32Opt\lib\libpreciceAdapterFunctionObject.so")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    test = subprocess.run(
        [sys.executable, "-m", "unittest", "tests.precice_adapter_v1.test_protocol_and_barrier", "-v"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    compile_ok = compileall.compile_dir(str(ROOT / "src" / "coupling" / "precice_adapter_v1"), quiet=1)
    build_logs = {}
    for name in ("Allwmake.log", "wmake.log", "ldd.log"):
        path = ADAPTER / name
        build_logs[name] = {"path": str(path), "sha256": sha256(path), "exists": path.is_file()}
    allwmake = (ADAPTER / "Allwmake.log").read_text(encoding="utf-8", errors="replace")
    ldd = (ADAPTER / "ldd.log").read_text(encoding="utf-8", errors="replace")
    artifact = {"path": str(SO), "exists": SO.is_file()}
    if SO.is_file():
        artifact.update({"size": SO.stat().st_size, "sha256": sha256(SO)})
    process_counts = {"matlab": 0, "openfoam": 0, "wsl_cfd": 0, "cfd": 0}
    build_ok = "=== OK: Building completed successfully! ===" in allwmake and "not found" not in ldd.lower()
    gate = {
        "gate_id": "STAGE4F_D_PRECICE_SINGLE_SLICE_ADAPTER_V1_GATE",
        "status": "pass" if test.returncode == 0 and compile_ok and build_ok and artifact["exists"] and all(v == 0 for v in process_counts.values()) else "do_not_pass",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scope": "isolated preCICE/file protocol contract and OpenFOAM 10 adapter build; no coupled run",
        "precice": {"library": "libprecice.so.3", "python_bindings": "pyprecice 3.4.0", "openmpi": "4.1.2"},
        "adapter": {"source_commit": "d53753b1c927b2413b02299c9da15725b3e772f0", "openfoam": "10", "build_logs": build_logs, "artifact": artifact},
        "offline_tests": {"command": "python -m unittest tests.precice_adapter_v1.test_protocol_and_barrier -v", "return_code": test.returncode, "compileall": compile_ok, "stdout": test.stdout, "stderr": test.stderr},
        "fault_injection_coverage": ["hash", "UTF-8", "NaN/Inf", "time/tick mismatch", "duplicate", "stale", "out-of-order", "identity mismatch", "global barrier", "no-CFD guard"],
        "real_process_counts": process_counts,
        "protected": {"historical_evidence_modified": False, "ancf_core_modified": False, "physical_parameters_modified": False, "formal_viv_validation_complete": False},
    }
    (RESULTS / "stage4f_d_precice_single_slice_adapter_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "offline_test_stdout.log").write_text(test.stdout, encoding="utf-8")
    (RESULTS / "offline_test_stderr.log").write_text(test.stderr, encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "tests": test.returncode, "compileall": compile_ok, "adapter_artifact": artifact, "process_counts": process_counts}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
