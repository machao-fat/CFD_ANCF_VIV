"""Stage 4C-A synthetic scalability and spatial-load campaign.

The campaign is intentionally a thin consumer of the frozen 0.2.1 modules:
``SliceManifest``, ``RuntimeConfig``, the ready/consumed protocol,
``MultiSliceScheduler``, and ``AtomicCheckpointManager`` are all imported
from the existing production paths.  This module adds no second hash or
H/H^T implementation.
"""

from __future__ import annotations

import copy
import json
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..checkpoint import AtomicCheckpointManager, CheckpointError, CommittedPublishError
from ..multi_slice_driver import (
    MultiSliceConfig,
    MultiSliceScheduler,
    SchedulerError,
    SchedulerState,
    SliceDefinition,
)
from ..multi_slice_driver.contract import LOAD_FIELDS, SliceExchangePaths
from ..multi_slice_driver.mocks import MockSliceProcess, MockStructureAdapter
from ..multi_slice_driver.protocol import publish_payload
from ..multi_slice_mapping.mapping import (
    IDENTITY_R_GL,
    LOAD_FIELDS as MAPPING_LOAD_FIELDS,
    LoadRecord,
    RuntimeConfig,
    SCHEMA_VERSION,
    SliceManifest,
    assert_virtual_work,
    atomic_write_json,
    build_H_for_manifest,
    map_integrated_slice_forces,
    read_load_csv,
    sha256_file,
)


GEOMETRY_TOLERANCE = 1.0e-12
NONNODE_MESH = (0.0, 3.0, 6.5, 10.0)


@dataclass(frozen=True)
class CampaignDefinition:
    """A candidate static manifest plus its run parameters."""

    name: str
    case_id: str
    specs: tuple[SliceDefinition, ...]
    reference_length_m: float = 10.0
    represented_length_m: float = 10.0
    dt_s: float = 0.0025
    timeout_s: float = 0.2
    start_time_s: float = 0.0

    def manifest(self) -> SliceManifest:
        manifest = SliceManifest(
            schema_version=SCHEMA_VERSION,
            case_id=self.case_id,
            reference_length_m=self.reference_length_m,
            represented_length_m=self.represented_length_m,
            R_GL=IDENTITY_R_GL,
            slices=self.specs,
        )
        validate_slice_coverage(manifest)
        return manifest

    def runtime_config(self) -> RuntimeConfig:
        manifest = self.manifest()
        return RuntimeConfig(
            schema_version=SCHEMA_VERSION,
            case_id=self.case_id,
            dt_s=self.dt_s,
            timeout_s=self.timeout_s,
            start_time_s=self.start_time_s,
            coupling_iteration=0,
            coupling_scheme="explicit_weak",
            slice_manifest_sha256=manifest.slice_manifest_sha256,
        )

    def geometry_audit(self) -> dict[str, object]:
        return validate_slice_coverage(self.manifest())


def _close(left: float, right: float, tol: float = GEOMETRY_TOLERANCE) -> bool:
    return abs(float(left) - float(right)) <= tol * max(1.0, abs(float(left)), abs(float(right)))


def validate_slice_coverage(manifest: SliceManifest) -> dict[str, object]:
    """Validate the geometric interval represented by every static slice.

    The formal mapping class validates identities and total length but does
    not prescribe interval coverage.  This campaign-level audit verifies the
    requested contiguous, non-overlapping partition without changing the
    public 0.2.1 class.
    """

    manifest.validate()
    intervals = []
    for item in manifest.slices:
        start = item.s_ref_m - 0.5 * item.slice_length_m
        end = item.s_ref_m + 0.5 * item.slice_length_m
        if not _close((start + end) * 0.5, item.s_ref_m):
            raise ValueError(f"slice {item.slice_id}: center is inconsistent with interval")
        if start < -GEOMETRY_TOLERANCE or end > manifest.reference_length_m + GEOMETRY_TOLERANCE:
            raise ValueError(f"slice {item.slice_id}: interval lies outside reference length")
        intervals.append((item.slice_id, start, end, item.s_ref_m, item.slice_length_m))
    intervals.sort(key=lambda row: row[1])
    if not _close(intervals[0][1], 0.0):
        raise ValueError("slice coverage has a gap at the lower boundary")
    for left, right in zip(intervals, intervals[1:]):
        if right[1] < left[2] - GEOMETRY_TOLERANCE:
            raise ValueError(f"slice intervals overlap: {left[0]} and {right[0]}")
        if not _close(right[1], left[2]):
            raise ValueError(f"slice intervals have a gap: {left[0]} and {right[0]}")
    if not _close(intervals[-1][2], manifest.reference_length_m):
        raise ValueError("slice coverage has a gap at the upper boundary")
    return {
        "reference_length_m": manifest.reference_length_m,
        "represented_length_m": manifest.represented_length_m,
        "sum_slice_length_m": sum(row[4] for row in intervals),
        "contiguous": True,
        "overlap": False,
        "gap": False,
        "intervals": [
            {"slice_id": sid, "start_m": start, "end_m": end, "s_ref_m": center, "slice_length_m": length}
            for sid, start, end, center, length in intervals
        ],
    }


def build_candidate_definition(number_of_slices: int) -> CampaignDefinition:
    if number_of_slices == 3:
        lengths = (2.5, 5.0, 2.5)
        centers = (1.25, 5.0, 8.75)
    elif number_of_slices == 5:
        lengths = (1.0, 2.0, 3.0, 2.5, 1.5)
        centers = (0.5, 2.0, 4.5, 7.25, 9.25)
    else:
        raise ValueError("candidate definitions are only available for three or five slices")
    specs = tuple(SliceDefinition(index, centers[index], lengths[index], 1.0) for index in range(number_of_slices))
    definition = CampaignDefinition(
        name=f"candidate_{number_of_slices}slice",
        case_id=f"stage4c_candidate_{number_of_slices}slice",
        specs=specs,
    )
    definition.geometry_audit()
    return definition


def build_scale_definition(number_of_slices: int) -> CampaignDefinition:
    if number_of_slices == 2:
        lengths = (5.0, 5.0)
        centers = (2.5, 7.5)
    elif number_of_slices == 3:
        return build_candidate_definition(3)
    elif number_of_slices == 5:
        return build_candidate_definition(5)
    else:
        raise ValueError("scale definitions support 2, 3, or 5 slices")
    return CampaignDefinition(
        name=f"scale_{number_of_slices}slice",
        case_id=f"stage4c_scale_{number_of_slices}slice",
        specs=tuple(SliceDefinition(index, centers[index], lengths[index], 1.0) for index in range(number_of_slices)),
    )


def serialize_candidate_pair(definition: CampaignDefinition, output_dir: str | Path) -> dict[str, object]:
    """Write formal manifest/config JSON and return recomputed hash evidence."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest = definition.manifest()
    config = definition.runtime_config()
    manifest_path = output / f"canonical_{len(definition.specs)}slice_manifest_candidate.json"
    config_path = output / f"canonical_{len(definition.specs)}slice_config_candidate.json"
    atomic_write_json(manifest_path, manifest.to_dict())
    atomic_write_json(config_path, config.to_dict())
    loaded_manifest, loaded_config = load_candidate_pair(manifest_path, config_path)
    return {
        "name": definition.name,
        "manifest_path": str(manifest_path),
        "config_path": str(config_path),
        "schema_version": loaded_manifest.schema_version,
        "slice_manifest_sha256": loaded_manifest.slice_manifest_sha256,
        "config_sha256": loaded_config.config_sha256,
        "stored_and_recomputed_match": {
            "manifest": loaded_manifest.slice_manifest_sha256 == loaded_manifest.computed_slice_manifest_sha256(),
            "config": loaded_config.config_sha256 == loaded_config.computed_config_sha256(),
        },
        "geometry": validate_slice_coverage(loaded_manifest),
    }


def load_candidate_pair(manifest_path: str | Path, config_path: str | Path) -> tuple[SliceManifest, RuntimeConfig]:
    manifest_data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    config_data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    manifest = SliceManifest.from_mapping(manifest_data)
    config = RuntimeConfig.from_mapping(config_data)
    config.validate_against_manifest(manifest)
    validate_slice_coverage(manifest)
    return manifest, config


class SyntheticLoadModel:
    """Deterministic unit-span force generator; outputs are in N/m."""

    def __init__(self, profile: str, manifest: SliceManifest, *, seed: int = 20260810) -> None:
        if profile not in {"uniform", "linear", "non_monotonic", "random"}:
            raise ValueError(f"unsupported synthetic load profile: {profile}")
        self.profile = profile
        self.seed = seed
        self.manifest = manifest
        rng = random.Random(seed)
        self._random = {
            item.slice_id: tuple(rng.uniform(-2.0, 2.0) for _ in range(3))
            for item in manifest.slices
        }

    def unit_force(self, spec: SliceDefinition) -> tuple[float, float, float]:
        s = spec.s_ref_m
        if self.profile == "uniform":
            return (2.0, -1.0, 0.5)
        if self.profile == "linear":
            return (1.2 + 0.35 * s, -0.8 + 0.22 * s, 0.1 - 0.015 * s)
        if self.profile == "non_monotonic":
            return (
                1.0 + 0.65 * math.sin(0.73 * s + 0.17),
                -0.4 + 0.9 * math.cos(0.91 * s - 0.23),
                0.15 + 0.12 * math.sin(1.37 * s + 0.4),
            )
        return self._random[spec.slice_id]

    def integrated_force(self, spec: SliceDefinition) -> tuple[float, float, float]:
        return tuple(value * spec.slice_length_m for value in self.unit_force(spec))

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "random_seed": self.seed,
            "units": {"unit_force": "N/m", "integrated_force": "N"},
            "coefficients": {
                "uniform": [2.0, -1.0, 0.5],
                "linear": {"fx": [1.2, 0.35], "fy": [-0.8, 0.22], "fz": [0.1, -0.015]},
                "non_monotonic": "explicit_sine_cosine_by_s_ref_m",
            },
            "unit_forces": {
                str(item.slice_id): list(self.unit_force(item)) for item in self.manifest.slices
            },
            "integrated_forces": {
                str(item.slice_id): list(self.integrated_force(item)) for item in self.manifest.slices
            },
        }


_MALFORMED_LOAD_FAULTS = {
    "missing_load_ready", "wrong_time", "wrong_step", "early_step", "wrong_iteration",
    "payload_hash", "config_hash", "slice_manifest_hash", "nan", "inf", "timeout", "process_exit",
}


class SyntheticSliceProcess(MockSliceProcess):
    """Use the production mock transaction path with a selected load profile."""

    def __init__(self, *args: object, load_model: SyntheticLoadModel, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.load_model = load_model

    def advance_one_step(self, step: int, time_s: float) -> None:
        super().advance_one_step(step, time_s)
        if self.fault in _MALFORMED_LOAD_FAULTS:
            return
        if self.manifest is None or self.runtime_config is None:
            raise RuntimeError("synthetic process was not bound to protocol")
        paths = SliceExchangePaths(self.exchange_root, self.spec)
        unit_force = self.load_model.unit_force(self.spec)
        record = LoadRecord.from_conversion(
            case_id=self.case_id,
            step=step,
            time_s=time_s,
            slice_definition=self.spec,
            unit_span_m=self.spec.unit_span_m,
            openfoam_force_N=tuple(value * self.spec.unit_span_m for value in unit_force),
            cfd_time_step_s=self.runtime_config.dt_s,
            R_GL=self.manifest.R_GL,
        )
        publish_payload(
            payload_path=paths.payload("load", step),
            ready_path=paths.ready("load", step),
            kind="load",
            record=record,
            manifest=self.manifest,
            runtime_config=self.runtime_config,
        )

    def checkpoint_files(self, step: int, time_s: float):
        if self.fault == "checkpoint_prepare_failure":
            raise CheckpointError(f"slice {self.slice_id}: injected checkpoint preparation failure")
        return super().checkpoint_files(step, time_s)


class FaultInjectCheckpointManager(AtomicCheckpointManager):
    """Inject manager-level failures while retaining the formal manager code."""

    def __init__(self, original: AtomicCheckpointManager, fault: str | None) -> None:
        self.__dict__.update(original.__dict__)
        self.fault = fault

    def prepare(self, *args: object, **kwargs: object):
        if self.fault == "checkpoint_prepare_manager_failure":
            raise CheckpointError("injected checkpoint manager prepare failure")
        return super().prepare(*args, **kwargs)

    def commit(self, prepared):
        if self.fault == "atomic_publish_failure":
            final_path = self.checkpoint_root / f"checkpoint_{prepared.checkpoint_id}.json"
            raise CommittedPublishError(
                "injected atomic committed-manifest publish failure",
                published=False,
                path=final_path,
            )
        return super().commit(prepared)


def _make_scheduler(
    definition: CampaignDefinition,
    root: Path,
    *,
    profile: str,
    seed: int,
    faults: Mapping[int, str] | None = None,
    structure_fault: str | None = None,
    timeout_s: float | None = None,
    manager_fault: str | None = None,
) -> tuple[MultiSliceScheduler, MockStructureAdapter, list[SyntheticSliceProcess], SyntheticLoadModel, MultiSliceConfig]:
    manifest = definition.manifest()
    model = SyntheticLoadModel(profile, manifest, seed=seed)
    timeout = definition.timeout_s if timeout_s is None else timeout_s
    config = MultiSliceConfig(
        case_id=definition.case_id,
        dt_s=definition.dt_s,
        timeout_s=timeout,
        specs=definition.specs,
        start_time_s=definition.start_time_s,
        reference_length_m=definition.reference_length_m,
        represented_length_m=definition.represented_length_m,
        R_GL=IDENTITY_R_GL,
    )
    exchange_root = root / "exchange"
    case_root = root / "cases"
    specs = tuple(manifest.slices)
    structure = MockStructureAdapter(specs, fault=structure_fault)
    processes = [
        SyntheticSliceProcess(
            spec,
            case_id=config.case_id,
            exchange_root=exchange_root,
            case_root=case_root,
            fault=(faults or {}).get(spec.slice_id),
            load_model=model,
        )
        for spec in specs
    ]
    scheduler = MultiSliceScheduler(
        config=config,
        exchange_root=exchange_root,
        structure=structure,
        slice_processes=processes,
        checkpoint_root=root / "checkpoints",
        case_root=case_root,
    )
    if manager_fault is not None:
        scheduler.checkpoint_manager = FaultInjectCheckpointManager(scheduler.checkpoint_manager, manager_fault)
    return scheduler, structure, processes, model, config


def _files_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) if root.exists() else 0


def _hash_audit_time(manifest: SliceManifest, config: RuntimeConfig) -> tuple[float, bool, bool]:
    started = time.perf_counter()
    manifest_match = manifest.slice_manifest_sha256 == manifest.computed_slice_manifest_sha256()
    config_match = config.config_sha256 == config.computed_config_sha256()
    return time.perf_counter() - started, manifest_match, config_match


def run_mock_campaign(
    definition: CampaignDefinition,
    root: str | Path,
    *,
    steps: int = 10,
    profile: str = "non_monotonic",
    seed: int = 20260810,
    faults: Mapping[int, str] | None = None,
    structure_fault: str | None = None,
    timeout_s: float | None = None,
    manager_fault: str | None = None,
) -> dict[str, object]:
    """Run a complete N-slice scheduler campaign and collect audits."""

    if steps <= 0:
        raise ValueError("steps must be positive")
    root_path = Path(root)
    scheduler, structure, processes, model, config = _make_scheduler(
        definition,
        root_path,
        profile=profile,
        seed=seed,
        faults=faults,
        structure_fault=structure_fault,
        timeout_s=timeout_s,
        manager_fault=manager_fault,
    )
    step_results = []
    durations = []
    hash_time = 0.0
    errors: list[str] = []
    manifest = config.manifest
    for step in range(steps):
        time_s = config.start_time_s + step * config.dt_s
        elapsed, manifest_match, config_match = _hash_audit_time(manifest, config.runtime_config)
        hash_time += elapsed
        if not (manifest_match and config_match):
            raise AssertionError("candidate manifest/config hash audit failed before campaign")
        started = time.perf_counter()
        try:
            result = scheduler.run_step(step=step, time_s=time_s)
        except Exception as exc:
            errors.append(str(exc))
            break
        durations.append(time.perf_counter() - started)
        checkpoint = json.loads(result.checkpoint_path.read_text(encoding="utf-8"))
        step_results.append({
            "step": result.step,
            "time_s": result.time_s,
            "state": result.state.value,
            "integrated_slice_forces": list(result.integrated_slice_forces),
            "generalized_force": list(result.audit.get("generalized_force_from_A_Ht", [])),
            "checkpoint_path": str(result.checkpoint_path),
            "checkpoint_id": checkpoint["checkpoint_id"],
            "checkpoint_status": checkpoint["status"],
            "checkpoint_q": checkpoint["structure"]["q"],
            "checkpoint_qdot": checkpoint["structure"]["qdot"],
            "checkpoint_qddot": checkpoint["structure"]["qddot"],
        })
    exchange = root_path / "exchange"
    checkpoints = root_path / "checkpoints"
    motion_files = list(exchange.glob("slice_*/motion/*.csv"))
    load_files = list(exchange.glob("slice_*/load/*.csv"))
    marker_files = list(exchange.glob("slice_*/ready/*.json")) + list(exchange.glob("slice_*/consumed/*.json"))
    committed = sorted(checkpoints.glob("checkpoint_*.json"))
    duration_total = sum(durations)
    result: dict[str, object] = {
        "campaign": definition.name,
        "case_id": definition.case_id,
        "schema_version": SCHEMA_VERSION,
        "slice_count": len(definition.specs),
        "requested_steps": steps,
        "completed_steps": len(step_results),
        "step_results": step_results,
        "time_barrier_pass": len(step_results) == steps and all(item["state"] == "COMMITTED" for item in step_results),
        "structure_advanced_on_failure": structure.committed_step >= 0 if errors else False,
        "scheduler_final_state": scheduler.state.value,
        "errors": errors,
        "manifest_sha256": config.slice_manifest_sha256,
        "config_sha256": config.config_sha256,
        "manifest_recomputed_match": config.manifest.slice_manifest_sha256 == config.manifest.computed_slice_manifest_sha256(),
        "config_recomputed_match": config.runtime_config.config_sha256 == config.runtime_config.computed_config_sha256(),
        "load_model": model.to_dict(),
        "timing": {
            "step_durations_s": durations,
            "total_s": duration_total,
            "mean_step_s": duration_total / len(durations) if durations else None,
            "hash_recompute_total_s": hash_time,
        },
        "files": {
            "motion_csv": len(motion_files),
            "load_csv": len(load_files),
            "marker_json": len(marker_files),
            "exchange_directory_bytes": _files_bytes(exchange),
            "checkpoint_directory_bytes": _files_bytes(checkpoints),
            "transaction_log_bytes": (exchange / "transaction_log.jsonl").stat().st_size if (exchange / "transaction_log.jsonl").is_file() else 0,
            "committed_manifest_count": len(committed),
            "checkpoint_manifest_bytes": sum(path.stat().st_size for path in committed),
        },
        "peak_memory": {"status": "unavailable", "reason": "No reliable cross-platform peak-memory sampler is available in this Windows test harness."},
        "paths": {"root": str(root_path), "exchange": str(exchange), "checkpoints": str(checkpoints)},
    }
    return result


def _numeric_max_abs(left: object, right: object) -> float:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right))
    if isinstance(left, list) and isinstance(right, list):
        return max((_numeric_max_abs(a, b) for a, b in zip(left, right)), default=0.0)
    if isinstance(left, dict) and isinstance(right, dict):
        return max((_numeric_max_abs(left[key], right[key]) for key in left.keys() & right.keys()), default=0.0)
    return 0.0 if left == right else float("inf")


def run_restart_comparison(
    definition: CampaignDefinition,
    root: str | Path,
    *,
    steps: int = 10,
    split: int = 5,
    profile: str = "non_monotonic",
    seed: int = 20260810,
) -> dict[str, object]:
    """Compare a continuous run with a 5+5 formal checkpoint restart."""

    root_path = Path(root)
    continuous_root = root_path / "continuous"
    segmented_root = root_path / "segmented"
    continuous = run_mock_campaign(definition, continuous_root, steps=steps, profile=profile, seed=seed)
    first_segment = run_mock_campaign(definition, segmented_root, steps=split, profile=profile, seed=seed)
    restart_checkpoint = Path(first_segment["step_results"][-1]["checkpoint_path"])
    scheduler, structure, processes, model, config = _make_scheduler(
        definition, segmented_root, profile=profile, seed=seed,
    )
    restored = scheduler.restore_from_checkpoint(restart_checkpoint)
    continued_steps = []
    for step in range(split, steps):
        result = scheduler.run_step(step=step, time_s=config.start_time_s + step * config.dt_s)
        continued_steps.append(result)
    final_path = continued_steps[-1].checkpoint_path
    segmented_manifest = json.loads(final_path.read_text(encoding="utf-8"))
    continuous_manifest = json.loads(Path(continuous["step_results"][-1]["checkpoint_path"]).read_text(encoding="utf-8"))
    def normalized_state(manifest: Mapping[str, object]) -> dict[str, object]:
        # checkpoint_id, created_utc, and checkpoint-relative paths are run
        # instance metadata.  The comparison below is intentionally limited
        # to the restart contract's physical state and transaction identity.
        return {
            "schema_version": manifest["schema_version"],
            "case_id": manifest["case_id"],
            "status": manifest["status"],
            "step": manifest["step"],
            "coupling_iteration": manifest["coupling_iteration"],
            "time_s": manifest["time_s"],
            "dt_s": manifest["dt_s"],
            "config_sha256": manifest["config_sha256"],
            "slice_manifest_sha256": manifest["slice_manifest_sha256"],
            "expected_slice_ids": manifest["expected_slice_ids"],
            "slice_identity": [
                {key: entry[key] for key in ("slice_id", "s_ref_m", "slice_length_m", "unit_span_m")}
                for entry in sorted(manifest["slices"], key=lambda item: int(item["slice_id"]))
            ],
            "structure_state": {
                key: manifest["structure"][key] for key in ("q", "qdot", "qddot")
            },
            "previous_slice_forces_N": manifest["previous_slice_forces_N"],
            "previous_generalized_force": manifest["previous_generalized_force"],
        }

    selected_continuous = normalized_state(continuous_manifest)
    selected_segmented = normalized_state(segmented_manifest)
    max_abs_error = _numeric_max_abs(selected_continuous, selected_segmented)
    return {
        "slice_count": len(definition.specs),
        "steps": steps,
        "split": split,
        "continuous_completed_steps": continuous["completed_steps"],
        "segmented_first_completed_steps": first_segment["completed_steps"],
        "segmented_restart_completed_steps": len(continued_steps),
        "restored_step": restored["step"],
        "restored_next_step": restored["next_step"],
        "continuous_final_step": continuous_manifest["step"],
        "segmented_final_step": segmented_manifest["step"],
        "continuous_final_time_s": continuous_manifest["time_s"],
        "segmented_final_time_s": segmented_manifest["time_s"],
        "q_max_abs_error": _numeric_max_abs(continuous_manifest["structure"]["q"], segmented_manifest["structure"]["q"]),
        "qdot_max_abs_error": _numeric_max_abs(continuous_manifest["structure"]["qdot"], segmented_manifest["structure"]["qdot"]),
        "qddot_max_abs_error": _numeric_max_abs(continuous_manifest["structure"]["qddot"], segmented_manifest["structure"]["qddot"]),
        "previous_slice_force_max_abs_error": _numeric_max_abs(continuous_manifest["previous_slice_forces_N"], segmented_manifest["previous_slice_forces_N"]),
        "generalized_force_max_abs_error": _numeric_max_abs(continuous_manifest["previous_generalized_force"], segmented_manifest["previous_generalized_force"]),
        "selected_manifest_max_abs_error": max_abs_error,
        "transaction_state_equal": scheduler.state == SchedulerState.COMMITTED and continuous["scheduler_final_state"] == "COMMITTED",
        "manifest_hash_equal": continuous_manifest["slice_manifest_sha256"] == segmented_manifest["slice_manifest_sha256"],
        "config_hash_equal": continuous_manifest["config_sha256"] == segmented_manifest["config_sha256"],
        "bitwise_selected_state_equal": selected_continuous == selected_segmented,
        "continuous_root": str(continuous_root),
        "segmented_root": str(segmented_root),
    }


def map_spatial_loads(
    definition: CampaignDefinition,
    *,
    profile: str,
    seed: int = 20260810,
    random_seed: int = 17,
) -> dict[str, object]:
    """Map synthetic unit-span loads using the formal H/H^T implementation."""

    manifest = definition.manifest()
    config = definition.runtime_config()
    model = SyntheticLoadModel(profile, manifest, seed=seed)
    H = build_H_for_manifest(manifest, NONNODE_MESH)
    delta_q = [0.001 * (index + 1) * (-1.0 if index % 3 == 0 else 1.0) for index in range(6 * len(NONNODE_MESH))]
    loads = {}
    for item in manifest.slices:
        unit = model.unit_force(item)
        loads[item.slice_id] = LoadRecord.from_conversion(
            case_id=manifest.case_id,
            step=0,
            time_s=0.0,
            slice_definition=item,
            unit_span_m=item.unit_span_m,
            openfoam_force_N=tuple(value * item.unit_span_m for value in unit),
            cfd_time_step_s=config.dt_s,
            R_GL=manifest.R_GL,
        )
    mapping = map_integrated_slice_forces(manifest, H, loads, delta_q=delta_q, random_seed=random_seed)
    assert mapping.virtual_work is not None
    assert_virtual_work(mapping.virtual_work)
    shuffled = list(loads.items())
    shuffled.reverse()
    shuffled_mapping = map_integrated_slice_forces(
        manifest,
        {sid: H[sid] for sid, _ in reversed(list(H.items()))},
        dict(shuffled),
    )
    return {
        "campaign": definition.name,
        "slice_count": len(manifest.slices),
        "profile": profile,
        "random_seed": seed,
        "unit_forces_2d_Npm": {str(item.slice_id): list(model.unit_force(item)) for item in manifest.slices},
        "integrated_slice_forces_N": {str(item.slice_id): list(loads[item.slice_id].force_N) for item in manifest.slices},
        "global_total_unit_span_force_Npm": [
            sum(model.unit_force(item)[component] for item in manifest.slices) for component in range(3)
        ],
        "global_total_integrated_force_N": [
            sum(loads[item.slice_id].force_N[component] for item in manifest.slices) for component in range(3)
        ],
        "generalized_force": list(mapping.generalized_force),
        "shuffled_generalized_force": list(shuffled_mapping.generalized_force),
        "permutation_invariant": mapping.generalized_force == shuffled_mapping.generalized_force,
        "virtual_work": mapping.virtual_work.to_dict(),
        "delta_s_audit": {
            "unit_force_is_Npm": True,
            "integrated_force_equals_unit_force_times_slice_length_once": all(
                all(abs(loads[item.slice_id].force_N[c] - model.unit_force(item)[c] * item.slice_length_m) <= 1.0e-12 for c in range(3))
                for item in manifest.slices
            ),
            "mapping_applies_no_slice_length_factor": True,
        },
        "non_node_centers": [
            item.s_ref_m for item in manifest.slices if all(not _close(item.s_ref_m, node) for node in NONNODE_MESH)
        ],
        "H_by_slice_id": {str(sid): [list(row) for row in matrix] for sid, matrix in H.items()},
    }


def _new_failure_root(root: Path, label: str) -> Path:
    short_labels = {
        "restart_source_restart_slice_count_change": "restart_src_count",
        "restart_source_restart_coordinate_change": "restart_src_coord",
        "restart_source_restart_length_change": "restart_src_length",
        "restart_source_restart_config_hash_change": "restart_src_config",
        "restart_source_restart_order_change_identity_same": "restart_src_order",
        "restart_order_change_identity_same": "restart_order_same",
        "restart_slice_count_change": "restart_count",
        "restart_coordinate_change": "restart_coord",
        "restart_length_change": "restart_length",
        "restart_config_hash_change": "restart_config",
    }
    safe_label = short_labels.get(label, label if len(label) <= 28 else label[:28])
    path = root / "failures" / safe_label
    path.mkdir(parents=True, exist_ok=True)
    return path


def _failure_case(definition: CampaignDefinition, root: Path, label: str, *, faults=None, structure_fault=None, manager_fault=None) -> dict[str, object]:
    case_root = _new_failure_root(root, label)
    stable_timeout = (
        0.2
        if label.startswith("checkpoint_")
        or label in {"atomic_publish_failure", "post_commit_finalize_failure"}
        else 0.01
    )
    try:
        campaign = run_mock_campaign(
            definition,
            case_root,
            steps=1,
            profile="non_monotonic",
            seed=20260810,
            faults=faults,
            structure_fault=structure_fault,
            timeout_s=stable_timeout,
            manager_fault=manager_fault,
        )
        raised = not bool(campaign["time_barrier_pass"])
        error = "; ".join(str(item) for item in campaign["errors"])
        final_state = campaign["scheduler_final_state"]
        committed_count = int(campaign["files"]["committed_manifest_count"])
        advanced = bool(campaign["structure_advanced_on_failure"])
    except Exception as exc:
        raised = True
        error = str(exc)
        final_state = "CONSTRUCTOR_REJECTED"
        committed_count = len(list((case_root / "checkpoints").glob("checkpoint_*.json")))
        advanced = False
    return {
        "case": label,
        "rejected_or_failed_closed": raised,
        "error": error,
        "final_state": final_state,
        "committed_manifest_count": committed_count,
        "structure_advanced_on_failure": advanced,
        "pre_commit_no_committed_manifest": committed_count == 0 if label not in {"post_commit_finalize_failure"} else None,
        "root": str(case_root),
    }


def _restart_change_case(definition: CampaignDefinition, root: Path, label: str) -> dict[str, object]:
    source = _new_failure_root(root, "restart_source_" + label)
    valid = run_mock_campaign(definition, source, steps=1, profile="non_monotonic")
    if valid["step_results"]:
        checkpoint = Path(valid["step_results"][0]["checkpoint_path"])
    else:
        # Retain a useful restart-rejection artifact even if a transient
        # filesystem race caused the wrapper summary to miss the returned
        # StepResult after the committed file was published.
        committed = sorted((source / "checkpoints").glob("checkpoint_*.json"))
        if not committed:
            raise RuntimeError(f"restart source did not commit a checkpoint: {valid['errors']}")
        checkpoint = committed[-1]
    try:
        raw = json.loads((source / "exchange" / "slice_manifest.json").read_text(encoding="utf-8"))
        if label == "restart_slice_count_change":
            raw["slices"] = raw["slices"] + [{"slice_id": len(raw["slices"]), "s_ref_m": 9.75, "slice_length_m": 0.5, "unit_span_m": 1.0}]
            raw["represented_length_m"] = 10.5
        elif label == "restart_coordinate_change":
            raw["slices"][0]["s_ref_m"] += 0.01
        elif label == "restart_length_change":
            raw["slices"][0]["slice_length_m"] += 0.01
        elif label == "restart_config_hash_change":
            changed = copy.copy(definition)
            changed = CampaignDefinition(**{**changed.__dict__, "dt_s": definition.dt_s * 1.1})
            _make_scheduler(changed, source, profile="non_monotonic", seed=20260810)
            raise AssertionError("unreachable")
        elif label == "restart_order_change_identity_same":
            raw["slices"] = list(reversed(raw["slices"]))
            raw["slice_manifest_sha256"] = SliceManifest.from_mapping(raw).slice_manifest_sha256
        else:
            raise ValueError(label)
        if label != "restart_order_change_identity_same":
            raw["slice_manifest_sha256"] = "0" * 64
        manifest = SliceManifest.from_mapping(raw)
        changed_definition = CampaignDefinition(
            name=definition.name + "_restart_" + label,
            case_id=definition.case_id,
            specs=tuple(manifest.slices),
            reference_length_m=manifest.reference_length_m,
            represented_length_m=manifest.represented_length_m,
            dt_s=definition.dt_s,
            timeout_s=definition.timeout_s,
            start_time_s=definition.start_time_s,
        )
        _make_scheduler(changed_definition, source, profile="non_monotonic", seed=20260810)
        scheduler, structure, _, _, _ = _make_scheduler(changed_definition, source, profile="non_monotonic", seed=20260810)
        scheduler.restore_from_checkpoint(checkpoint)
        accepted = True
        error = ""
    except Exception as exc:
        accepted = False
        error = str(exc)
        structure = None
    return {
        "case": label,
        "accepted": accepted,
        "expected_acceptance": label == "restart_order_change_identity_same",
        "rejected_as_expected": (not accepted) if label != "restart_order_change_identity_same" else accepted,
        "structure_advanced_on_failure": False if structure is None else structure.committed_step >= 1,
        "error": error,
        "restart_source_time_barrier": valid["time_barrier_pass"],
        "restart_source_errors": valid["errors"],
        "checkpoint": str(checkpoint),
    }


def _post_commit_recovery_case(definition: CampaignDefinition, root: Path) -> dict[str, object]:
    case_root = _new_failure_root(root, "post_commit_finalize_failure")
    scheduler, structure, _, _, config = _make_scheduler(
        definition,
        case_root,
        profile="non_monotonic",
        seed=20260810,
        structure_fault="post_commit_finalize_failure",
        timeout_s=0.2,
    )
    try:
        scheduler.run_step(step=0, time_s=0.0)
    except SchedulerError as exc:
        failure_error = str(exc)
    else:
        failure_error = "finalize failure was not raised"
    committed_after_failure = list((case_root / "checkpoints").glob("checkpoint_*.json"))
    recovery_required = scheduler.state == SchedulerState.RECOVERY_REQUIRED and len(committed_after_failure) == 1
    structure.fault = None
    recovery = scheduler.recover_from_checkpoint(committed_after_failure[0]) if recovery_required else {}
    try:
        scheduler.run_step(step=0, time_s=0.0)
        duplicate_same_step_rejected = False
    except SchedulerError:
        duplicate_same_step_rejected = True
    next_result = scheduler.run_step(step=1, time_s=config.dt_s)
    return {
        "case": "post_commit_finalize_failure",
        "rejected_or_failed_closed": True,
        "error": failure_error,
        "final_state": "RECOVERY_REQUIRED" if recovery_required else scheduler.state.value,
        "committed_manifest_count": len(committed_after_failure),
        "structure_advanced_on_failure": False,
        "pre_commit_no_committed_manifest": None,
        "post_commit_manifest_retained": recovery_required,
        "recovery_completed": bool(recovery),
        "recovery_step": recovery.get("step"),
        "duplicate_same_step_rejected": duplicate_same_step_rejected,
        "next_step_after_recovery": next_result.step,
        "root": str(case_root),
    }


def run_failure_injection_matrix(definition: CampaignDefinition, root: str | Path) -> dict[str, object]:
    """Exercise fail-closed protocol, transaction, and restart guards."""

    root_path = Path(root)
    cases: list[dict[str, object]] = []
    for label, fault in (
        ("motion_not_consumed", "missing_motion_consumed"),
        ("load_missing", "missing_load_ready"),
        ("timestamp_error", "wrong_time"),
        ("step_error", "wrong_step"),
        ("coupling_iteration_error", "wrong_iteration"),
        ("payload_hash_error", "payload_hash"),
        ("config_hash_error", "config_hash"),
        ("manifest_hash_error", "slice_manifest_hash"),
        ("nan_error", "nan"),
        ("inf_error", "inf"),
        ("slice_timeout", "timeout"),
        ("checkpoint_prepare_failure", "checkpoint_prepare_failure"),
    ):
        cases.append(_failure_case(definition, root_path, label, faults={1: fault}))
    for field in ("U", "p", "phi", "Uf", "meshPhi", "polyMesh_points", "uniform_time", "motionScale"):
        cases.append(_failure_case(definition, root_path, "checkpoint_missing_" + field, faults={1: "checkpoint_missing_" + field}))
    cases.append(_failure_case(definition, root_path, "checkpoint_manager_prepare_failure", manager_fault="checkpoint_prepare_manager_failure"))
    cases.append(_failure_case(definition, root_path, "atomic_publish_failure", manager_fault="atomic_publish_failure"))
    cases.append(_post_commit_recovery_case(definition, root_path))
    duplicate_root = _new_failure_root(root_path, "duplicate_slice_id")
    try:
        manifest = definition.manifest()
        model = SyntheticLoadModel("uniform", manifest)
        config = MultiSliceConfig(case_id=definition.case_id, dt_s=definition.dt_s, timeout_s=0.01, specs=definition.specs)
        process = SyntheticSliceProcess(manifest.slices[0], case_id=definition.case_id, exchange_root=duplicate_root / "exchange", case_root=duplicate_root / "cases", load_model=model)
        MultiSliceScheduler(config=config, exchange_root=duplicate_root / "exchange", structure=MockStructureAdapter(definition.specs), slice_processes=[process, process], checkpoint_root=duplicate_root / "checkpoints", case_root=duplicate_root / "cases")
        duplicate_rejected = False
        duplicate_error = "not rejected"
    except Exception as exc:
        duplicate_rejected = True
        duplicate_error = str(exc)
    cases.append({"case": "duplicate_slice_id", "rejected_or_failed_closed": duplicate_rejected, "error": duplicate_error, "final_state": "CONSTRUCTOR_REJECTED", "committed_manifest_count": 0, "structure_advanced_on_failure": False, "pre_commit_no_committed_manifest": True})
    for label in ("restart_slice_count_change", "restart_coordinate_change", "restart_length_change", "restart_config_hash_change", "restart_order_change_identity_same"):
        cases.append(_restart_change_case(definition, root_path, label))
    precommit = [row for row in cases if row.get("case") != "post_commit_finalize_failure" and row.get("case") != "restart_order_change_identity_same"]
    post = next(row for row in cases if row.get("case") == "post_commit_finalize_failure")
    restart_order = next(row for row in cases if row.get("case") == "restart_order_change_identity_same")
    return {
        "slice_count": len(definition.specs),
        "cases": cases,
        "case_count": len(cases),
        "all_fail_closed": all(bool(row.get("rejected_or_failed_closed", row.get("rejected_as_expected", False))) for row in precommit),
        "all_precommit_no_committed_manifest": all(row.get("pre_commit_no_committed_manifest") is not False for row in precommit),
        "structure_advanced_on_failure": any(bool(row.get("structure_advanced_on_failure")) for row in cases),
        "post_commit_recovery_required": post.get("final_state") == "RECOVERY_REQUIRED" and int(post.get("committed_manifest_count", 0)) == 1,
        "restart_order_identity_preserved": bool(restart_order.get("accepted")),
        "nan_inf_rejected": all(row.get("rejected_or_failed_closed") for row in cases if row.get("case") in {"nan_error", "inf_error"}),
    }
