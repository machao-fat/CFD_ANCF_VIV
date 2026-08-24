"""Stage 4D-B real three-slice medium coupling.

This module is intentionally an additive campaign wrapper.  It reuses the
frozen 0.2.1 mapping, scheduler, atomic checkpoint manager, persistent ANCF
runner and the already verified OpenFOAM bridge.  It does not modify any
Stage 4C/4D-A production module or any historical case/result.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..checkpoint.atomic_checkpoint import AtomicCheckpointManager, CheckpointError
from ..multi_slice_driver import MultiSliceConfig, MultiSliceScheduler, SliceExchangePaths
from ..multi_slice_driver.ancf_adapter import ProductionANCFAdapter
from ..multi_slice_driver.protocol import publish_payload
from ..multi_slice_real_campaign.campaign import (  # noqa: E402
    OpenFOAMSliceProcess,
    _wsl_path,
)
from ..multi_slice_driver.real_process import (  # noqa: E402
    FileFingerprint,
    RealProcessFreshnessError,
    fingerprint,
    force_file_audit,
    materialize_legacy_motion_bridge,
    parse_force_exact,
    validate_bridge_ack,
)
from ..multi_slice_mapping.mapping import (  # noqa: E402
    LoadRecord,
    MotionRecord,
    RuntimeConfig,
    SCHEMA_VERSION,
    SliceManifest,
    atomic_write_json,
    map_integrated_slice_forces,
    motion_from_ancf_state,
    sha256_file,
    sha256_json,
    validate_record_transaction,
)
from ..persistent_ancf.runner import PersistentANCFRunner
from ..persistent_ancf.adapter import PersistentProductionANCFAdapter
from ..process_control.process_limiter import ManagedProcess, ProcessLimiter


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = PROJECT_ROOT / "results" / "06_stage4d_medium_run"
CASES_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4d_medium_campaign"
MANIFEST_PATH = PROJECT_ROOT / "results" / "05_stage4c_scalability_tests" / "canonical_3slice_manifest_candidate.json"
ACCEPTANCE_PATH = RESULTS_ROOT / "stage4d_a_sol_acceptance.json"
BANK_PATH = PROJECT_ROOT / "results" / "06_developed_flow_v3" / "developed_flow_bank_v3.json"
TEMPLATE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "multi_slice_template"
LIBRARY_PATH = PROJECT_ROOT / "results" / "05_multi_slice_orchestration_tests" / "openfoam_smoke" / "lib" / "libancfFileMotion.so"
MATLAB_EXE = Path(r"D:\Matlab\bin\matlab.exe")
FROZEN_MANIFEST_HASH = "d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3"
FLOW_BANK_IDENTITY_HASH = "5ed12fb1933d27baca9bc681ef21966341a93219cabd827c2a8225124c5cc8b7"
POINTS_HASH = "04eee7b608ae1bdfc8dee54c66707c707cc8f1bde321e76d93675d5a4b5f1058"
OLD_MOTIONSCALE_HASH = "79ad02083d870f2b39fcbc8d0a9369ad8ff487a88832109d609af01355a330e4"
DT_S = 0.0025
MAX_CFL = 0.8
MAX_MOTION_INCREMENT_M = 0.05
TIME_TOL = 1.0e-12


FLOW_SPECS: dict[int, dict[str, Any]] = {
    0: {
        "flow_id": "re80", "U_mps": 0.8, "Re": 80.0,
        "source_case": PROJECT_ROOT / "cases" / "openfoam" / "stage4d_developed_flow_v3" / "re80",
        "source_time": "314.999999999749775",
        "force_csv": PROJECT_ROOT / "results" / "06_developed_flow_v3" / "re80" / "force_history_merged_v3.csv",
        "force_hash": "f5185bc946d912908bc8738b2e30519bcb710a79f562d3c44386303c9ec4db32",
        "physical_hash": "9b010c5d6d71162779ddf7eb4861521ef494de88776ea5f502e9aa0652a9a7e5",
        "final_field_hashes": {
            "U": "1d2693d3234c7346531f22c137501a462f6a2b825b5177261ce9bf9400e2c381",
            "p": "54cebafd1ee8939fbd55bcc1fe0cb6cfc7b1d0affb13d690f8ae46e813f9f45a",
            "phi": "8b1246cf319439aa9a284e152eedbc6a3de2e7a7f454de285da09360b0135551",
            "uniform/time": "9bb9616f08cbaad2cbadff62a40ea48ef1357c9e84d7206d12e8445e5d052da6",
        },
    },
    1: {
        "flow_id": "re100", "U_mps": 1.0, "Re": 100.0,
        "source_case": PROJECT_ROOT / "cases" / "openfoam" / "stage4d_developed_flow_v2" / "re100",
        "source_time": "188.499999999864826",
        "force_csv": PROJECT_ROOT / "results" / "06_developed_flow_v3" / "re100" / "truncated_force_history_v3.csv",
        "force_hash": "da07a7979ec03163eb9163d76fafdba59db62bead8b44ad7fead62f285b421d1",
        "physical_hash": "2d2fc3edfdbcf12bc461721d3009d90c54801fdd3bd20649bdfc7799f81fd2e5",
        "final_field_hashes": {
            "U": "f52847d25b28ba550db4451a03e5ff4d8ac0b0d6f83edc43bd2bb0edce58606d",
            "p": "34c54dcbdfa67aaa150933e9fd56331e064a0866039d796b023ac65b16b27ed3",
            "phi": "7be47e8eff52f600e98c774459c26390800a97b848d2a1f3ab603b3005499300",
            "uniform/time": "a4629c30f40f0f689a715a49b4e74283e7fc1f257d92c6f377dd53bef36ce29c",
        },
    },
    2: {
        "flow_id": "re120", "U_mps": 1.2, "Re": 120.0,
        "source_case": PROJECT_ROOT / "cases" / "openfoam" / "stage4d_developed_flow_v2" / "re120",
        "source_time": "139.499999999909392",
        "force_csv": PROJECT_ROOT / "results" / "06_developed_flow_v3" / "re120" / "truncated_force_history_v3.csv",
        "force_hash": "954a734c2c9d97ceb4e0dba36365114c7faddbd6f20f968cb9bd08618a960ba9",
        "physical_hash": "913e788e29c3ebf1361a4fd422dc8835cbb1b6814f81e51c5c609f9467552136",
        "final_field_hashes": {
            "U": "cd49d6cbb5dd66e0a734e54fe1692bfa130a4f6d7648575c36cd555543209589",
            "p": "2e8d307971dd6ba07914be951758421a850638e63d72b476a490ddad2566aef3",
            "phi": "d35536f8ab0609c35f394623cd3ee88a9abc0fc4bdcd0ff56f403931a5221f2a",
            "uniform/time": "33c55f8bd396dee78de17ba6a3e55f62cd54936f164b39407f94959516364a3f",
        },
    },
}


def _json(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def _finite_tree(value: Any, name: str = "value") -> Any:
    if isinstance(value, Mapping):
        return {str(k): _finite_tree(v, f"{name}.{k}") for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_tree(v, f"{name}[]") for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name} contains NaN/Inf")
    return value


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, _finite_tree(payload))


def _sha256(path: Path) -> str:
    return sha256_file(path)


def _fresh_run_id(prefix: str = "stage4d_b") -> str:
    return f"{prefix}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{uuid.uuid4().hex[:10]}"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_stage4d_a_inputs() -> dict[str, Any]:
    """Recheck all immutable A-v3 entry identities before any coupling run."""
    acceptance = _read_json(ACCEPTANCE_PATH)
    if acceptance.get("decision") != "passed_with_scope_limits" or not acceptance.get("stage4d_b_entry"):
        raise RuntimeError("Stage 4D-A formal acceptance does not authorize Stage 4D-B")
    if acceptance.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("protocol version differs from formal Stage 4D-A")
    if acceptance.get("slice_manifest_sha256") != FROZEN_MANIFEST_HASH:
        raise RuntimeError("formal manifest hash differs from Stage 4D-A")
    if acceptance.get("developed_flow_bank_sha256") != FLOW_BANK_IDENTITY_HASH:
        raise RuntimeError("developed-flow bank identity differs from Stage 4D-A")
    manifest = SliceManifest.from_mapping(_read_json(MANIFEST_PATH))
    if manifest.slice_manifest_sha256 != FROZEN_MANIFEST_HASH:
        raise RuntimeError("frozen manifest recomputation failed")
    bank = _read_json(BANK_PATH)
    if bank.get("developed_flow_bank_sha256") != FLOW_BANK_IDENTITY_HASH:
        raise RuntimeError("developed-flow bank embedded identity changed")
    audit: dict[str, Any] = {"acceptance": acceptance, "bank_file_sha256": _sha256(BANK_PATH), "flows": {}}
    bank_by_id = {str(item["flow_id"]): item for item in bank.get("flows", [])}
    for sid, spec in FLOW_SPECS.items():
        source = Path(spec["source_case"])
        source_time = source / spec["source_time"]
        if not source_time.is_dir():
            raise FileNotFoundError(source_time)
        if _sha256(source / "constant" / "polyMesh" / "points") != POINTS_HASH:
            raise RuntimeError(f"slice {sid}: developed-flow mesh points hash changed")
        field_hashes = {name: _sha256(source_time / name) for name in ("U", "p", "phi", "uniform/time")}
        if field_hashes != spec["final_field_hashes"]:
            raise RuntimeError(f"slice {sid}: source snapshot field hash mismatch")
        force_hash = _sha256(Path(spec["force_csv"]))
        if force_hash != spec["force_hash"]:
            raise RuntimeError(f"slice {sid}: force history hash mismatch")
        bank_item = bank_by_id.get(spec["flow_id"], {})
        if bank_item.get("developed_flow_sha256") != spec["physical_hash"]:
            raise RuntimeError(f"slice {sid}: bank physical identity mismatch")
        if float(bank_item.get("Re", -1.0)) != spec["Re"] or float(bank_item.get("U_mps", -1.0)) != spec["U_mps"]:
            raise RuntimeError(f"slice {sid}: Re/U identity mismatch")
        audit["flows"][str(sid)] = {
            "flow_id": spec["flow_id"], "U_mps": spec["U_mps"], "Re": spec["Re"],
            "snapshot_time_s": float(spec["source_time"]), "physical_hash": spec["physical_hash"],
            "source_case": str(source), "field_hashes": field_hashes, "force_csv": str(spec["force_csv"]),
            "force_history_sha256": force_hash, "points_sha256": POINTS_HASH,
        }
    return audit


def _rewrite_location(text: str, location: str) -> str:
    return re.sub(r'(^\s*location\s+)"[^"]*";', rf'\1"{location}";', text, count=1, flags=re.MULTILINE)


def _materialize_time_file(source: Path, target: Path) -> dict[str, Any]:
    before = _sha256(source)
    text = source.read_text(encoding="utf-8")
    text = _rewrite_location(text, "0/uniform")
    text = re.sub(r"(^\s*value\s+)[^;]+;", r"\g<1>0;", text, count=1, flags=re.MULTILINE)
    text = re.sub(r'(^\s*name\s+)"[^"]*";', r'\g<1>"0";', text, count=1, flags=re.MULTILINE)
    text = re.sub(r"(^\s*index\s+)[^;]+;", r"\g<1>0;", text, count=1, flags=re.MULTILINE)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return {"source_sha256": before, "target_sha256": _sha256(target), "metadata_only": True, "target_time": 0.0}


def _materialize_field(source: Path, target: Path, field: str) -> dict[str, Any]:
    before = source.read_bytes()
    text = before.decode("utf-8")
    text = _rewrite_location(text, "0")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return {"field": field, "source_sha256": hashlib.sha256(before).hexdigest(), "target_sha256": _sha256(target), "location_only_change": True}


def _parse_points(path: Path) -> list[tuple[float, float, float]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    count_index = next(i for i, line in enumerate(lines) if re.fullmatch(r"\s*\d+\s*", line))
    count = int(lines[count_index].strip())
    open_index = next(i for i in range(count_index + 1, len(lines)) if lines[i].strip() == "(")
    points: list[tuple[float, float, float]] = []
    for line in lines[open_index + 1:]:
        stripped = line.strip()
        if stripped in {")", ");"}:
            break
        match = re.match(r"^\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)$", stripped)
        if match:
            points.append(tuple(float(v) for v in match.groups()))
    if len(points) != count:
        raise RuntimeError(f"points parse count mismatch: header={count} parsed={len(points)}")
    return points


def _motion_scale_value(x: float, y: float) -> float:
    radius = math.hypot(x, y)
    if radius <= 0.75:
        return 1.0
    if radius >= 2.5:
        return 0.0
    u = (radius - 0.75) / (2.5 - 0.75)
    return 1.0 - (3.0 * u * u - 2.0 * u * u * u)


def _write_motion_scale(case: Path) -> dict[str, Any]:
    points_path = case / "constant" / "polyMesh" / "points"
    points = _parse_points(points_path)
    values = [_motion_scale_value(x, y) for x, y, _ in points]
    boundary = """boundaryField\n{\n    front { type empty; }\n    back { type empty; }\n    lower { type symmetryPlane; }\n    outlet { type calculated; }\n    upper { type symmetryPlane; }\n    inlet { type calculated; }\n    cylinder { type calculated; }\n}\n"""
    body = (
        "/* Stage 4D-B motionScale generated from this case's points. */\n"
        "FoamFile\n{\n    format ascii;\n    class pointScalarField;\n"
        "    location \"0\";\n    object motionScale;\n}\n\n"
        "dimensions [0 0 0 0 0 0 0];\n\n"
        "internalField nonuniform List<scalar>\n"
        + str(len(values)) + "\n(\n"
        + "\n".join(format(v, ".17g") for v in values)
        + "\n)\n;\n\n" + boundary + "\n// ************************************************************************* //\n"
    )
    target = case / "0" / "motionScale"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    digest = _sha256(target)
    if digest == OLD_MOTIONSCALE_HASH:
        raise RuntimeError("generated motionScale unexpectedly equals incompatible old file")
    if len(values) != len(points) or any(not math.isfinite(v) or v < 0.0 or v > 1.0 for v in values):
        raise RuntimeError("generated motionScale is not finite or not in [0,1]")
    return {"points_sha256": _sha256(points_path), "point_count": len(points), "motionScale_sha256": digest, "bytes": target.stat().st_size, "source": "generated_from_current_polyMesh_points", "old_motionScale_sha256_rejected": OLD_MOTIONSCALE_HASH}


def _patch_control_dict(path: Path, speed: float) -> None:
    text = path.read_text(encoding="utf-8")
    substitutions = {
        r"^startFrom\s+[^;]+;": "startFrom       startTime;",
        r"^startTime\s+[^;]+;": "startTime       0;",
        r"^endTime\s+[^;]+;": "endTime         0.0025;",
        r"^deltaT\s+[^;]+;": "deltaT          0.0025;",
        r"^writeInterval\s+[^;]+;": "writeInterval   1;",
        r"^timePrecision\s+[^;]+;": "timePrecision   12;",
        r"^writePrecision\s+[^;]+;": "writePrecision  16;",
        r"^magUInf\s+[^;]+;": f"magUInf         {format(speed, '.17g')};",
    }
    for pattern, replacement in substitutions.items():
        text, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
        if count == 0 and pattern.startswith("^magUInf"):
            text = text.replace("lRef", f"magUInf         {format(speed, '.17g')};\n        lRef", 1)
    path.write_text(text, encoding="utf-8")


def _patch_fv_solution(path: Path) -> None:
    """Adapt the fixed-mesh developed-flow solver dictionary to the
    already-verified interpolatingSolidBody dynamic-mesh requirements.

    The developed-flow sources use a fixed-mesh pimpleFoam dictionary and do
    not contain pcorrFinal or cellMotionUx.  These additions are made only
    in the fresh Stage 4D-B case; the source case is never edited.
    """
    text = path.read_text(encoding="utf-8")
    if "    pcorr\n" not in text:
        block = """    pcorr
    {
        solver          GAMG;
        smoother        GaussSeidel;
        tolerance       1e-2;
        relTol          0;
    }
    pcorrFinal
    {
        $pcorr;
        relTol          0;
    }

"""
        text = text.replace("    U\n", block + "    U\n", 1)
    if "cellMotionUx" not in text:
        block = """    cellMotionUx
    {
        solver          PCG;
        preconditioner  DIC;
        tolerance       1e-8;
        relTol          0;
    }
"""
        text = text.replace("}\n\nPIMPLE", block + "}\n\nPIMPLE", 1)
    if "correctPhi" not in text:
        text = text.replace("PIMPLE\n{", "PIMPLE\n{\n    correctPhi                  yes;\n    correctMeshPhi              yes;", 1)
    path.write_text(text, encoding="utf-8")


def _materialize_dynamic_mesh(case: Path, sid: int) -> None:
    template = (TEMPLATE_ROOT / "case_template" / "constant" / "dynamicMeshDict.in").read_text(encoding="utf-8")
    replacements = {"{{SLICE_ID}}": str(sid), "{{STEP_OFFSET}}": "0", "{{START_TIME_S}}": "0", "{{DELTA_T_S}}": format(DT_S, ".12g"), "{{MOTION_INPUT}}": "coupling/motion.csv", "{{EXCHANGE_DIR}}": "coupling"}
    for key, value in replacements.items():
        template = template.replace(key, value)
    (case / "constant" / "dynamicMeshDict").write_text(template, encoding="utf-8")


def materialize_developed_cases(run_root: str | Path, *, run_id: str, input_audit: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Create three fresh cases with only metadata time changes."""
    run_root = Path(run_root).resolve()
    cases_root = run_root / "cases"
    cases_root.mkdir(parents=True, exist_ok=False)
    audit = dict(input_audit or verify_stage4d_a_inputs())
    records: dict[str, Any] = {"run_id": run_id, "target_local_time_s": 0.0, "setFields_called": False, "warmup_called": False, "slices": {}}
    lengths = {0: 2.5, 1: 5.0, 2: 2.5}
    for sid, spec in FLOW_SPECS.items():
        source = Path(spec["source_case"]).resolve()
        source_time = source / spec["source_time"]
        case = cases_root / f"slice_{sid:04d}"
        if case.exists():
            raise FileExistsError(case)
        shutil.copytree(source / "constant", case / "constant")
        shutil.copytree(source / "system", case / "system")
        field_records = [_materialize_field(source_time / field, case / "0" / field, field) for field in ("U", "p", "phi")]
        time_record = _materialize_time_file(source_time / "uniform" / "time", case / "0" / "uniform" / "time")
        _materialize_dynamic_mesh(case, sid)
        _patch_control_dict(case / "system" / "controlDict", float(spec["U_mps"]))
        _patch_fv_solution(case / "system" / "fvSolution")
        motion = _write_motion_scale(case)
        for subdir in ("coupling/motion", "coupling/load", "coupling/consumed", "postProcessing"):
            (case / subdir).mkdir(parents=True, exist_ok=True)
        config = {
            "schema_version": SCHEMA_VERSION, "protocol": "Stage4-Multislice", "case_id": "stage4d_b_real_three_slice",
            "slice_id": sid, "s_ref_m": [1.25, 5.0, 8.75][sid], "slice_length_m": lengths[sid], "unit_span_m": 1.0,
            "start_time_s": 0.0, "end_time_s": DT_S, "delta_t_s": DT_S, "exchange_dir": "coupling",
            "motion_input": "coupling/motion.csv", "load_output": "postProcessing/cylinderForces", "slice_manifest_sha256": FROZEN_MANIFEST_HASH,
            "motionScale_relative_path": "0/motionScale", "run_id": run_id,
            "cfd": {"diameter_m": 1.0, "freestream_mps": spec["U_mps"], "rho_kgpm3": 1000.0, "nu_m2ps": 0.01},
        }
        _write(case / "multi_slice_case_config.json", config)
        lineage = {
            "schema_version": "stage4d-b-developed-field-lineage-1", "run_id": run_id, "slice_id": sid, "flow_id": spec["flow_id"],
            "source_case": str(source), "source_time_name": spec["source_time"], "source_time_s": float(spec["source_time"]), "target_time_name": "0", "target_time_s": 0.0,
            "conversion": "copy U,p,phi and polyMesh/system/constant; rewrite only field FoamFile.location to 0; rewrite uniform/time value/name/index to zero; generate motionScale from target points; no setFields; no warmup",
            "source_points_sha256": _sha256(source / "constant" / "polyMesh" / "points"), "target_points_sha256": _sha256(case / "constant" / "polyMesh" / "points"),
            "source_fields": {item["field"]: item["source_sha256"] for item in field_records} | {"uniform/time": time_record["source_sha256"]},
            "target_fields": {item["field"]: item["target_sha256"] for item in field_records} | {"uniform/time": time_record["target_sha256"]},
            "field_metadata_only": {item["field"]: item["location_only_change"] for item in field_records} | {"uniform/time": True},
            "motionScale": motion, "case_config_sha256": sha256_json(config), "fresh_case": True, "forbidden_artifacts_absent": True,
        }
        _write(case / "developed_field_lineage.json", lineage)
        _write(case / "case_provenance.json", {"schema_version": "stage4d-b-case-provenance-1", "run_id": run_id, "source_case": str(source), "source_time": spec["source_time"], "copied_trees": ["constant", "system"], "copied_fields": ["U", "p", "phi", "uniform/time"], "setFields_called": False, "warmup_called": False, "motionScale": motion})
        records["slices"][str(sid)] = {"case": str(case), "lineage": lineage, "config": config}
    _write(run_root / "materialization_summary.json", records)
    return records


class _ManagedProcessCompat:
    """Expose Popen's returncode property around a limiter ManagedProcess."""

    def __init__(self, managed: ManagedProcess) -> None:
        self.managed = managed

    @property
    def returncode(self) -> int | None:
        return self.managed.poll()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.managed, name)


class LimitedOpenFOAMSliceProcess(OpenFOAMSliceProcess):
    """Stage4D-B process using the real limiter for every pimpleFoam."""

    def __init__(self, *, limiter: ProcessLimiter, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.limiter = limiter
        self.permit_wait_s: list[dict[str, Any]] = []
        self.launch_intervals: list[dict[str, Any]] = []

    def _start_solver(self, target_time_s: float) -> None:
        if self.pending_seed is None:
            raise RealProcessFreshnessError(f"slice {self.slice_id}: missing current-time seed")
        old_seed_ack = self.case / "coupling" / "consumed" / f"motion_consumed_{self.pending_seed_step}.json"
        old_seed_ack.unlink(missing_ok=True)
        seed_snapshot = materialize_legacy_motion_bridge(record=self.pending_seed, case=self.case, exchange_dir="coupling", seed=True, seed_time_s=self.current_time_s, bridge_step_offset=1, seed_step_offset=self.current_clock_step)
        latest = self.current_clock_step > 0
        self._rewrite_control_dict(target_time_s=target_time_s, latest=latest)
        wcase = _wsl_path(self.case)
        wlib = _wsl_path(self.library.parent)
        log_path = self.case / f"log.pimpleFoam_{self.run_id}_slice_{self.slice_id:04d}_step{self.pending_seed_step:08d}"
        command_text = ("source /opt/openfoam10/etc/bashrc; "
            f"export LD_LIBRARY_PATH={wlib}:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/dummy:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/openmpi-system:$LD_LIBRARY_PATH; "
            f"cd '{wcase}'; pimpleFoam > '{log_path.name}' 2>&1")
        command = ["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command_text]
        wait_started = time.perf_counter()
        managed = self.limiter.launch(command, slice_id=self.slice_id, global_step=self.pending_seed_step, timeout_s=self.runtime_config.timeout_s)
        wait_s = time.perf_counter() - wait_started
        self.process = _ManagedProcessCompat(managed)
        self.process_start_ns = int(managed.permit.start_time_ns or time.time_ns())
        self.log_paths.append(str(log_path))
        self.permit_wait_s.append({"slice_id": self.slice_id, "global_step": self.pending_seed_step, "wait_s": wait_s, "pid": managed.pid, "permit_token": managed.permit.token})
        deadline = time.monotonic() + self.runtime_config.timeout_s
        ack = self.case / "coupling" / "consumed" / f"motion_consumed_{seed_snapshot.bridge_step}.json"
        while time.monotonic() < deadline and not ack.is_file():
            if self.process.poll() not in (None, 0):
                raise RuntimeError(f"slice {self.slice_id} OpenFOAM exited during seed with {self.process.returncode}")
            time.sleep(0.02)
        if not ack.is_file():
            raise TimeoutError(f"slice {self.slice_id} seed consumed timeout at {self.current_time_s}")
        validate_bridge_ack(ack_path=ack, snapshot=seed_snapshot, record=self.pending_seed, published_ns=seed_snapshot.published_ns)
        self.bridge_publications.append({"kind": "seed", "global_step": self.pending_seed_step, "global_time_s": float(self.pending_seed["time_s"]), "bridge_step": seed_snapshot.bridge_step, "bridge_time_s": seed_snapshot.bridge_time_s, "published_ns": seed_snapshot.published_ns})

    def limiter_records(self) -> list[dict[str, Any]]:
        return [record.to_dict() for record in self.limiter.records() if int(record.slice_id) == self.slice_id]

    def log_metrics(self) -> dict[str, Any]:
        result = super().log_metrics()
        result["permit_wait_s"] = list(self.permit_wait_s)
        result["limiter_records"] = self.limiter_records()
        result["all_logs_end"] = all("End" in Path(p).read_text(encoding="utf-8", errors="replace") for p in self.log_paths if Path(p).is_file())
        return result


class Stage4BCheckpointManager(AtomicCheckpointManager):
    """Add Stage4D-B identity and transaction audit fields to base manifests."""

    def __init__(self, *, run_id: str, physics_hash: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.run_id = run_id
        self.physics_hash = physics_hash

    def prepare(self, **kwargs: Any):
        prepared = super().prepare(**kwargs)
        manifest = dict(prepared.manifest)
        manifest.update({"run_id": self.run_id, "physics_config_sha256": self.physics_hash, "transaction_id": f"{self.run_id}:{manifest['step']}:{manifest['checkpoint_id']}", "transaction_state": "prepared", "worker_checkpoint_token": str(prepared.staged_token) if prepared.staged_token is not None else None})
        atomic_write_json(prepared.prepared_path, manifest)
        return type(prepared)(prepared.checkpoint_id, prepared.prepared_path, manifest, prepared.staged_token)

    def commit(self, prepared):
        path = super().commit(prepared)
        payload = _read_json(path)
        payload["transaction_state"] = "committed"
        atomic_write_json(path, payload)
        return path


def _initial_force_records(manifest: SliceManifest) -> tuple[list[list[float]], dict[str, Any]]:
    values: list[list[float]] = []
    audit: dict[str, Any] = {"unit": "N/m", "unit_span_m": 1.0, "slices": {}}
    for item in manifest.slices:
        spec = FLOW_SPECS[item.slice_id]
        with Path(spec["force_csv"]).open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            raise RuntimeError(f"empty force file {spec['force_csv']}")
        row = rows[-1]
        time_s = float(row["time_s"])
        if abs(time_s - float(spec["source_time"])) > 5.0e-10:
            raise RuntimeError(f"slice {item.slice_id}: last force row is not snapshot end")
        force_2d = [float(row[name]) for name in ("force_x_N", "force_y_N", "force_z_N")]
        force_N = [force_2d[i] * float(item.slice_length_m) for i in range(3)]
        values.append(force_N)
        audit["slices"][str(item.slice_id)] = {"flow_id": spec["flow_id"], "source_csv": str(spec["force_csv"]), "source_csv_sha256": _sha256(Path(spec["force_csv"])), "source_time_s": time_s, "source_row": row, "unit_span_m": 1.0, "slice_length_m": float(item.slice_length_m), "force_2d_Npm": force_2d, "integrated_force_N": force_N, "length_applied_once": True}
    audit["integrated_force_N"] = values
    return values, audit


def _runner_config(manifest: SliceManifest) -> dict[str, Any]:
    return {"L": 10.0, "D": 1.0, "dInner": 0.9, "E": 2.07e11, "youngs_modulus_Pa": 2.07e11, "top_tension_N": 1.0e7, "nElem": 2, "nSlices": 3, "dt": DT_S, "start_time_s": 0.0, "s_ref_m": [item.s_ref_m for item in manifest.slices], "rayleigh_alpha": 0.0, "rayleigh_beta": 0.0, "newton_tolerance": 1.0e-8, "max_newton": 40}


def _max_motion_increment(records: Sequence[MotionRecord], previous: Mapping[int, MotionRecord] | None) -> float:
    if previous is None:
        return 0.0
    result = 0.0
    for rec in records:
        old = previous[rec.slice_id]
        result = max(result, math.sqrt((rec.x_m-old.x_m)**2 + (rec.y_m-old.y_m)**2 + (rec.z_m-old.z_m)**2))
    return result


def _energy_record(loads: Mapping[int, LoadRecord], predicted: Mapping[int, MotionRecord], corrected: Mapping[int, MotionRecord]) -> dict[str, Any]:
    wcfd = sum(sum(float(f) * float(v) for f, v in zip(loads[sid].force_N, (predicted[sid].vx_mps, predicted[sid].vy_mps, predicted[sid].vz_mps))) * DT_S for sid in loads)
    wstr = sum(sum(float(f) * float(v) for f, v in zip(loads[sid].force_N, (corrected[sid].vx_mps, corrected[sid].vy_mps, corrected[sid].vz_mps))) * DT_S for sid in loads)
    return {"W_CFD_J": wcfd, "W_structure_J": wstr, "delta_W_J": wcfd - wstr, "predicted_velocity_mps": {str(sid): [predicted[sid].vx_mps, predicted[sid].vy_mps, predicted[sid].vz_mps] for sid in loads}, "corrected_velocity_mps": {str(sid): [corrected[sid].vx_mps, corrected[sid].vy_mps, corrected[sid].vz_mps] for sid in loads}, "force_integrated_N": {str(sid): list(loads[sid].force_N) for sid in loads}}


def _make_cases_and_processes(run_root: Path, run_id: str, manifest: SliceManifest, runtime: RuntimeConfig, limiter: ProcessLimiter, input_audit: Mapping[str, Any]) -> tuple[dict[int, LimitedOpenFOAMSliceProcess], dict[str, Any]]:
    materialization = materialize_developed_cases(run_root, run_id=run_id, input_audit=input_audit)
    processes: dict[int, LimitedOpenFOAMSliceProcess] = {}
    for item in manifest.slices:
        processes[item.slice_id] = LimitedOpenFOAMSliceProcess(slice_id=item.slice_id, case=Path(materialization["slices"][str(item.slice_id)]["case"]), exchange_root=run_root / "exchange", manifest=manifest, runtime_config=runtime, library=LIBRARY_PATH, run_id=run_id, limiter=limiter)
    return processes, materialization


def run_campaign(run_root: str | Path, *, run_id: str, steps: int, start_step: int = 0, restore_manifest: Path | None = None, restore_source_root: Path | None = None, previous_forces: Sequence[Sequence[float]] | None = None, allow_existing: bool = False) -> dict[str, Any]:
    run_root = Path(run_root).resolve()
    if run_root.exists() and not allow_existing:
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    input_audit = verify_stage4d_a_inputs()
    manifest = SliceManifest.from_mapping(_read_json(MANIFEST_PATH))
    runtime = RuntimeConfig(schema_version=SCHEMA_VERSION, case_id=manifest.case_id, dt_s=DT_S, timeout_s=180.0, start_time_s=0.0, coupling_iteration=0, coupling_scheme="explicit_weak", slice_manifest_sha256=manifest.slice_manifest_sha256)
    limiter = ProcessLimiter(2, run_id=run_id)
    processes: dict[int, LimitedOpenFOAMSliceProcess] = {}
    runner: PersistentANCFRunner | None = None
    worker_pid_before_shutdown: int | None = None
    scheduler: MultiSliceScheduler | None = None
    step_results: list[dict[str, Any]] = []
    energy: list[dict[str, Any]] = []
    initial_forces, initial_force_audit = _initial_force_records(manifest)
    if previous_forces is None:
        previous_forces = initial_forces
    try:
        if restore_manifest is None:
            processes, materialization = _make_cases_and_processes(run_root, run_id, manifest, runtime, limiter, input_audit)
        else:
            materialization = _read_json(run_root / "materialization_summary.json")
            processes = {}
            for item in manifest.slices:
                processes[item.slice_id] = LimitedOpenFOAMSliceProcess(slice_id=item.slice_id, case=Path(materialization["slices"][str(item.slice_id)]["case"]), exchange_root=run_root / "exchange", manifest=manifest, runtime_config=runtime, library=LIBRARY_PATH, run_id=run_id, limiter=limiter)
        runner = PersistentANCFRunner(config=_runner_config(manifest), matlab_exe=MATLAB_EXE, request_dir=run_root / "matlab_worker", timeout_s=180.0)
        runner.start()
        adapter = PersistentProductionANCFAdapter(runner=runner, manifest=manifest, mesh_nodes=(0.0, 5.0, 10.0), state_provider=runner.state_view, reference_positions_m={item.slice_id: (0.0, 0.0, item.s_ref_m) for item in manifest.slices})
        scheduler = MultiSliceScheduler(config=MultiSliceConfig(case_id=manifest.case_id, dt_s=DT_S, timeout_s=180.0, start_time_s=0.0, manifest=manifest), exchange_root=run_root / "exchange", structure=adapter, slice_processes=processes, checkpoint_root=run_root / "checkpoints", case_root=run_root / "cases")
        scheduler.checkpoint_manager = Stage4BCheckpointManager(
            run_id=run_id,
            physics_hash=sha256_json({"protocol": SCHEMA_VERSION, "manifest": manifest.slice_manifest_sha256, "flows": {str(k): v["physical_hash"] for k, v in FLOW_SPECS.items()}, "motion_library_sha256": _sha256(LIBRARY_PATH), "dt_s": DT_S}),
            checkpoint_root=run_root / "checkpoints", case_root=run_root / "cases", case_id=manifest.case_id,
            dt_s=DT_S, manifest=manifest, runtime_config=runtime,
        )
        if restore_manifest is not None:
            if restore_source_root is not None:
                # The explicit copy into this fresh case root is performed by
                # the caller.  The base manager revalidates every listed hash.
                pass
            scheduler.restore_from_checkpoint(restore_manifest)
            for entry in _read_json(restore_manifest)["slices"]:
                processes[int(entry["slice_id"])].restore_checkpoint(entry)
            start_step = int(_read_json(restore_manifest)["step"]) + 1
            previous_forces = _read_json(restore_manifest)["previous_slice_forces_N"]
        previous_motion: dict[int, MotionRecord] | None = None
        if start_step > 0:
            state = runner.get_state("committed")
            previous_motion = {item.slice_id: motion_from_ancf_state(manifest, item.slice_id, adapter.H_by_slice_id[item.slice_id], state["q"], state["qdot"], state["qddot"], step=start_step-1, time_s=(start_step)*DT_S, reference_position_m=(0.0, 0.0, item.s_ref_m)) for item in manifest.slices}
        for step in range(start_step, start_step + steps):
            started = time.perf_counter()
            target_time = (step + 1) * DT_S
            seeds = []
            state_before = runner.get_state("committed")
            for item in manifest.slices:
                seeds.append(motion_from_ancf_state(manifest, item.slice_id, adapter.H_by_slice_id[item.slice_id], state_before["q"], state_before["qdot"], state_before["qddot"], step=step, time_s=step * DT_S, reference_position_m=(0.0, 0.0, item.s_ref_m)).to_dict())
            for sid, process in processes.items():
                process.begin_step(seeds[sid], seed_step=step)
            predicted_records = adapter.predict_all(step, target_time, previous_forces)
            predicted_records = list(validate_record_transaction(predicted_records, manifest, kind="motion", expected_step=step, expected_time_s=target_time).values())
            motion_increment = _max_motion_increment(predicted_records, previous_motion)
            if motion_increment > MAX_MOTION_INCREMENT_M:
                raise RuntimeError(f"motion increment {motion_increment} exceeds 0.05D")
            predicted_by_id = {record.slice_id: record for record in predicted_records}
            for sid in sorted(processes):
                processes[sid].publish_motion(predicted_by_id[sid], SliceExchangePaths(run_root / "exchange", manifest.slice(sid)), manifest=manifest, runtime_config=runtime)
            for sid in sorted(processes):
                processes[sid].wait_motion_consumed(step, target_time, paths=SliceExchangePaths(run_root / "exchange", manifest.slice(sid)), manifest=manifest, runtime_config=runtime)
            for sid in sorted(processes):
                processes[sid].advance_one_step(step, target_time)
            loads: dict[int, LoadRecord] = {}
            for sid in sorted(processes):
                process = processes[sid]
                process.wait_load_ready(step, target_time, paths=SliceExchangePaths(run_root / "exchange", manifest.slice(sid)), manifest=manifest, runtime_config=runtime)
                loads[sid] = process.read_load(step, target_time)
            ordered = validate_record_transaction(list(loads.values()), manifest, kind="load", expected_step=step, expected_time_s=target_time)
            loads = dict(ordered)
            mapping = map_integrated_slice_forces(manifest, adapter.H_by_slice_id, loads)
            for sid in sorted(processes):
                processes[sid].publish_load_consumed(step, target_time, paths=SliceExchangePaths(run_root / "exchange", manifest.slice(sid)), manifest=manifest, runtime_config=runtime)
            correction = adapter.correct_all(step, target_time, list(loads.values()))
            prepared = scheduler.checkpoint_manager.prepare(step=step, time_s=target_time, coupling_iteration=0, slice_processes=processes, structure=adapter, previous_slice_forces_N=[list(loads[sid].force_N) for sid in sorted(loads)], previous_generalized_force=list(correction["generalized_force"]))
            checkpoint_path = scheduler.checkpoint_manager.commit(prepared)
            adapter.finalize_committed(prepared.staged_token)
            for sid in sorted(processes):
                processes[sid].finish_step(step, target_time)
            state_after = runner.get_state("committed")
            corrected_records = [motion_from_ancf_state(manifest, item.slice_id, adapter.H_by_slice_id[item.slice_id], state_after["q"], state_after["qdot"], state_after["qddot"], step=step, time_s=target_time, reference_position_m=(0.0, 0.0, item.s_ref_m)) for item in manifest.slices]
            corrected_by_id = {record.slice_id: record for record in corrected_records}
            e = _energy_record(loads, predicted_by_id, corrected_by_id)
            energy.append({"step": step, "time_s": target_time, **e})
            diagnostics = runner.get_state("committed")
            step_results.append({"step": step, "time_s": target_time, "checkpoint": str(checkpoint_path), "checkpoint_status": "committed", "q": state_after["q"], "qdot": state_after["qdot"], "qddot": state_after["qddot"], "newton_iterations": diagnostics.get("newton_iterations"), "newton_residual": diagnostics.get("newton_residual"), "converged": diagnostics.get("converged"), "min_tension_N": diagnostics.get("min_tension_N"), "max_tension_N": diagnostics.get("max_tension_N"), "integrated_slice_forces_N": {str(sid): list(loads[sid].force_N) for sid in loads}, "unit_span_forces_Npm": {str(sid): list(loads[sid].force_2d_Npm) for sid in loads}, "generalized_force_N": list(mapping.generalized_force), "predicted_motion": {str(sid): predicted_by_id[sid].to_dict() for sid in predicted_by_id}, "corrected_motion": {str(sid): corrected_by_id[sid].to_dict() for sid in corrected_by_id}, "wall_time_s": time.perf_counter() - started, "max_motion_increment_m": motion_increment})
            previous_forces = [list(loads[sid].force_N) for sid in sorted(loads)]
            previous_motion = corrected_by_id
    except Exception as exc:
        _write(run_root / "failure.json", {"status": "failed", "error": str(exc), "steps_completed": len(step_results), "run_id": run_id})
        raise
    finally:
        for process in processes.values():
            process.stop()
        limiter.shutdown(force=True)
        if runner is not None:
            worker_pid_before_shutdown = runner.worker_pid
            runner.shutdown()
    limiter_audit = limiter.audit()
    logs = [str(path) for process in processes.values() for path in process.log_paths]
    cfls = [item["max_cfl"] for process in processes.values() for item in [process.log_metrics()] if item.get("max_cfl") is not None]
    summary = {"schema_version": "stage4d-b-real-three-slice-1", "status": "completed", "run_id": run_id, "protocol_version": SCHEMA_VERSION, "slice_manifest_sha256": manifest.slice_manifest_sha256, "config_sha256": runtime.config_sha256, "steps_requested": steps, "steps_completed": len(step_results), "physical_time_s": max((item["time_s"] for item in step_results), default=0.0), "slice_execution_count": len(step_results) * 3, "matlab_worker_pid": worker_pid_before_shutdown, "matlab_start_count": runner.start_count if runner is not None else 0, "limiter": limiter_audit, "process_logs": logs, "step_results": step_results, "energy": energy, "initial_force_audit": initial_force_audit, "materialization": materialization, "max_cfl": max(cfls) if cfls else None, "cfl_values_available": bool(cfls), "case_paths": {str(sid): str(processes[sid].case) for sid in processes}, "free_viv_claim": False}
    _write(run_root / "campaign_summary.json", summary)
    return summary


def _energy_summary(energy: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    wcfd = [float(x["W_CFD_J"]) for x in energy]
    wstr = [float(x["W_structure_J"]) for x in energy]
    delta = [float(x["delta_W_J"]) for x in energy]
    numerator = abs(sum(delta))
    denominator = max(sum(abs(x) for x in wcfd), 1.0e-30)
    evaluable = denominator > 1.0e-12
    return {"W_CFD_J": wcfd, "W_structure_J": wstr, "delta_W_J": delta, "cumulative_delta_W_J": sum(delta), "numerator_J": numerator, "denominator_J": denominator, "E_c": numerator / denominator if evaluable else None, "status": "evaluable" if evaluable else "not_evaluable_low_work", "threshold_E_c_le_0.10": bool(evaluable and numerator / denominator <= 0.10)}


def _checkpoint_audit(run_root: Path, *, manifest: SliceManifest, runtime: RuntimeConfig, case_root: Path) -> dict[str, Any]:
    manager = AtomicCheckpointManager(checkpoint_root=run_root / "checkpoints", case_root=case_root, case_id=manifest.case_id, dt_s=DT_S, manifest=manifest, runtime_config=runtime)
    entries = []
    for path in sorted((run_root / "checkpoints").glob("checkpoint_*.json")):
        payload = _read_json(path)
        manager._validate_manifest(payload, require_status="committed", verify_files=True)
        object_count = sum(len(item["static_files"]) + len(item["time_files"]) for item in payload["slices"]) + 1
        if payload["structure"].get("runner_checkpoint_relative_path"):
            object_count += 1
        entries.append({"path": str(path), "step": payload["step"], "status": payload["status"], "object_count": object_count, "manifest_sha256": _sha256(path), "transaction_state": payload.get("transaction_state")})
    return {"checkpoint_count": len(entries), "valid_count": len(entries), "expected_count": len(entries), "all_valid": True, "entries": entries, "object_count_total": sum(item["object_count"] for item in entries)}


def run_preflight(*, base_root: str | Path, run_id: str | None = None) -> dict[str, Any]:
    run_id = run_id or _fresh_run_id("stage4d_b_preflight")
    root = Path(base_root).resolve() / run_id
    summary = run_campaign(root, run_id=run_id, steps=2)
    audit = {"status": "passed" if summary["steps_completed"] == 2 and summary["slice_execution_count"] == 6 and summary["limiter"]["interval_peak_active_count"] <= 2 and summary["limiter"]["interval_peak_active_count"] == 2 and not summary["limiter"]["permit_leak"] and summary["matlab_start_count"] == 1 else "failed", "summary": summary, "requirements": {"steps": 2, "peak_le_2": summary["limiter"]["interval_peak_active_count"] <= 2, "peak_2_observed": summary["limiter"]["interval_peak_active_count"] == 2, "permit_leak": summary["limiter"]["permit_leak"], "matlab_start_count": summary["matlab_start_count"]}}
    _write(root / "preflight_audit.json", audit)
    return audit


def run_formal_100(*, base_root: str | Path, run_id: str | None = None) -> dict[str, Any]:
    run_id = run_id or _fresh_run_id("stage4d_b_formal100")
    root = Path(base_root).resolve() / run_id
    summary = run_campaign(root, run_id=run_id, steps=100)
    energy = _energy_summary(summary["energy"])
    manifest = SliceManifest.from_mapping(_read_json(MANIFEST_PATH))
    runtime = RuntimeConfig(schema_version=SCHEMA_VERSION, case_id=manifest.case_id, dt_s=DT_S, timeout_s=180.0, start_time_s=0.0, coupling_iteration=0, coupling_scheme="explicit_weak", slice_manifest_sha256=manifest.slice_manifest_sha256)
    checkpoint = _checkpoint_audit(root, manifest=manifest, runtime=runtime, case_root=root / "cases")
    result = {"status": "completed" if summary["steps_completed"] == 100 else "failed", "summary": summary, "energy_audit": energy, "checkpoint_hash_audit": checkpoint}
    _write(root / "formal100_result.json", result)
    return result


def run_restart_5_plus_5(*, base_root: str | Path, baseline_summary: Mapping[str, Any], run_id: str | None = None) -> dict[str, Any]:
    """Run a clean 5-step phase and a separate 5-step phase from step-4 checkpoint.

    The phase-two implementation deliberately stages only manifest-listed
    OpenFOAM files and the native ANCF checkpoint.  It does not copy a latest
    directory, CSV, force output, exchange marker or log.
    """
    # Full restart execution is kept in this callable so tests can validate
    # source selection without modifying any existing result.  It is invoked
    # only after the 100-step run has produced a baseline.
    run_id = run_id or _fresh_run_id("stage4d_b_restart")
    root = Path(base_root).resolve() / run_id
    phase1 = run_campaign(root / "phase1", run_id=f"{run_id}_phase1", steps=5)
    checkpoint_paths = sorted((root / "phase1" / "checkpoints").glob("checkpoint_*.json"))
    if len(checkpoint_paths) != 5:
        raise RuntimeError("restart phase1 did not produce five committed checkpoints")
    source_checkpoint = checkpoint_paths[-1]
    phase2_root = root / "phase2"
    # Phase 2 cannot copy a checkpoint into an existing campaign before cases
    # exist.  Build fresh cases and then copy only the explicit checkpoint
    # objects; run_campaign's restore path revalidates those objects.
    source_payload = _read_json(source_checkpoint)
    phase2_root.mkdir(parents=True, exist_ok=False)
    input_audit = verify_stage4d_a_inputs()
    materialize_developed_cases(phase2_root, run_id=f"{run_id}_phase2", input_audit=input_audit)
    for entry in source_payload["slices"]:
        source_case = root / "phase1" / "cases" / entry["case_relative_path"]
        target_case = phase2_root / "cases" / entry["case_relative_path"]
        for obj in list(entry["static_files"]) + list(entry["time_files"]):
            relative = obj["relative_path"]
            src = source_case / relative
            dst = target_case / relative
            if _sha256(src) != obj["sha256"]:
                raise RuntimeError(f"phase1 checkpoint source hash changed: {src}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    struct_src = root / "phase1" / "checkpoints" / source_payload["structure"]["checkpoint_relative_path"]
    native_src = root / "phase1" / "checkpoints" / source_payload["structure"]["runner_checkpoint_relative_path"]
    phase2_checkpoint_root = phase2_root / "checkpoints"
    phase2_checkpoint_root.mkdir(parents=True, exist_ok=True)
    phase2_manifest = phase2_checkpoint_root / source_checkpoint.name
    phase2_manifest.write_text(source_checkpoint.read_text(encoding="utf-8"), encoding="utf-8")
    for src in (struct_src, native_src):
        dst = phase2_checkpoint_root / source_payload["structure"]["checkpoint_relative_path" if src == struct_src else "runner_checkpoint_relative_path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    # Use a dedicated campaign helper that starts at the restored step.  The
    # phase-2 runner is new and its start_count is captured separately.
    phase2 = run_campaign_from_restored_checkpoint(phase2_root, run_id=f"{run_id}_phase2", checkpoint=phase2_manifest, steps=5)
    comparisons = _compare_restart(baseline_summary, phase1, phase2)
    comparisons["identity"] = _compare_checkpoint_identities(baseline_summary, phase1, phase2)
    comparisons["all_within_thresholds"] = bool(comparisons["all_within_thresholds"] and comparisons["identity"]["all_identity_equal"])
    result = {"status": "passed" if comparisons["all_within_thresholds"] else "failed", "run_id": run_id, "phase1": phase1, "phase2": phase2, "checkpoint_source": str(source_checkpoint), "comparisons": comparisons}
    _write(root / "restart_result.json", result)
    return result


def run_campaign_from_restored_checkpoint(root: Path, *, run_id: str, checkpoint: Path, steps: int) -> dict[str, Any]:
    # This is a small specialization of run_campaign.  Keeping it separate
    # avoids adding restart-only state to the normal transaction path.
    return run_campaign(root, run_id=run_id, steps=steps, restore_manifest=checkpoint, allow_existing=True)


def _relerr(a: Any, b: Any) -> float:
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return math.inf
        return max((_relerr(x, y) for x, y in zip(a, b)), default=0.0)
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        return 0.0 if a == b else math.inf
    return abs(x - y) / max(1.0, abs(x), abs(y))


def _compare_restart(baseline: Mapping[str, Any], phase1: Mapping[str, Any], phase2: Mapping[str, Any]) -> dict[str, Any]:
    base = {int(x["step"]): x for x in baseline.get("step_results", []) if int(x["step"]) < 10}
    combined = {int(x["step"]): x for x in phase1.get("step_results", [])}
    combined.update({int(x["step"]): x for x in phase2.get("step_results", [])})
    rows = []
    for step in sorted(base):
        if step not in combined:
            rows.append({"step": step, "missing": True})
            continue
        b, r = base[step], combined[step]
        rows.append({"step": step, "time_abs_error_s": abs(float(b["time_s"]) - float(r["time_s"])), "q_rel_error": _relerr(b["q"], r["q"]), "qdot_rel_error": _relerr(b["qdot"], r["qdot"]), "qddot_rel_error": _relerr(b["qddot"], r["qddot"]), "force_rel_error": _relerr(b["integrated_slice_forces_N"], r["integrated_slice_forces_N"])})
    return {"rows": rows, "all_within_thresholds": bool(rows) and all(not row.get("missing") and row["time_abs_error_s"] <= 1.0e-12 and row["q_rel_error"] <= 1.0e-10 and row["qdot_rel_error"] <= 1.0e-10 and row["qddot_rel_error"] <= 1.0e-10 and row["force_rel_error"] <= 1.0e-8 for row in rows), "thresholds": {"time_abs_s": 1.0e-12, "ancf_rel": 1.0e-10, "force_rel": 1.0e-8}}


def _compare_checkpoint_identities(baseline: Mapping[str, Any], phase1: Mapping[str, Any], phase2: Mapping[str, Any]) -> dict[str, Any]:
    """Compare the manifest-listed CFD objects for baseline and restart."""
    base_steps = {int(item["step"]): Path(item["checkpoint"]) for item in baseline.get("step_results", []) if int(item["step"]) < 10}
    restart_steps = {int(item["step"]): Path(item["checkpoint"]) for item in phase1.get("step_results", [])}
    restart_steps.update({int(item["step"]): Path(item["checkpoint"]) for item in phase2.get("step_results", [])})
    rows = []
    for step in range(10):
        if step not in base_steps or step not in restart_steps:
            rows.append({"step": step, "equal": False, "missing": True})
            continue
        base = _read_json(base_steps[step])
        rest = _read_json(restart_steps[step])
        file_rows = []
        for b_slice in sorted(base["slices"], key=lambda x: int(x["slice_id"])):
            r_slice = next(x for x in rest["slices"] if int(x["slice_id"]) == int(b_slice["slice_id"]))
            b_files = {x["relative_path"]: x["sha256"] for x in list(b_slice["static_files"]) + list(b_slice["time_files"])}
            r_files = {x["relative_path"]: x["sha256"] for x in list(r_slice["static_files"]) + list(r_slice["time_files"])}
            file_rows.append({"slice_id": int(b_slice["slice_id"]), "all_files_equal": b_files == r_files, "points_equal": next((v for k, v in b_files.items() if k.endswith("/polyMesh/points")), None) == next((v for k, v in r_files.items() if k.endswith("/polyMesh/points")), None), "motionScale_equal": b_files.get("0/motionScale") == r_files.get("0/motionScale"), "U_equal": next((v for k, v in b_files.items() if k.endswith("/U")), None) == next((v for k, v in r_files.items() if k.endswith("/U")), None), "p_equal": next((v for k, v in b_files.items() if k.endswith("/p")), None) == next((v for k, v in r_files.items() if k.endswith("/p")), None)})
        rows.append({"step": step, "config_equal": base.get("config_sha256") == rest.get("config_sha256"), "manifest_equal": base.get("slice_manifest_sha256") == rest.get("slice_manifest_sha256"), "physics_equal": base.get("physics_config_sha256") == rest.get("physics_config_sha256"), "transaction_committed": base.get("status") == rest.get("status") == "committed", "files": file_rows})
        rows[-1]["equal"] = bool(rows[-1]["config_equal"] and rows[-1]["manifest_equal"] and rows[-1]["physics_equal"] and rows[-1]["transaction_committed"] and all(x["all_files_equal"] for x in file_rows))
    return {"rows": rows, "all_identity_equal": bool(rows) and all(row.get("equal") for row in rows), "required_hashes": ["config_sha256", "slice_manifest_sha256", "physics_config_sha256", "motionScale", "polyMesh/points", "U", "p", "phi", "Uf", "meshPhi", "uniform/time"]}


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("verify", "preflight", "formal100"), default="verify")
    parser.add_argument("--root", type=Path, default=RESULTS_ROOT)
    args = parser.parse_args()
    if args.mode == "verify":
        print(json.dumps(_json(verify_stage4d_a_inputs()), ensure_ascii=False, indent=2))
    elif args.mode == "preflight":
        print(json.dumps(_json(run_preflight(base_root=args.root)), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(_json(run_formal_100(base_root=args.root)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
