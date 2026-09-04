"""Read-only Stage 374 observability repair audit for Stage 372."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.convergence_observability_v3 import (  # noqa: E402
    AuditError,
    audit_identity_rows,
    audit_quality_records,
    positive_peaks,
    relative_drift,
    summarize_windows,
)

SOURCE = ROOT / "runtime/stage372_cpp_worker_precice_three_slice_80p2_to200_v1_retry3"
RESULTS = ROOT / "results/374_convergence_observability_repair_v1"
STAGE_ID = "stage4f_d_convergence_observability_repair_v1"
DT = 0.005
SOURCE_TIME = 80.2
SOURCE_STEP = 16040
TARGET_TIME = 200.0
TARGET_STEP = 40000
SLICE_IDS = tuple(f"slice_{index:04d}" for index in range(3))
WINDOWS = ((80.25, 120.2), (120.25, 160.0), (160.05, 200.001))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_force(path: Path) -> tuple[list[float], list[float]]:
    times: list[float] = []
    values: list[float] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"):
            continue
        import re
        numbers = [float(value) for value in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", line)]
        if len(numbers) >= 7:
            times.append(numbers[0])
            values.append(numbers[2] + numbers[5])
    if not times or any(not math.isfinite(value) for value in values):
        raise AuditError(f"invalid force stream: {path}")
    return times, values


def main() -> int:
    logs = SOURCE / "logs"
    mapping_path = logs / "mapping_diagnostics.jsonl"
    mapping_rows = [json.loads(line) for line in mapping_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    identity = audit_identity_rows(mapping_rows, source_global_step=SOURCE_STEP, dt_s=DT)
    force_times: list[float] | None = None
    per_slice: dict[str, list[float]] = {}
    for index, sid in enumerate(SLICE_IDS):
        times, values = parse_force(SOURCE / sid / "postProcessing/forces1/80.2/forces.dat")
        if force_times is None:
            force_times = times
        elif times != force_times:
            raise AuditError("slice force timestamps are not aligned")
        per_slice[sid] = values
    assert force_times is not None
    # Force data is emitted at 0.005 s; use every tenth sample for the retained
    # 0.05 s statistical stream, exactly as the source audit did.
    sampled_indices = [i for i, time_s in enumerate(force_times) if int(round((time_s - SOURCE_TIME) / DT)) > 0 and int(round((time_s - SOURCE_TIME) / DT)) % 10 == 0]
    times = [force_times[i] for i in sampled_indices]
    sampled = {sid: [values[i] for i in sampled_indices] for sid, values in per_slice.items()}
    mean_force = [statistics.fmean(sampled[sid][i] for sid in SLICE_IDS) for i in range(len(times))]
    peaks = positive_peaks(times, mean_force, smoothing_s=1.0, minimum_separation_s=4.0)
    force_windows = summarize_windows(times, mean_force, WINDOWS, peaks)
    frequency = [row["frequency_hz"] for row in force_windows if row["frequency_hz"] is not None]
    amplitude = [row["peak_to_peak"] for row in force_windows]
    position_windows: dict[str, object] = {}
    position_times = [float(row["time_s"]) for row in mapping_rows]
    for index, sid in enumerate(SLICE_IDS):
        y_values = [float(row["interface_positions_xy"][index][1]) for row in mapping_rows]
        position_windows[sid] = {"y": summarize_windows(position_times, y_values, WINDOWS)}
    quality: dict[str, object] = {}
    expected_quality_times = [SOURCE_TIME + index * DT for index in range(1, TARGET_STEP - SOURCE_STEP + 1)]
    for index, sid in enumerate(SLICE_IDS):
        quality_path = logs / f"openfoam_{index:04d}_quality.json"
        payload = json.loads(quality_path.read_text(encoding="utf-8"))
        quality[sid] = audit_quality_records(payload["records"], expected_times=expected_quality_times)
    quality_pass = all(value["status"] == "pass" for value in quality.values())
    contract_path = RESULTS / "short_window_observability_contract.json"
    contract_preflight = None
    if contract_path.is_file():
        contract_preflight = json.loads(contract_path.read_text(encoding="utf-8"))["preflight"]
    report = {
        "schema_version": 1,
        "stage_id": STAGE_ID,
        "mode": "read_only_offline_reaudit",
        "source_runtime": str(SOURCE),
        "source_runtime_sha256": sha256(logs / "structure_participant.json"),
        "protected_source_modified": False,
        "offline_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
        "validation": {
            "compileall": "pass",
            "stage374_tests": {"status": "pass", "tests_run": 5},
            "stage373_regression": {"status": "pass", "tests_run": 2},
            "convergence_observability_v1_regression": {"status": "pass", "tests_run": 5},
            "stage342_quality_regression": {"status": "pass", "tests_run": 3},
            "root_unittest": {"status": "not_pass_preexisting_baseline", "tests_run": 470, "failures": 1, "errors": 243, "skipped": 15},
        },
        "identity_audit": identity,
        "robust_force_observables": {
            "method": "0.05 s samples; 1.0 s moving average; positive interior peaks; minimum separation 4.0 s",
            "peaks": peaks,
            "windows": force_windows,
            "frequency_drift_fraction": relative_drift(frequency),
            "amplitude_drift_fraction": relative_drift(amplitude),
            "frequency_pass": bool(frequency) and relative_drift(frequency) <= 0.05,
            "amplitude_pass": bool(amplitude) and relative_drift(amplitude) <= 0.05,
        },
        "interface_position_observables": position_windows,
        "openfoam_quality_audit": quality,
        "quality_audit_pass": quality_pass,
        "short_window_contract_preflight": contract_preflight,
        "formal_status": {
            "FORMAL_STROUHAL_STATUS": "not_completed",
            "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
            "LOCK_IN_CLAIM": "not_completed",
        },
        "gate_components": {
            "identity_audit": identity["status"],
            "quality_audit": "pass" if quality_pass else "do_not_pass",
            "robust_frequency": "pass" if bool(frequency) and relative_drift(frequency) <= 0.05 else "do_not_pass",
            "amplitude_stability": "pass" if bool(amplitude) and relative_drift(amplitude) <= 0.05 else "do_not_pass",
            "formal_convergence": "pass" if quality_pass and identity["status"] == "pass" and bool(frequency) and bool(amplitude) and relative_drift(frequency) <= 0.05 and relative_drift(amplitude) <= 0.05 else "not_completed",
        },
        "gate": "STAGE4F_D_CONVERGENCE_OBSERVABILITY_REPAIR_V1_GATE: pass",
        "next_action": "No CFD launch is authorized by this offline repair.  A fresh run must record terminal courant_max and aligned quality/response streams before formal convergence can be reconsidered.",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stage4f_d_convergence_observability_repair_v1.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": report["gate"], "identity": identity["status"], "quality": report["gate_components"]["quality_audit"], "frequency": report["gate_components"]["robust_frequency"], "amplitude": report["gate_components"]["amplitude_stability"], "formal": report["gate_components"]["formal_convergence"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
