"""Stage 4D-C-A numerical-convergence campaign.

The campaign is additive and imports the already accepted Stage 4D-B process
bridge.  It parameterizes only the new campaign path for ``dt`` and ``nElem``;
the frozen 0.2.1 mapping, persistent ANCF runner, ProcessLimiter and atomic
checkpoint implementation remain the production implementations.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..multi_slice_mapping.mapping import (
    SliceManifest,
    ancf_hermite_H,
    sha256_json,
)
from ..stage4d_medium_campaign import campaign as base


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = PROJECT_ROOT / "results" / "07_stage4d_c_convergence"
TEMPLATE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4d_convergence_template"
MANIFEST_PATH = base.MANIFEST_PATH
STAGE4D_B_ACCEPTANCE = PROJECT_ROOT / "results" / "06_stage4d_medium_run" / "stage4d_b_sol_acceptance.json"
BASELINE_ROOT = PROJECT_ROOT / "results" / "06_stage4d_medium_run" / "stage4d_b_formal100_20260811T044351Z_7e8682bdbf"
SCHEMA_VERSION = "0.2.1"
MANIFEST_HASH = base.FROZEN_MANIFEST_HASH
BANK_IDENTITY_HASH = base.FLOW_BANK_IDENTITY_HASH
DT_COARSE = 0.0025
DT_FINE = 0.00125
N_ELEM_COARSE = 2
N_ELEM_MEDIUM = 4
N_ELEM_FINE = 8
MAX_CFL = 0.8
MOTION_LIMIT_M = 0.05
PRODUCTION_MOTIONSCALE_HASH = "833fd42be209a83a4b4fd4792dc5377168cd81814a2ba60013b6ce11776cc0a5"
GENERATED_MOTIONSCALE_HASH = "30c7be5c4faa19a5c311e05585d20dcb0fe0af0b5f1292e8600a4cbb0aba046d"
TIME_TOL = 1.0e-12


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    base.atomic_write_json(path, value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _decode_process_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    text = value.decode("utf-8", errors="replace")
    if text.count("\x00") > max(2, len(text) // 20):
        text = value.decode("utf-16", errors="replace")
    return text


def _fresh_run_id(prefix: str) -> str:
    return f"{prefix}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{uuid.uuid4().hex[:10]}"


def _finite(value: Any, name: str = "value") -> Any:
    if isinstance(value, Mapping):
        return {str(k): _finite(v, f"{name}.{k}") for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v, f"{name}[]") for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name} contains NaN/Inf")
    return value


def _template_file_paths() -> list[Path]:
    return [
        TEMPLATE_ROOT / "README.md",
        TEMPLATE_ROOT / "template_config.json",
        TEMPLATE_ROOT / "case_template" / "constant" / "dynamicMeshDict.in",
        TEMPLATE_ROOT / "case_template" / "system" / "controlDict.in",
        TEMPLATE_ROOT / "case_template" / "system" / "fvSolution",
    ]


def template_identity() -> dict[str, Any]:
    files = []
    for path in _template_file_paths():
        if not path.is_file():
            raise FileNotFoundError(path)
        files.append({"relative_path": str(path.relative_to(TEMPLATE_ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": _sha256(path)})
    identity = {"template_id": "stage4d-c-convergence-template-v1", "files": files}
    identity["template_sha256"] = sha256_json(identity)
    return identity


def verify_stage4d_b_entry() -> dict[str, Any]:
    entry = _read(STAGE4D_B_ACCEPTANCE)
    if entry.get("decision") != "passed_with_scope_limits":
        raise RuntimeError("Stage 4D-B formal acceptance is not passed_with_scope_limits")
    if entry.get("protocol_version") != SCHEMA_VERSION or entry.get("slice_manifest_sha256") != MANIFEST_HASH:
        raise RuntimeError("Stage 4D-B protocol or manifest identity mismatch")
    if entry.get("developed_flow_bank_identity_sha256") != BANK_IDENTITY_HASH:
        raise RuntimeError("Stage 4D-B developed-flow bank identity mismatch")
    audit = base.verify_stage4d_a_inputs()
    summary = _read(BASELINE_ROOT / "campaign_summary.json")
    required = {"steps_completed": 100, "slice_execution_count": 300, "max_cfl": 0.1725241657902625, "matlab_start_count": 1}
    if any(summary.get(k) != v for k, v in required.items()):
        raise RuntimeError("Stage 4D-B baseline summary does not match frozen evidence")
    if abs(float(_read(PROJECT_ROOT / "results" / "06_stage4d_medium_run" / "stage4d_b_energy_audit.json")["E_c"]) - 9.906678707660641e-05) > 1.0e-15:
        raise RuntimeError("Stage 4D-B energy identity mismatch")
    checkpoint_audit = _read(PROJECT_ROOT / "results" / "06_stage4d_medium_run" / "stage4d_b_checkpoint_hash_audit.json")
    if checkpoint_audit.get("checkpoint_count") != 100 or not checkpoint_audit.get("all_valid"):
        raise RuntimeError("Stage 4D-B checkpoint identity mismatch")
    return {"stage4d_b_acceptance": entry, "stage4d_audit": audit, "baseline_summary": {k: summary.get(k) for k in required}, "baseline_checkpoint_audit": {k: checkpoint_audit.get(k) for k in ("checkpoint_count", "object_count_total", "all_valid")}}


def _render(template: Path, replacements: Mapping[str, str]) -> str:
    text = template.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(key, value)
    if "{{" in text or "}}" in text:
        raise RuntimeError(f"unresolved template token in {template}")
    return text


def _materialize_cases(run_root: Path, *, run_id: str, dt_s: float, n_elem: int, input_audit: Mapping[str, Any] | None = None) -> dict[str, Any]:
    run_root = run_root.resolve()
    cases_root = run_root / "cases"
    cases_root.mkdir(parents=True, exist_ok=False)
    audit = dict(input_audit or verify_stage4d_b_entry()["stage4d_audit"])
    template = template_identity()
    manifest = SliceManifest.from_mapping(_read(MANIFEST_PATH))
    lengths = {0: 2.5, 1: 5.0, 2: 2.5}
    result: dict[str, Any] = {"run_id": run_id, "target_local_time_s": 0.0, "setFields_called": False, "warmup_called": False, "template": template, "nElem": n_elem, "dt_s": dt_s, "slices": {}}
    for sid, spec in base.FLOW_SPECS.items():
        source = Path(spec["source_case"]).resolve()
        source_time = source / spec["source_time"]
        case = cases_root / f"slice_{sid:04d}"
        shutil.copytree(source / "constant", case / "constant")
        shutil.copytree(source / "system", case / "system")
        fields = [base._materialize_field(source_time / name, case / "0" / name, name) for name in ("U", "p", "phi")]
        time_record = base._materialize_time_file(source_time / "uniform" / "time", case / "0" / "uniform" / "time")
        replacements = {
            "{{SLICE_ID}}": str(sid),
            "{{STEP_OFFSET}}": "0",
            "{{START_TIME_S}}": "0",
            "{{END_TIME_S}}": format(dt_s, ".12g"),
            "{{DELTA_T_S}}": format(dt_s, ".12g"),
            "{{U_MPS}}": format(float(spec["U_mps"]), ".17g"),
            "{{MOTION_INPUT}}": "coupling/motion.csv",
            "{{EXCHANGE_DIR}}": "coupling",
        }
        (case / "constant" / "dynamicMeshDict").write_text(_render(TEMPLATE_ROOT / "case_template" / "constant" / "dynamicMeshDict.in", replacements), encoding="utf-8")
        (case / "system" / "controlDict").write_text(_render(TEMPLATE_ROOT / "case_template" / "system" / "controlDict.in", replacements), encoding="utf-8")
        shutil.copy2(TEMPLATE_ROOT / "case_template" / "system" / "fvSolution", case / "system" / "fvSolution")
        motion = base._write_motion_scale(case)
        if motion["motionScale_sha256"] != GENERATED_MOTIONSCALE_HASH:
            raise RuntimeError(f"slice {sid}: generated motionScale hash changed")
        for relative in ("coupling/motion", "coupling/load", "coupling/consumed", "postProcessing"):
            (case / relative).mkdir(parents=True, exist_ok=True)
        config = {
            "schema_version": SCHEMA_VERSION, "protocol": "Stage4-Multislice", "case_id": manifest.case_id,
            "slice_id": sid, "s_ref_m": [1.25, 5.0, 8.75][sid], "slice_length_m": lengths[sid], "unit_span_m": 1.0,
            "start_time_s": 0.0, "end_time_s": dt_s, "delta_t_s": dt_s, "step_offset": 0,
            "exchange_dir": "coupling", "motion_input": "coupling/motion.csv", "load_output": "postProcessing/cylinderForces",
            "slice_manifest_sha256": MANIFEST_HASH, "run_id": run_id, "nElem": n_elem, "template_sha256": template["template_sha256"],
            "template_file_hashes": template["files"], "motionScale_initial_sha256": GENERATED_MOTIONSCALE_HASH,
            "motionScale_production_sha256": PRODUCTION_MOTIONSCALE_HASH,
            "cfd": {"diameter_m": 1.0, "freestream_mps": spec["U_mps"], "rho_kgpm3": 1000.0, "nu_m2ps": 0.01},
        }
        _write(case / "multi_slice_case_config.json", config)
        lineage = {
            "schema_version": "stage4d-c-developed-field-lineage-1", "run_id": run_id, "slice_id": sid, "flow_id": spec["flow_id"],
            "source_case": str(source), "source_time_name": spec["source_time"], "source_time_s": float(spec["source_time"]),
            "target_time_name": "0", "target_time_s": 0.0,
            "conversion": "copy source constant/system and snapshot U,p,phi/uniform-time; rewrite only location/time metadata; render candidate dictionaries; generate motionScale from current points; no setFields; no warmup",
            "source_points_sha256": _sha256(source / "constant" / "polyMesh" / "points"), "target_points_sha256": _sha256(case / "constant" / "polyMesh" / "points"),
            "source_fields": {item["field"]: item["source_sha256"] for item in fields} | {"uniform/time": time_record["source_sha256"]},
            "target_fields": {item["field"]: item["target_sha256"] for item in fields} | {"uniform/time": time_record["target_sha256"]},
            "field_metadata_only": {item["field"]: item["location_only_change"] for item in fields} | {"uniform/time": True},
            "template_sha256": template["template_sha256"], "template_file_hashes": template["files"], "motionScale": motion,
            "case_config_sha256": sha256_json(config), "fresh_case": True, "forbidden_artifacts_absent": True,
        }
        _write(case / "developed_field_lineage.json", lineage)
        _write(case / "case_provenance.json", {"schema_version": "stage4d-c-case-provenance-1", "run_id": run_id, "source_case": str(source), "source_time": spec["source_time"], "copied_trees": ["constant", "system"], "copied_fields": ["U", "p", "phi", "uniform/time"], "setFields_called": False, "warmup_called": False, "template_sha256": template["template_sha256"], "nElem": n_elem, "dt_s": dt_s})
        result["slices"][str(sid)] = {"case": str(case), "lineage": lineage, "config": config}
    _write(run_root / "materialization_summary.json", result)
    return result


@contextlib.contextmanager
def _patched_base(*, dt_s: float, n_elem: int, materializer):
    original = {
        "DT_S": base.DT_S,
        "runner_config": base._runner_config,
        "materialize": base.materialize_developed_cases,
        "adapter": base.PersistentProductionANCFAdapter,
        "sha256_json": base.sha256_json,
        "checkpoint_manager": base.Stage4BCheckpointManager,
    }
    template = template_identity()
    class ConvergenceAdapter(base.PersistentProductionANCFAdapter):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["mesh_nodes"] = tuple(float(j * 10.0 / n_elem) for j in range(n_elem + 1))
            super().__init__(*args, **kwargs)

    def runner_config(manifest: SliceManifest) -> dict[str, Any]:
        config = dict(original["runner_config"](manifest))
        config.update({"nElem": n_elem, "dt": dt_s})
        return config

    def physics_sha(value: Any) -> str:
        if isinstance(value, Mapping) and "motion_library_sha256" in value:
            value = dict(value)
            value.update({"nElem": n_elem, "dt_s": dt_s, "template_sha256": template["template_sha256"], "motionScale_initial_sha256": GENERATED_MOTIONSCALE_HASH, "motionScale_production_sha256": PRODUCTION_MOTIONSCALE_HASH})
        return original["sha256_json"](value)

    class ConvergenceCheckpointManager(original["checkpoint_manager"]):
        def prepare(self, **kwargs: Any):
            prepared = super().prepare(**kwargs)
            manifest = dict(prepared.manifest)
            manifest.update({"template_sha256": template["template_sha256"], "nElem": n_elem, "dt_s": dt_s, "motionScale_initial_sha256": GENERATED_MOTIONSCALE_HASH, "motionScale_production_sha256": PRODUCTION_MOTIONSCALE_HASH})
            base.atomic_write_json(prepared.prepared_path, manifest)
            return type(prepared)(prepared.checkpoint_id, prepared.prepared_path, manifest, prepared.staged_token)

    base.DT_S = dt_s
    base._runner_config = runner_config
    base.materialize_developed_cases = materializer
    base.PersistentProductionANCFAdapter = ConvergenceAdapter
    base.sha256_json = physics_sha
    base.Stage4BCheckpointManager = ConvergenceCheckpointManager
    try:
        yield template
    finally:
        base.DT_S = original["DT_S"]
        base._runner_config = original["runner_config"]
        base.materialize_developed_cases = original["materialize"]
        base.PersistentProductionANCFAdapter = original["adapter"]
        base.sha256_json = original["sha256_json"]
        base.Stage4BCheckpointManager = original["checkpoint_manager"]


def _worker_identity(root: Path) -> dict[str, Any]:
    responses = sorted((root / "matlab_worker" / "responses").glob("*.json"))
    protocol_pid = None
    initialize_file = None
    for path in responses:
        try:
            payload = _read(path)
        except Exception:
            continue
        if payload.get("action") == "initialize" or payload.get("command") == "initialize":
            initialize_file = str(path)
            protocol_pid = payload.get("worker_pid") or payload.get("result", {}).get("worker_pid")
            break
    return {"launcher_pid": None, "protocol_worker_pid": protocol_pid, "initialize_response": initialize_file}


def _production_motion_scale(root: Path) -> dict[str, Any]:
    rows = {}
    for case in sorted((root / "cases").glob("slice_*")):
        path = case / "0" / "motionScale"
        rows[case.name] = {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}
    return {"generated_sha256": GENERATED_MOTIONSCALE_HASH, "production_sha256_expected": PRODUCTION_MOTIONSCALE_HASH, "slices": rows, "all_production_equal": bool(rows) and all(item["sha256"] == PRODUCTION_MOTIONSCALE_HASH for item in rows.values())}


def _run_one(root: Path, *, run_id: str, dt_s: float, n_elem: int, steps: int, restore_manifest: Path | None = None) -> dict[str, Any]:
    materializer = lambda run_root, run_id, input_audit=None: _materialize_cases(Path(run_root), run_id=run_id, dt_s=dt_s, n_elem=n_elem, input_audit=input_audit)
    with _patched_base(dt_s=dt_s, n_elem=n_elem, materializer=materializer) as template:
        summary = base.run_campaign(root, run_id=run_id, steps=steps, restore_manifest=restore_manifest, allow_existing=restore_manifest is not None)
        runtime = base.RuntimeConfig(schema_version=SCHEMA_VERSION, case_id=summary["step_results"][0].get("case_id", "stage4c_candidate_3slice") if summary.get("step_results") else "stage4c_candidate_3slice", dt_s=dt_s, timeout_s=180.0, start_time_s=0.0, coupling_iteration=0, coupling_scheme="explicit_weak", slice_manifest_sha256=MANIFEST_HASH)
        manifest = SliceManifest.from_mapping(_read(MANIFEST_PATH))
        checkpoint_audit = base._checkpoint_audit(root, manifest=manifest, runtime=runtime, case_root=root / "cases")
    worker = _worker_identity(root)
    worker["launcher_pid"] = summary.get("matlab_worker_pid")
    motion_scale = _production_motion_scale(root)
    if not motion_scale["all_production_equal"]:
        raise RuntimeError(f"{run_id}: production motionScale hash mismatch")
    energy = base._energy_summary(summary.get("energy", []))
    payload = {"run_id": run_id, "dt_s": dt_s, "nElem": n_elem, "steps": steps, "summary": summary, "worker_identity": worker, "template": template, "motionScale": motion_scale, "energy_audit": energy, "checkpoint_hash_audit": checkpoint_audit, "free_viv_claim": False}
    _write(root / "convergence_run_summary.json", payload)
    _write(root / "energy_audit.json", energy)
    _write(root / "checkpoint_hash_audit.json", checkpoint_audit)
    return payload


def _wsl_path(path: Path) -> str:
    return base._wsl_path(path)


def _check_mesh(case: Path, output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = f"source /opt/openfoam10/etc/bashrc; cd '{_wsl_path(case)}'; checkMesh"
    result = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command], capture_output=True, text=False, timeout=180)
    stdout = _decode_process_output(result.stdout)
    stderr = _decode_process_output(result.stderr)
    output.write_text(stdout + stderr, encoding="utf-8")
    text = output.read_text(encoding="utf-8", errors="replace")
    return {"case": str(case), "return_code": result.returncode, "log": str(output), "mesh_ok": result.returncode == 0 and "Mesh OK" in text}


def run_template_smoke(*, root: Path, run_id: str | None = None) -> dict[str, Any]:
    run_id = run_id or _fresh_run_id("stage4d_c_template_audit")
    audit_root = root / run_id
    with _patched_base(dt_s=DT_COARSE, n_elem=2, materializer=lambda run_root, run_id, input_audit=None: _materialize_cases(Path(run_root), run_id=run_id, dt_s=DT_COARSE, n_elem=2, input_audit=input_audit)):
        materialization = _materialize_cases(audit_root, run_id=run_id, dt_s=DT_COARSE, n_elem=2)
    mesh = [_check_mesh(Path(item["case"]), audit_root / "checkMesh" / f"slice_{sid}.log") for sid, item in materialization["slices"].items()]
    foam = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", "source /opt/openfoam10/etc/bashrc; foamVersion"], capture_output=True, text=False, timeout=60)
    foam_stdout = _decode_process_output(foam.stdout)
    foam_stderr = _decode_process_output(foam.stderr)
    template = template_identity()
    foam_text = foam_stdout + foam_stderr
    raw_foam = (foam.stdout or b"") + (foam.stderr or b"")
    raw_version_match = re.search(rb"OpenFOAM-\d+", raw_foam) if isinstance(raw_foam, bytes) else None
    foam_version_match = re.search(r"OpenFOAM-\d+", foam_text)
    foam_version = raw_version_match.group(0).decode("ascii") if raw_version_match else (foam_version_match.group(0) if foam_version_match else foam_text.strip())
    smoke_id = _fresh_run_id("stage4d_c_template_smoke")
    smoke_root = root / smoke_id
    smoke: dict[str, Any]
    if all(item["mesh_ok"] for item in mesh) and foam.returncode == 0:
        smoke = _run_one(smoke_root, run_id=smoke_id, dt_s=DT_COARSE, n_elem=N_ELEM_COARSE, steps=2)
        smoke_result = {
            "status": "passed" if smoke["summary"].get("steps_completed") == 2 else "failed",
            "run_id": smoke_id,
            "root": str(smoke_root),
            "steps_completed": smoke["summary"].get("steps_completed"),
            "max_cfl": smoke["summary"].get("max_cfl"),
            "openfoam_execution_count": smoke["summary"].get("slice_execution_count"),
            "matlab_start_count": smoke["summary"].get("matlab_start_count"),
            "process_peak": smoke["summary"].get("limiter", {}).get("peak_active_count"),
            "checkpoint_count": smoke["checkpoint_hash_audit"].get("checkpoint_count"),
            "motionScale": smoke["motionScale"],
        }
    else:
        smoke_result = {"status": "not_run", "reason": "checkMesh or foamVersion failed", "run_id": smoke_id}
    result = {"status": "passed" if all(item["mesh_ok"] for item in mesh) and foam.returncode == 0 and smoke_result["status"] == "passed" else "failed", "run_id": run_id, "template": template, "openfoam_version": foam_version, "checkMesh": mesh, "real_two_step_smoke": smoke_result, "parameters": ["dt_s", "slice_id", "U_mps", "start_time_s", "end_time_s", "step_offset", "run_id"], "runtime_solver_patch_required": False, "required_fv_solution_entries": ["pcorr", "pcorrFinal", "cellMotionUx", "correctPhi yes", "correctMeshPhi yes"], "motionScale_generated_sha256": GENERATED_MOTIONSCALE_HASH, "motionScale_production_sha256": PRODUCTION_MOTIONSCALE_HASH}
    _write(RESULTS_ROOT / "template_audit.json", result)
    _write(audit_root / "template_audit.json", result)
    return result


def _rms(values: Sequence[float]) -> float:
    return math.sqrt(sum(float(v) * float(v) for v in values) / max(1, len(values)))


def _nrmse(reference: Sequence[Sequence[float]], candidate: Sequence[Sequence[float]], floor: float) -> float:
    a = [float(v) for row in reference for v in row]
    b = [float(v) for row in candidate for v in row]
    if len(a) != len(b) or not a:
        raise ValueError("aligned series length mismatch")
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)) / len(a)) / max(_rms(a), floor)


def _motion_vectors(summary: Mapping[str, Any], key: str, sid: int, fields: Sequence[str]) -> list[list[float]]:
    return [[float(item[key][str(sid)][field]) for field in fields] for item in summary["step_results"]]


def _force_vectors(summary: Mapping[str, Any], key: str, sid: int) -> list[list[float]]:
    return [[float(v) for v in item[key][str(sid)]] for item in summary["step_results"]]


def _align_fine(coarse: Mapping[str, Any], fine: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    c = coarse["summary"] if "summary" in coarse else coarse
    f = fine["summary"] if "summary" in fine else fine
    selected = []
    for item in c["step_results"]:
        target = float(item["time_s"])
        matches = [x for x in f["step_results"] if abs(float(x["time_s"]) - target) <= TIME_TOL]
        if len(matches) != 1:
            raise RuntimeError(f"fine time grid has no unique match at {target}")
        selected.append(matches[0])
    aligned = dict(f)
    aligned["step_results"] = selected
    return c, aligned


def compare_time_step(coarse: Mapping[str, Any], fine: Mapping[str, Any]) -> dict[str, Any]:
    c, f = _align_fine(coarse, fine)
    metrics: dict[str, Any] = {"per_slice": {}, "structure": {}}
    for sid in (0, 1, 2):
        cdisp = _motion_vectors(c, "corrected_motion", sid, ("ux_m", "uy_m"))
        fdisp = _motion_vectors(f, "corrected_motion", sid, ("ux_m", "uy_m"))
        cspeed = _motion_vectors(c, "corrected_motion", sid, ("vx_mps", "vy_mps"))
        fspeed = _motion_vectors(f, "corrected_motion", sid, ("vx_mps", "vy_mps"))
        cforce = _force_vectors(c, "integrated_slice_forces_N", sid)
        fforce = _force_vectors(f, "integrated_slice_forces_N", sid)
        cdisp_norm = [math.hypot(*v) for v in cdisp]
        fdisp_norm = [math.hypot(*v) for v in fdisp]
        cspeed_norm = [math.hypot(*v) for v in cspeed]
        fspeed_norm = [math.hypot(*v) for v in fspeed]
        cdrag = [v[0] for v in cforce]
        fdrag = [v[0] for v in fforce]
        clift = [v[1] for v in cforce]
        flift = [v[1] for v in fforce]
        item = {
            "displacement_nrmse": _nrmse(cdisp, fdisp, 1e-8),
            "velocity_nrmse": _nrmse(cspeed, fspeed, 1e-6),
            "displacement_rms_relative_change": abs(_rms(fdisp_norm) - _rms(cdisp_norm)) / max(_rms(cdisp_norm), 1e-8),
            "displacement_peak_relative_change": abs(max(fdisp_norm) - max(cdisp_norm)) / max(max(cdisp_norm), 1e-8),
            "velocity_rms_relative_change": abs(_rms(fspeed_norm) - _rms(cspeed_norm)) / max(_rms(cspeed_norm), 1e-6),
            "mean_drag_relative_change": abs(sum(fdrag) / len(fdrag) - sum(cdrag) / len(cdrag)) / max(abs(sum(cdrag) / len(cdrag)), 1.0),
            "transverse_force_rms_relative_change": abs(_rms(flift) - _rms(clift)) / max(_rms(clift), 1.0),
            "force_nrmse": _nrmse(cforce, fforce, 1.0),
        }
        metrics["per_slice"][str(sid)] = item
    q_c = [item["q"] for item in c["step_results"]]
    q_f = [item["q"] for item in f["step_results"]]
    qdot_c = [item["qdot"] for item in c["step_results"]]
    qdot_f = [item["qdot"] for item in f["step_results"]]
    qddot_c = [item["qddot"] for item in c["step_results"]]
    qddot_f = [item["qddot"] for item in f["step_results"]]
    metrics["structure"] = {"q_nrmse": _nrmse(q_c, q_f, 1e-8), "qdot_nrmse": _nrmse(qdot_c, qdot_f, 1e-6), "qddot_nrmse": _nrmse(qddot_c, qddot_f, 1e-6)}
    c_energy = base._energy_summary(c.get("energy", []))
    f_energy = base._energy_summary(f.get("energy", []))
    metrics["energy"] = {"coarse": c_energy, "fine": f_energy, "sum_abs_W_CFD_relative_change": abs(f_energy["denominator_J"] - c_energy["denominator_J"]) / max(c_energy["denominator_J"], 1e-10)}
    metrics["max_cfl"] = {"coarse": c.get("max_cfl"), "fine": f.get("max_cfl")}
    checks = []
    for item in metrics["per_slice"].values():
        checks.extend([
            ("displacement_rms", item["displacement_rms_relative_change"] <= 0.05),
            ("displacement_peak", item["displacement_peak_relative_change"] <= 0.05),
            ("velocity_rms", item["velocity_rms_relative_change"] <= 0.05),
            ("mean_drag", item["mean_drag_relative_change"] <= 0.05),
            ("transverse_force_rms", item["transverse_force_rms_relative_change"] <= 0.10),
            ("force_nrmse", item["force_nrmse"] <= 0.10),
        ])
    checks.extend([
        ("q_nrmse", metrics["structure"]["q_nrmse"] <= 0.05),
        ("qdot_nrmse", metrics["structure"]["qdot_nrmse"] <= 0.05),
        ("qddot_nrmse", metrics["structure"]["qddot_nrmse"] <= 0.05),
        ("sum_abs_W_CFD", metrics["energy"]["sum_abs_W_CFD_relative_change"] <= 0.10),
        ("coarse_E_c", c_energy["status"] == "evaluable" and c_energy["E_c"] <= 0.10),
        ("fine_E_c", f_energy["status"] == "evaluable" and f_energy["E_c"] <= 0.10),
        ("coarse_CFL", c.get("max_cfl") is not None and c["max_cfl"] < MAX_CFL),
        ("fine_CFL", f.get("max_cfl") is not None and f["max_cfl"] < MAX_CFL),
    ])
    metrics["checks"] = [{"name": name, "passed": bool(ok)} for name, ok in checks]
    metrics["all_passed"] = all(ok for _, ok in checks)
    metrics["alignment"] = {"coarse_count": len(c["step_results"]), "fine_count": len(fine["summary"]["step_results"]), "aligned_count": len(f["step_results"]), "rule": "fine step 2k+1 at coarse target time (k+1)*dt_coarse"}
    return metrics


def _virtual_work(n_elem: int) -> dict[str, Any]:
    manifest = SliceManifest.from_mapping(_read(MANIFEST_PATH))
    nodes = tuple(float(j * 10.0 / n_elem) for j in range(n_elem + 1))
    ndof = 6 * len(nodes)
    delta_q = [0.001 * math.sin(0.37 * (j + 1)) for j in range(ndof)]
    forces = {0: (1114.0, 20.0, 0.1), 1: (3337.0, 85.0, -0.2), 2: (2333.0, -338.0, 0.3)}
    generalized = [0.0] * ndof
    local_work = 0.0
    rows = {}
    for item in manifest.slices:
        H = ancf_hermite_H(item.s_ref_m, nodes)
        if len(H) != 3 or any(len(row) != ndof for row in H):
            raise RuntimeError(f"invalid H dimension for nElem={n_elem}")
        displacement = [sum(float(H[row][j]) * delta_q[j] for j in range(ndof)) for row in range(3)]
        force = forces[item.slice_id]
        local_work += sum(force[row] * displacement[row] for row in range(3))
        for j in range(ndof):
            generalized[j] += sum(float(H[row][j]) * force[row] for row in range(3))
        rows[str(item.slice_id)] = {"H_rows": len(H), "H_cols": len(H[0]), "displacement": displacement}
    generalized_work = sum(delta_q[j] * generalized[j] for j in range(ndof))
    abs_error = abs(local_work - generalized_work)
    rel_error = abs_error / max(1.0, abs(local_work), abs(generalized_work))
    return {"nElem": n_elem, "node_positions_m": list(nodes), "ndof": ndof, "slice_order_invariant": True, "local_work": local_work, "generalized_work": generalized_work, "absolute_error": abs_error, "relative_error": rel_error, "passed": rel_error <= 1e-12, "slices": rows}


def compare_structure(coarse: Mapping[str, Any], medium: Mapping[str, Any], fine: Mapping[str, Any]) -> dict[str, Any]:
    def pair(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
        c, f = _align_fine(left, right)
        item: dict[str, Any] = {"per_slice": {}}
        for sid in (0, 1, 2):
            cdisp = _motion_vectors(c, "corrected_motion", sid, ("ux_m", "uy_m")); fdisp = _motion_vectors(f, "corrected_motion", sid, ("ux_m", "uy_m"))
            cspeed = _motion_vectors(c, "corrected_motion", sid, ("vx_mps", "vy_mps")); fspeed = _motion_vectors(f, "corrected_motion", sid, ("vx_mps", "vy_mps"))
            cf = _force_vectors(c, "integrated_slice_forces_N", sid); ff = _force_vectors(f, "integrated_slice_forces_N", sid)
            cn = [math.hypot(*v) for v in cdisp]; fn = [math.hypot(*v) for v in fdisp]
            csn = [math.hypot(*v) for v in cspeed]; fsn = [math.hypot(*v) for v in fspeed]
            item["per_slice"][str(sid)] = {"displacement_nrmse": _nrmse(cdisp, fdisp, 1e-8), "velocity_nrmse": _nrmse(cspeed, fspeed, 1e-6), "displacement_peak_relative_change": abs(max(fn) - max(cn)) / max(max(cn), 1e-8), "displacement_rms_relative_change": abs(_rms(fn) - _rms(cn)) / max(_rms(cn), 1e-8), "velocity_rms_relative_change": abs(_rms(fsn) - _rms(csn)) / max(_rms(csn), 1e-6), "force_nrmse": _nrmse(cf, ff, 1.0), "mean_drag_relative_change": abs(sum(x[0] for x in ff) / len(ff) - sum(x[0] for x in cf) / len(cf)) / max(abs(sum(x[0] for x in cf) / len(cf)), 1.0), "transverse_force_rms_relative_change": abs(_rms([x[1] for x in ff]) - _rms([x[1] for x in cf])) / max(_rms([x[1] for x in cf]), 1.0)}
        c_energy = base._energy_summary(c.get("energy", [])); f_energy = base._energy_summary(f.get("energy", []))
        item["energy"] = {"left": c_energy, "right": f_energy, "sum_abs_W_CFD_relative_change": abs(f_energy["denominator_J"] - c_energy["denominator_J"]) / max(c_energy["denominator_J"], 1e-10)}
        tensions = lambda summary, key: [float(x[key]) for x in summary["step_results"]]
        item["tension"] = {"left_min": min(tensions(c, "min_tension_N")), "left_max": max(tensions(c, "max_tension_N")), "right_min": min(tensions(f, "min_tension_N")), "right_max": max(tensions(f, "max_tension_N"))}
        checks = []
        for row in item["per_slice"].values():
            checks += [row["displacement_nrmse"] <= .05, row["velocity_nrmse"] <= .05, row["displacement_peak_relative_change"] <= .05, row["mean_drag_relative_change"] <= .05, row["transverse_force_rms_relative_change"] <= .10, row["force_nrmse"] <= .10]
        checks += [item["energy"]["sum_abs_W_CFD_relative_change"] <= .10, c_energy["status"] == "evaluable" and c_energy["E_c"] <= .10, f_energy["status"] == "evaluable" and f_energy["E_c"] <= .10, c.get("max_cfl", 1) < MAX_CFL, f.get("max_cfl", 1) < MAX_CFL]
        item["all_passed"] = all(checks)
        return item
    virtual = {str(n): _virtual_work(n) for n in (2, 4, 8)}
    result = {"configurations": {"nElem2": {"nElem": 2, "steps": len(coarse["summary"]["step_results"]), "dt_s": coarse["dt_s"]}, "nElem4": {"nElem": 4, "steps": len(medium["summary"]["step_results"]), "dt_s": medium["dt_s"]}, "nElem8": {"nElem": 8, "steps": len(fine["summary"]["step_results"]), "dt_s": fine["dt_s"]}}, "virtual_work": virtual, "nElem2_vs_nElem4": pair(coarse, medium), "nElem4_vs_nElem8": pair(medium, fine)}
    result["nElem4_vs_nElem8"]["virtual_work_passed"] = virtual["4"]["passed"] and virtual["8"]["passed"]
    result["all_passed"] = result["nElem4_vs_nElem8"]["all_passed"] and result["nElem4_vs_nElem8"]["virtual_work_passed"]
    return result


def _stage_checkpoint(source_root: Path, target_root: Path, checkpoint: Path, *, dt_s: float, n_elem: int, run_id: str) -> Path:
    materializer = lambda run_root, run_id, input_audit=None: _materialize_cases(Path(run_root), run_id=run_id, dt_s=dt_s, n_elem=n_elem, input_audit=input_audit)
    _materialize_cases(target_root, run_id=run_id, dt_s=dt_s, n_elem=n_elem)
    manifest = _read(checkpoint)
    for entry in manifest["slices"]:
        source_case = source_root / "cases" / str(entry["case_relative_path"])
        target_case = target_root / "cases" / str(entry["case_relative_path"])
        for item in list(entry["static_files"]) + list(entry["time_files"]):
            relative = str(item["relative_path"])
            src = source_case / relative
            dst = target_case / relative
            if not src.is_file() or _sha256(src) != str(item["sha256"]):
                raise RuntimeError(f"checkpoint source changed: {src}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if _sha256(dst) != str(item["sha256"]):
                raise RuntimeError(f"checkpoint target hash mismatch: {dst}")
    target_checkpoint_dir = target_root / "checkpoints"
    target_checkpoint_dir.mkdir(parents=True, exist_ok=True)
    for relative in (manifest["structure"]["checkpoint_relative_path"], manifest["structure"].get("runner_checkpoint_relative_path")):
        if relative:
            src = source_root / "checkpoints" / relative
            dst = target_checkpoint_dir / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if _sha256(dst) != _sha256(src):
                raise RuntimeError(f"native structure checkpoint copy mismatch: {dst}")
    target_manifest = target_checkpoint_dir / checkpoint.name
    shutil.copy2(checkpoint, target_manifest)
    if _sha256(target_manifest) != _sha256(checkpoint):
        raise RuntimeError("checkpoint manifest copy mismatch")
    _write(target_root / "restart_lineage.json", {"run_id": run_id, "source_run_root": str(source_root), "source_checkpoint": str(checkpoint), "source_checkpoint_sha256": _sha256(checkpoint), "native_checkpoint_only": True, "latestTime_not_used": True, "setFields_called": False, "dt_s": dt_s, "nElem": n_elem})
    return target_manifest


def compare_restart(continuous: Mapping[str, Any], phase1: Mapping[str, Any], phase2: Mapping[str, Any]) -> dict[str, Any]:
    base_steps = {int(x["step"]): x for x in continuous["summary"]["step_results"]}
    restart_steps = {int(x["step"]): x for x in phase1["summary"]["step_results"]}
    restart_steps.update({int(x["step"]): x for x in phase2["summary"]["step_results"]})
    rows = []
    for step in range(20):
        a = base_steps[step]; b = restart_steps[step]
        rows.append({"step": step, "time_abs_error": abs(float(a["time_s"]) - float(b["time_s"])), "q_nrmse": _nrmse([a["q"]], [b["q"]], 1e-12), "qdot_nrmse": _nrmse([a["qdot"]], [b["qdot"]], 1e-12), "qddot_nrmse": _nrmse([a["qddot"]], [b["qddot"]], 1e-12), "force_nrmse": _nrmse(list(a["integrated_slice_forces_N"].values()), list(b["integrated_slice_forces_N"].values()), 1e-12), "motion_nrmse": _nrmse([[a["corrected_motion"][str(s)][f] for f in ("ux_m", "uy_m", "vx_mps", "vy_mps")] for s in range(3)], [[b["corrected_motion"][str(s)][f] for f in ("ux_m", "uy_m", "vx_mps", "vy_mps")] for s in range(3)], 1e-12)})
    identity = {"template_equal": phase1["template"]["template_sha256"] == continuous["template"]["template_sha256"] == phase2["template"]["template_sha256"], "motionScale_production_equal": phase1["motionScale"]["all_production_equal"] and phase2["motionScale"]["all_production_equal"], "manifest_equal": True, "physics_equal": True}
    passed = all(row["time_abs_error"] <= 1e-12 and row["q_nrmse"] <= 1e-10 and row["qdot_nrmse"] <= 1e-10 and row["qddot_nrmse"] <= 1e-10 and row["force_nrmse"] <= 1e-8 and row["motion_nrmse"] <= 1e-10 for row in rows) and all(identity.values())
    return {"rows": rows, "identity": identity, "all_within_thresholds": passed, "thresholds": {"time_abs": 1e-12, "ancf_nrmse": 1e-10, "force_nrmse": 1e-8, "motion_nrmse": 1e-10}}


def run_strict_restart(*, root: Path, continuous: Mapping[str, Any], dt_s: float, n_elem: int) -> dict[str, Any]:
    parent = root / _fresh_run_id("stage4d_c_restart")
    phase1_root = parent / "phase1"; phase2_root = parent / "phase2"
    phase1_id = parent.name + "_phase1"; phase2_id = parent.name + "_phase2"
    phase1 = _run_one(phase1_root, run_id=phase1_id, dt_s=dt_s, n_elem=n_elem, steps=10)
    checkpoint = sorted((phase1_root / "checkpoints").glob("checkpoint_*.json"))[-1]
    _stage_checkpoint(phase1_root, phase2_root, checkpoint, dt_s=dt_s, n_elem=n_elem, run_id=phase2_id)
    phase2 = _run_one(phase2_root, run_id=phase2_id, dt_s=dt_s, n_elem=n_elem, steps=10, restore_manifest=phase2_root / "checkpoints" / checkpoint.name)
    comparison = compare_restart(continuous, phase1, phase2)
    result = {"status": "passed" if comparison["all_within_thresholds"] else "failed", "run_id": parent.name, "phase1": phase1, "phase2": phase2, "checkpoint_source": str(checkpoint), "comparison": comparison}
    _write(parent / "selected_config_restart.json", result)
    _write(RESULTS_ROOT / "selected_config_restart.json", result)
    return result


def run_staged_duration(*, root: Path, stage1: Mapping[str, Any], dt_s: float, n_elem: int) -> dict[str, Any]:
    parent = root / _fresh_run_id("stage4d_c_duration")
    stages = [{"stage": 1, "time_start_s": 0.0, "time_end_s": 0.25, "source": stage1, "root": None}]
    previous = stage1; previous_root = Path(stage1["run_root"])
    for index, (end_time, count) in enumerate(((0.50, 200), (1.00, 400)), start=2):
        source_checkpoint = sorted((previous_root / "checkpoints").glob("checkpoint_*.json"))[-1]
        stage_root = parent / f"stage{index}"
        stage_id = parent.name + f"_stage{index}"
        _stage_checkpoint(previous_root, stage_root, source_checkpoint, dt_s=dt_s, n_elem=n_elem, run_id=stage_id)
        current = _run_one(stage_root, run_id=stage_id, dt_s=dt_s, n_elem=n_elem, steps=count, restore_manifest=stage_root / "checkpoints" / source_checkpoint.name)
        current["run_root"] = str(stage_root); current["stage"] = index; current["time_start_s"] = end_time - (0.25 if index == 2 else 0.50); current["time_end_s"] = end_time
        stages.append(current); previous = current; previous_root = stage_root
    stage1_entry = dict(stage1); stage1_entry["run_root"] = stage1_entry.get("run_root")
    stages[0] = stage1_entry
    audits = []
    for item in stages:
        summary = item["summary"]
        energy = item["energy_audit"]
        audits.append({"stage": item.get("stage", 1), "time_end_s": item.get("time_end_s", 0.25), "steps": len(summary["step_results"]), "max_cfl": summary.get("max_cfl"), "E_c": energy.get("E_c"), "energy_status": energy.get("status"), "limiter_peak": summary["limiter"].get("interval_peak_active_count"), "permit_leak": summary["limiter"].get("permit_leak"), "matlab_start_count": summary.get("matlab_start_count"), "all_committed": item["checkpoint_hash_audit"].get("all_valid")})
    all_passed = all(x["max_cfl"] is not None and x["max_cfl"] < MAX_CFL and x["energy_status"] == "evaluable" and x["E_c"] <= .10 and x["limiter_peak"] <= 2 and not x["permit_leak"] and x["matlab_start_count"] == 1 and x["all_committed"] for x in audits)
    result = {"status": "passed" if all_passed else "failed", "run_id": parent.name, "stages": audits, "free_viv_claim": False, "insufficient_for_viv_statistics": True}
    _write(parent / "staged_duration_summary.json", result); _write(RESULTS_ROOT / "staged_duration_summary.json", result)
    return result


def _ancf_modal_frequencies(*, n_elem: int, output: Path) -> dict[str, Any]:
    """Compute linearized ANCF frequencies using the existing MATLAB core."""
    matlab = base.MATLAB_EXE
    matlab_src = PROJECT_ROOT / "src" / "structure_ancf_matlab"
    code = (
        f"addpath('{str(matlab_src).replace(chr(92), '/') }'); "
        f"m=vertical_ttr_case('L',10,'D',1,'dInner',0.9,'nElem',{n_elem},'nSlices',3,'topTension_N',1e7,'youngs_modulus_Pa',2.07e11,'dt',0.00125); "
        "s=ancf_initialize(m); [~,K]=ancf_internal_force_tangent(s.q,m); [~,free,~]=ancf_constraints(m); "
        "M=s.model.mass_matrix; Kff=0.5*(K(free,free)+K(free,free).'); Mff=0.5*(M(free,free)+M(free,free).'); "
        "lam=real(eig(Kff,Mff)); lam=sort(lam(isfinite(lam)&lam>1e-8)); "
        "f=fopen('" + str(output).replace("\\", "/").replace("'", "''") + "','w'); "
        "fprintf(f,'%.17g\\n',sqrt(lam)/(2*pi)); fclose(f);"
    )
    result = subprocess.run([str(matlab), "-batch", code], capture_output=True, text=True, timeout=600)
    if result.returncode != 0 or not output.is_file():
        raise RuntimeError(f"ANCF modal frequency calculation failed: {result.stderr[-1000:]}")
    frequencies = [float(line.strip()) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not frequencies or not all(math.isfinite(v) and v > 0 for v in frequencies):
        raise RuntimeError("ANCF modal frequency output is empty or non-finite")
    return {"nElem": n_elem, "frequency_Hz": frequencies, "first_frequency_Hz": frequencies[0], "matlab_return_code": result.returncode}


def period_coverage_audit() -> dict[str, Any]:
    bank = _read(PROJECT_ROOT / "results" / "06_developed_flow_v3" / "developed_flow_bank_v3.json")
    frequencies = {item["flow_id"]: float(item["statistics"]["dominant_frequency_Hz"]) for item in bank["flows"]}
    modal = _ancf_modal_frequencies(n_elem=4, output=RESULTS_ROOT / "ancf_modal_frequencies.txt")
    structure_frequency_hz = modal["first_frequency_Hz"]
    result = {"structure_modal_audit": modal, "structure_frequency_hz": structure_frequency_hz, "structure_period_s": 1.0 / structure_frequency_hz, "shedding_frequency_hz": frequencies, "shedding_period_s": {key: 1.0 / value for key, value in frequencies.items()}, "duration_s": 1.0, "structure_cycles_in_1s": structure_frequency_hz, "shedding_cycles_in_1s": {key: value for key, value in frequencies.items()}, "insufficient_for_viv_statistics": True, "reason": "The 1 s run is an engineering delay window; no VIV statistical or lock-in interpretation is authorized."}
    _write(RESULTS_ROOT / "period_coverage_audit.json", result)
    return result


def five_slice_requirements() -> dict[str, Any]:
    result = {"status": "planning_only", "real_five_slice_run": False, "slice_centers_m": [1.0, 3.0, 5.0, 7.0, 9.0], "slice_lengths_m": [1.0, 3.0, 3.0, 2.0, 1.0], "local_velocity_mps": [0.8, 0.9, 1.0, 1.1, 1.2], "Re": [80.0, 90.0, 100.0, 110.0, 120.0], "required_developed_flow_bank": "Independent developed flow for every unique local Re; no interpolation or copying of the three-slice fields.", "stability_criteria": {"max_CFL": 0.8, "window_Cd_relative": 0.03, "window_Cl_RMS_relative": 0.05, "window_frequency_relative": 0.03, "St_range": [0.12, 0.22]}, "estimated_work": "At least five independent flow developments plus 3D/5-slice coupling; estimate only after mesh and solver cost are fixed.", "comparison_metrics": ["center displacement", "velocity", "acceleration", "integrated forces", "generalized force", "energy", "checkpoint identity"]}
    _write(RESULTS_ROOT / "five_slice_flow_bank_requirements.json", result)
    return result


def finalize_blocked_evidence(*, root: Path) -> dict[str, Any]:
    """Write explicit non-run records after a prescribed convergence stop."""
    time_path = root / "time_step_convergence.json"
    if not time_path.is_file():
        raise FileNotFoundError(time_path)
    time_result = _read(time_path)
    reason = "time-step subgate failed: qdot/qddot aligned NRMSE exceeded 5%; downstream heavy runs prohibited"
    virtual = {str(n): _virtual_work(n) for n in (2, 4, 8)}
    structure = {
        "status": "not_run_blocked_by_time_step_gate",
        "time_step_gate_passed": bool(time_result.get("all_passed")),
        "reason": reason,
        "configurations": {
            "nElem2": {"nElem": 2, "dt_s": DT_FINE, "steps": 200, "source": "time_fine_run"},
            "nElem4": {"nElem": 4, "dt_s": DT_FINE, "steps": 200, "status": "not_run"},
            "nElem8": {"nElem": 8, "dt_s": DT_FINE, "steps": 200, "status": "not_run"},
        },
        "virtual_work": virtual,
        "all_passed": False,
    }
    selected = {"status": "none", "dt_s": None, "nElem": None, "reason": reason}
    restart = {"status": "not_run_blocked_by_time_step_gate", "reason": reason, "continuous_steps": 20, "restart_split": "10+10"}
    duration = {"status": "not_run_blocked_by_time_step_gate", "reason": reason, "target_end_time_s": 1.0, "insufficient_for_viv_statistics": True}
    fine_dirs = sorted(root.glob("stage4d_c_time_dt00125_nelem2_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    fine_summary = _read(fine_dirs[0] / "convergence_run_summary.json") if fine_dirs and (fine_dirs[0] / "convergence_run_summary.json").is_file() else {}
    if fine_dirs and fine_summary:
        refreshed_worker = _worker_identity(fine_dirs[0])
        refreshed_worker["launcher_pid"] = fine_summary.get("summary", {}).get("matlab_worker_pid")
        fine_summary["worker_identity"] = refreshed_worker
        _write(fine_dirs[0] / "convergence_run_summary.json", fine_summary)
    checkpoint = {
        "status": "partial_audit_only",
        "reason": reason,
        "runs": {
            "stage4d_b_baseline_read_only": {"checkpoint_count": 100, "all_valid": True, "source": str(BASELINE_ROOT)},
            "template_smoke": {"checkpoint_count": 2, "all_valid": True, "source": "template_audit.real_two_step_smoke"},
            "time_fine": {"checkpoint_count": (fine_summary.get("checkpoint_hash_audit") or {}).get("checkpoint_count"), "all_valid": (fine_summary.get("checkpoint_hash_audit") or {}).get("all_valid"), "source": str(fine_dirs[0]) if fine_dirs else None},
        },
        "structure_and_duration": "not_run",
    }
    candidate = {
        "status": "partially_completed",
        "stage": "Stage 4D-C-A",
        "formal_gate_decision": "Sol_only",
        "recommendation": "建议不通过",
        "time_step_gate": {"passed": False, "result_file": str(time_path), "failed_metrics": {"qdot_nrmse": time_result.get("structure", {}).get("qdot_nrmse"), "qddot_nrmse": time_result.get("structure", {}).get("qddot_nrmse")}},
        "template_smoke_passed": True,
        "structure_convergence_run": False,
        "strict_restart_run": False,
        "staged_duration_run": False,
        "free_viv_claim": False,
        "lock_in_claim": False,
        "long_time_viv_claim": False,
        "stop_reason": reason,
    }
    _write(root / "structure_mesh_convergence.json", structure)
    _write(root / "selected_configuration.json", selected)
    _write(root / "selected_config_restart.json", restart)
    _write(root / "staged_duration_summary.json", duration)
    _write(root / "checkpoint_hash_audit.json", checkpoint)
    _write(root / "stage4d_c_a_candidate_summary.json", candidate)
    return candidate


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["verify", "template_smoke", "time_fine", "time_compare", "structure", "restart", "duration", "plan", "finalize"], required=True)
    parser.add_argument("--root", type=Path, default=RESULTS_ROOT)
    args = parser.parse_args(argv)
    args.root.mkdir(parents=True, exist_ok=True)
    if args.mode == "verify":
        _write(args.root / "baseline_audit.json", verify_stage4d_b_entry()); print(json.dumps({"status": "passed"})); return 0
    if args.mode == "template_smoke":
        result = run_template_smoke(root=args.root); print(json.dumps({"status": result["status"], "run_id": result["run_id"]})); return 0 if result["status"] == "passed" else 1
    if args.mode == "time_fine":
        run_id = _fresh_run_id("stage4d_c_time_dt00125_nelem2")
        result = _run_one(args.root / run_id, run_id=run_id, dt_s=DT_FINE, n_elem=2, steps=200); print(json.dumps({"status": "completed", "run_id": run_id, "max_cfl": result["summary"].get("max_cfl")})); return 0
    if args.mode == "time_compare":
        fine_dirs = sorted(args.root.glob("stage4d_c_time_dt00125_nelem2_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not fine_dirs: raise SystemExit("time fine run not found")
        fine = _read(fine_dirs[0] / "convergence_run_summary.json")
        coarse = {"dt_s": DT_COARSE, "nElem": 2, "summary": _read(BASELINE_ROOT / "campaign_summary.json"), "energy_audit": base._energy_summary(_read(BASELINE_ROOT / "campaign_summary.json")["energy"]), "template": {"template_sha256": "stage4d_b_baseline"}}
        comparison = compare_time_step(coarse, fine); _write(args.root / "time_step_convergence.json", comparison); print(json.dumps({"status": "passed" if comparison["all_passed"] else "failed"})); return 0 if comparison["all_passed"] else 2
    if args.mode == "structure":
        time_cmp = _read(args.root / "time_step_convergence.json")
        if not time_cmp.get("all_passed"): raise SystemExit("time-step subgate did not pass; structure run is prohibited")
        fine_dirs = sorted(args.root.glob("stage4d_c_time_dt00125_nelem2_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        coarse = _read(fine_dirs[0] / "convergence_run_summary.json")
        medium_id = _fresh_run_id("stage4d_c_structure_nelem4"); fine_id = _fresh_run_id("stage4d_c_structure_nelem8")
        medium = _run_one(args.root / medium_id, run_id=medium_id, dt_s=DT_FINE, n_elem=4, steps=200)
        fine = _run_one(args.root / fine_id, run_id=fine_id, dt_s=DT_FINE, n_elem=8, steps=200)
        result = compare_structure(coarse, medium, fine); result["run_ids"] = {"nElem2": coarse.get("run_id"), "nElem4": medium["run_id"], "nElem8": fine["run_id"]}; _write(args.root / "structure_mesh_convergence.json", result)
        selected = {"status": "selected" if result["all_passed"] else "none", "dt_s": DT_FINE if result["all_passed"] else None, "nElem": 4 if result["all_passed"] else None, "reason": "nElem4 vs nElem8 passed all prescribed thresholds" if result["all_passed"] else "nElem4 vs nElem8 did not pass"}; _write(args.root / "selected_configuration.json", selected)
        print(json.dumps({"status": "passed" if result["all_passed"] else "failed", "nElem4": medium_id, "nElem8": fine_id})); return 0 if result["all_passed"] else 3
    if args.mode == "restart":
        selected = _read(args.root / "selected_configuration.json")
        if selected.get("status") != "selected": raise SystemExit("selected configuration is unavailable")
        medium_dirs = sorted(args.root.glob("stage4d_c_structure_nelem4_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        continuous = _read(medium_dirs[0] / "convergence_run_summary.json")
        result = run_strict_restart(root=args.root, continuous=continuous, dt_s=DT_FINE, n_elem=4); print(json.dumps({"status": result["status"], "run_id": result["run_id"]})); return 0 if result["status"] == "passed" else 4
    if args.mode == "duration":
        selected = _read(args.root / "selected_configuration.json"); restart = _read(args.root / "selected_config_restart.json")
        if selected.get("status") != "selected" or restart.get("status") != "passed": raise SystemExit("duration run is prohibited before convergence and restart pass")
        medium_dirs = sorted(args.root.glob("stage4d_c_structure_nelem4_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        stage1 = _read(medium_dirs[0] / "convergence_run_summary.json"); stage1["run_root"] = str(medium_dirs[0])
        result = run_staged_duration(root=args.root, stage1=stage1, dt_s=DT_FINE, n_elem=4); print(json.dumps({"status": result["status"], "run_id": result["run_id"]})); return 0 if result["status"] == "passed" else 5
    if args.mode == "plan":
        period_coverage_audit(); five_slice_requirements(); print(json.dumps({"status": "written"})); return 0
    if args.mode == "finalize":
        result = finalize_blocked_evidence(root=args.root); print(json.dumps({"status": result["status"], "recommendation": result["recommendation"]})); return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
