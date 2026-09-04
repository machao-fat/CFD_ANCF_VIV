"""Offline audit for a true step-0 three-slice initialization.

This script is deliberately read-only with respect to existing cases and
evidence.  It records whether a physically matching CFD field set and ANCF
state are available before any real continuation is authorized.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[2]
RESULTS = PROJECT / "results/234_cpp_worker_to70s_fresh_initialization_audit_v1"
DOCS = PROJECT / "docs/234_cpp_worker_to70s_fresh_initialization_audit_v1"
TARGET_CONFIG = (
    PROJECT
    / "cases/openfoam/stage4f_c_case_initialization_repair_v1/C/cases/slice_0000"
    / "multi_slice_case_config.json"
)
SOURCE_CHECKPOINT = (
    PROJECT
    / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints"
    / "checkpoint_step00000559_22277fd2c60d.json"
)
TARGET_TEMPLATE = PROJECT / "cases/openfoam/cpp_worker_persistent_ipc_v1/real_confirm_001"
MISMATCHED_CANDIDATE = (
    PROJECT / "cases/openfoam/stage4f_lowre_three_slice_preflight/run_20260817_retry1/cases"
)

REQUIRED_FIELDS = ("U", "Uf", "meshPhi", "p", "phi")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes().decode("utf-8"))


def field_audit(case_root: Path, time_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sid in range(3):
        directory = case_root / f"slice_{sid:04d}" / time_name
        files = {name: (directory / name).is_file() for name in REQUIRED_FIELDS}
        rows.append(
            {
                "slice_id": sid,
                "directory": str(directory),
                "fields": files,
                "complete": all(files.values()),
            }
        )
    return rows


def process_audit() -> dict[str, Any]:
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", "Get-Process | Select-Object Id,ProcessName | ConvertTo-Json -Compress"],
            text=True,
            stderr=subprocess.STDOUT,
        )
        processes = json.loads(raw) if raw.strip() else []
        if isinstance(processes, dict):
            processes = [processes]
    except Exception as exc:  # pragma: no cover - platform fallback
        return {"query": "failed", "error": str(exc), "matching_processes": []}
    matching = [
        item
        for item in processes
        if str(item.get("ProcessName", "")).lower()
        in {"matlab", "pimplefoam", "simplefoam", "foamrun", "wsl", "wsl.exe", "cfd_ancf_ancf_kernel_worker"}
    ]
    return {"query": "ok", "matching_processes": matching}


def main() -> int:
    target = read_json(TARGET_CONFIG)
    checkpoint = read_json(SOURCE_CHECKPOINT)
    source_structure = checkpoint.get("structure", {})
    source_mapping = {
        "step": checkpoint.get("step", checkpoint.get("global_step")),
        "time_s": checkpoint.get("time_s"),
        "tick": checkpoint.get("time_tick", checkpoint.get("integer_tick")),
        "committed": checkpoint.get("status") == "committed" or checkpoint.get("committed") is True,
        "q_present": "q" in source_structure,
        "qdot_present": "qdot" in source_structure,
        "qddot_present": "qddot" in source_structure,
    }
    target_physics = target.get("ancf", {})
    target_cfd = target.get("cfd", {})
    required_target = {
        "length_m": 50.0,
        "youngs_modulus_pa": 3227125779.22183,
        "top_tension_n": 2179104.00298,
        "delta_t_s": 0.00125,
        "freestream_mps": 1.0,
        "diameter_m": 1.0,
        "nu_m2ps": 0.01,
        "rho_kgpm3": 1000.0,
    }
    target_values = {
        "length_m": target_physics.get("length_m"),
        "youngs_modulus_pa": target_physics.get("youngs_modulus_pa"),
        "top_tension_n": target_physics.get("top_tension_n"),
        "delta_t_s": target.get("delta_t_s"),
        "freestream_mps": target_cfd.get("freestream_mps"),
        "diameter_m": target_cfd.get("diameter_m"),
        "nu_m2ps": target_cfd.get("nu_m2ps"),
        "rho_kgpm3": target_cfd.get("rho_kgpm3"),
    }
    matching_contract = all(
        value is not None
        and abs(float(value) - expected) <= max(1e-9, abs(expected) * 1e-9)
        for key, expected in required_target.items()
        for value in [target_values[key]]
    )

    source_time = "2.2075"
    template_current = field_audit(TARGET_TEMPLATE, source_time)
    template_step0 = field_audit(TARGET_TEMPLATE, "0")
    mismatched_step0 = field_audit(MISMATCHED_CANDIDATE, "0")
    mismatch_config = read_json(MISMATCHED_CANDIDATE / "slice_0000/multi_slice_case_config.json")
    mismatch_physics = mismatch_config.get("ancf", {})
    mismatch_values = {
        "length_m": mismatch_physics.get("length_m"),
        "youngs_modulus_pa": mismatch_physics.get("youngs_modulus_pa"),
        "top_tension_n": mismatch_physics.get("top_tension_n"),
        "delta_t_s": mismatch_config.get("delta_t_s"),
    }
    candidate_is_matching = all(
        row["complete"] for row in mismatched_step0
    ) and all(
        value is not None
        and abs(float(value) - required_target[key]) <= max(1e-9, abs(required_target[key]) * 1e-9)
        for key, value in mismatch_values.items()
    )

    evidence = {
        "stage_id": "stage4f_d_cpp_worker_to70s_fresh_initialization_audit_v1",
        "gate": "STAGE4F_D_CPP_WORKER_TO70S_FRESH_INITIALIZATION_AUDIT_V1_GATE: do_not_pass",
        "status": "do_not_pass",
        "reason": "no physically matching true step-0 CFD field set is available",
        "source_checkpoint": {
            "path": str(SOURCE_CHECKPOINT),
            "sha256": sha256(SOURCE_CHECKPOINT),
            **source_mapping,
        },
        "target_contract": {
            "path": str(TARGET_CONFIG),
            "values": target_values,
            "expected": required_target,
            "matching_contract": matching_contract,
        },
        "required_initialization": {
            "physical_time_s": 0.0,
            "step": 0,
            "tick": 0,
            "required_fields": list(REQUIRED_FIELDS),
            "slices": 3,
        },
        "target_template_fields": {
            "source_time_2_2075": template_current,
            "step0": template_step0,
        },
        "mismatched_candidate": {
            "root": str(MISMATCHED_CANDIDATE),
            "config_values": mismatch_values,
            "step0_fields": mismatched_step0,
            "matching_target_contract": candidate_is_matching,
        },
        "ancf_restart_requirement": {
            "q": source_mapping["q_present"],
            "qdot": source_mapping["qdot_present"],
            "qddot": source_mapping["qddot_present"],
            "true_t0_state_available": False,
        },
        "process_audit": process_audit(),
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "old_evidence_modified": False,
        "stage233_runtime_reused": False,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    (RESULTS / "fresh_initialization_audit.json").write_bytes(payload.encode("utf-8"))
    report = "# Fresh step-0 initialization audit\n\n"
    report += "- Gate: `STAGE4F_D_CPP_WORKER_TO70S_FRESH_INITIALIZATION_AUDIT_V1_GATE: do_not_pass`\n"
    report += "- No real MATLAB/OpenFOAM/WSL/CFD process was started.\n"
    report += "- The accepted step 559 checkpoint is `2.2075 s`, not physical `t=0`.\n"
    report += "- The target 50 m, `dt=0.00125` template lacks `U/Uf/meshPhi/p/phi` at both `0` and `2.2075`.\n"
    report += "- The only complete step-0 candidate has a different 10 m/`dt=0.0025` contract and is rejected.\n"
    report += "\nA fresh run requires a matched t=0 CFD field set and matching ANCF `q/qdot/qddot`; no continuation is authorized until those artifacts are produced and audited.\n"
    (DOCS / "fresh_initialization_audit_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"gate": evidence["gate"], "results": str(RESULTS), "process_starts": evidence["real_process_starts"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
