from __future__ import annotations

import json
import math
import random
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT / "src"))

from coupling.multi_slice_mapping.mapping import (  # noqa: E402
    IDENTITY_R_GL,
    LOAD_FIELDS,
    MOTION_FIELDS,
    SCHEMA_VERSION,
    ConsumedMarker,
    HashValidationError,
    IdentityError,
    LoadRecord,
    MappingError,
    MotionRecord,
    NumericValidationError,
    RuntimeConfig,
    SchemaError,
    SliceDefinition,
    SliceManifest,
    VirtualWorkError,
    ancf_hermite_H,
    assert_virtual_work,
    atomic_write_csv,
    build_H_for_manifest,
    canonical_json,
    convert_openfoam_force,
    create_consumed_marker,
    create_ready_marker,
    global_to_local,
    interpolate_ancf_state,
    local_to_global,
    map_integrated_slice_forces,
    motion_from_ancf_state,
    read_load_csv,
    read_motion_csv,
    sha256_json,
    validate_load_record,
    validate_motion_record,
    validate_record_transaction,
)


METRICS = {
    "max_force_conversion_relative_error": 0.0,
    "max_virtual_work_absolute_error": 0.0,
    "max_virtual_work_relative_error": 0.0,
    "permutation_test_pass": False,
    "missing_slice_rejected": False,
    "duplicate_slice_rejected": False,
    "unexpected_slice_rejected": False,
    "nan_inf_rejected": False,
    "hash_tamper_rejected": False,
    "delta_s_applied_once": False,
    "old_schema_rejected": False,
    "golden_hash_repeat_pass": False,
    "config_manifest_independent_pass": False,
}


def make_manifest(lengths, refs=None, *, reference_length=10.0, case_id="synthetic", unit_spans=None):
    lengths = tuple(float(value) for value in lengths)
    if refs is None:
        refs = tuple((index + 0.5) * reference_length / len(lengths) for index in range(len(lengths)))
    if unit_spans is None:
        unit_spans = (1.0,) * len(lengths)
    slices = tuple(
        SliceDefinition(index, refs[index], lengths[index], unit_spans[index])
        for index in range(len(lengths))
    )
    return SliceManifest(
        schema_version=SCHEMA_VERSION,
        case_id=case_id,
        reference_length_m=reference_length,
        represented_length_m=sum(lengths),
        slices=slices,
    )


def make_config(manifest, *, dt_s=0.0025, timeout_s=30.0, start_time_s=0.0):
    return RuntimeConfig(
        schema_version=SCHEMA_VERSION,
        case_id=manifest.case_id,
        dt_s=dt_s,
        timeout_s=timeout_s,
        start_time_s=start_time_s,
        coupling_iteration=0,
        coupling_scheme="explicit_weak",
        slice_manifest_sha256=manifest.slice_manifest_sha256,
    )


def make_motion(manifest, slice_id, *, step=4, time_s=0.04, y=0.0):
    item = manifest.slice(slice_id)
    return MotionRecord(
        schema_version=SCHEMA_VERSION,
        case_id=manifest.case_id,
        step=step,
        coupling_iteration=0,
        time_s=time_s,
        slice_id=item.slice_id,
        s_ref_m=item.s_ref_m,
        slice_length_m=item.slice_length_m,
        x_ref_m=0.0,
        y_ref_m=0.0,
        z_ref_m=item.s_ref_m,
        ux_m=0.0,
        uy_m=y,
        uz_m=0.0,
        x_m=0.0,
        y_m=y,
        z_m=item.s_ref_m,
        vx_mps=0.0,
        vy_mps=0.0,
        vz_mps=0.0,
        ax_mps2=0.0,
        ay_mps2=0.0,
        az_mps2=0.0,
    )


def make_load(manifest, slice_id, force=(0.0, 1.0, 0.0), *, unit_span=1.0, step=4, time_s=0.04):
    return LoadRecord.from_conversion(
        case_id=manifest.case_id,
        step=step,
        time_s=time_s,
        slice_definition=manifest.slice(slice_id),
        unit_span_m=unit_span,
        openfoam_force_N=force,
        cfd_time_step_s=0.001,
        R_GL=manifest.R_GL,
    )


def load_fixture(name):
    return json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))


class MultiSliceMappingTests(unittest.TestCase):
    def test_single_slice_compatibility(self):
        manifest = make_manifest((1.0,), refs=(0.5,), reference_length=1.0)
        record = make_motion(manifest, 0)
        self.assertIs(validate_motion_record(record, manifest, expected_step=4, expected_time_s=0.04), record)
        H = {0: ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))}
        result = map_integrated_slice_forces(manifest, H, {0: (2.0, -3.0, 4.0)})
        self.assertEqual(result.generalized_force, (2.0, -3.0, 4.0))

    def test_two_uniform_slices(self):
        manifest = make_manifest((5.0, 5.0), refs=(2.5, 7.5), reference_length=10.0)
        self.assertAlmostEqual(manifest.represented_length_m, 10.0)
        self.assertEqual([item.slice_id for item in manifest.slices], [0, 1])

    def test_five_uniform_slices(self):
        manifest = make_manifest((2.0,) * 5, reference_length=10.0)
        self.assertEqual(len(manifest.slices), 5)
        self.assertAlmostEqual(sum(item.slice_length_m for item in manifest.slices), 10.0)

    def test_nonuniform_slice_lengths(self):
        manifest = make_manifest((0.5, 1.0, 2.5), refs=(0.25, 1.0, 2.75), reference_length=5.0)
        self.assertAlmostEqual(manifest.represented_length_m, 4.0)
        self.assertEqual(manifest.slice(2).slice_length_m, 2.5)

    def test_end_half_slices(self):
        manifest = make_manifest((0.5, 2.0, 2.0, 0.5), refs=(0.0, 1.25, 3.25, 4.0), reference_length=4.0)
        self.assertEqual(manifest.slice(0).s_ref_m, 0.0)
        self.assertEqual(manifest.slice(3).slice_length_m, 0.5)

    def test_slice_between_ancf_nodes_and_multiple_in_one_element(self):
        manifest = make_manifest((1.0, 1.0), refs=(1.2, 2.4), reference_length=5.0)
        Hs = build_H_for_manifest(manifest, (0.0, 3.0, 5.0))
        self.assertEqual(len(Hs[0]), 3)
        self.assertEqual(len(Hs[0][0]), 18)
        self.assertNotEqual(Hs[0], Hs[1])

    def test_node_coincidence_on_nonuniform_mesh(self):
        H = ancf_hermite_H(3.0, (0.0, 3.0, 5.0))
        self.assertAlmostEqual(H[0][6], 1.0)
        self.assertAlmostEqual(H[1][7], 1.0)
        self.assertAlmostEqual(H[2][8], 1.0)

    def test_input_rows_are_restored_by_slice_id(self):
        manifest = make_manifest((1.0, 1.0, 1.0), reference_length=3.0)
        rows = [make_motion(manifest, sid) for sid in (2, 0, 1)]
        normalized = validate_record_transaction(rows, manifest, kind="motion", expected_step=4, expected_time_s=0.04)
        self.assertEqual(list(normalized), [0, 1, 2])
        METRICS["permutation_test_pass"] = True

    def test_missing_slice_rejected(self):
        manifest = make_manifest((1.0, 1.0), reference_length=2.0)
        with self.assertRaises(IdentityError):
            validate_record_transaction([make_motion(manifest, 0)], manifest, kind="motion")
        METRICS["missing_slice_rejected"] = True

    def test_duplicate_slice_rejected(self):
        manifest = make_manifest((1.0, 1.0), reference_length=2.0)
        with self.assertRaises(IdentityError):
            validate_record_transaction([make_motion(manifest, 0), make_motion(manifest, 0)], manifest, kind="motion")
        METRICS["duplicate_slice_rejected"] = True

    def test_unexpected_slice_rejected(self):
        manifest = make_manifest((1.0, 1.0), reference_length=2.0)
        invalid = replace(make_motion(manifest, 0), slice_id=2)
        with self.assertRaises(IdentityError):
            validate_record_transaction([invalid, make_motion(manifest, 1)], manifest, kind="motion")
        METRICS["unexpected_slice_rejected"] = True

    def test_duplicate_slice_id_manifest_rejected(self):
        manifest_dict = make_manifest((1.0, 1.0), reference_length=2.0).to_dict()
        manifest_dict["slices"][1]["slice_id"] = 0
        with self.assertRaises(IdentityError):
            SliceManifest.from_mapping(manifest_dict)

    def test_duplicate_s_ref_rejected(self):
        with self.assertRaises(IdentityError):
            make_manifest((1.0, 1.0), refs=(0.5, 0.5), reference_length=2.0)

    def test_nan_rejected(self):
        manifest = make_manifest((1.0,), reference_length=1.0)
        with self.assertRaises(NumericValidationError):
            replace(make_motion(manifest, 0), uy_m=float("nan"))
        METRICS["nan_inf_rejected"] = True

    def test_inf_rejected(self):
        manifest = make_manifest((1.0,), reference_length=1.0)
        with self.assertRaises(NumericValidationError):
            replace(make_motion(manifest, 0), vz_mps=float("inf"))
        METRICS["nan_inf_rejected"] = True

    def test_step_inconsistency_rejected(self):
        manifest = make_manifest((1.0, 1.0), reference_length=2.0)
        with self.assertRaises(IdentityError):
            validate_record_transaction(
                [make_motion(manifest, 0, step=4), make_motion(manifest, 1, step=5)], manifest, kind="motion"
            )

    def test_time_inconsistency_rejected(self):
        manifest = make_manifest((1.0, 1.0), reference_length=2.0)
        with self.assertRaises(IdentityError):
            validate_record_transaction(
                [make_motion(manifest, 0, time_s=0.04), make_motion(manifest, 1, time_s=0.05)], manifest, kind="motion"
            )

    def test_nonzero_coupling_iteration_rejected(self):
        manifest = make_manifest((1.0,), reference_length=1.0)
        with self.assertRaises(SchemaError):
            replace(make_motion(manifest, 0), coupling_iteration=1)

    def test_s_ref_tamper_rejected(self):
        manifest = make_manifest((1.0,), refs=(0.5,), reference_length=1.0)
        tampered = replace(make_motion(manifest, 0), s_ref_m=0.0)
        with self.assertRaises(IdentityError):
            validate_motion_record(tampered, manifest)

    def test_slice_length_tamper_rejected(self):
        manifest = make_manifest((1.0,), refs=(0.5,), reference_length=1.0)
        tampered = replace(make_motion(manifest, 0), slice_length_m=2.0)
        with self.assertRaises(IdentityError):
            validate_motion_record(tampered, manifest)

    def test_payload_tamper_after_ready_rejected(self):
        manifest = make_manifest((1.0,), reference_length=1.0)
        config = make_config(manifest)
        record = make_load(manifest, 0, force=(0.0, 2.0, 0.0))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "load_step00000004_iter0000.csv"
            atomic_write_csv(path, LOAD_FIELDS, record.to_dict())
            marker = create_ready_marker(path, record, manifest, config, payload_kind="load")
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaises(HashValidationError):
                read_load_csv(path, manifest, expected_step=4, expected_time_s=0.04, runtime_config=config, ready_marker=marker)
        METRICS["hash_tamper_rejected"] = True

    def test_config_sha256_wrong_rejected(self):
        manifest = make_manifest((1.0,), reference_length=1.0)
        config_dict = make_config(manifest).to_dict()
        config_dict["config_sha256"] = "0" * 64
        with self.assertRaises(HashValidationError):
            RuntimeConfig.from_mapping(config_dict)

    def test_manifest_rejects_embedded_config(self):
        manifest_dict = make_manifest((1.0,), reference_length=1.0).to_dict()
        manifest_dict["config"] = {"dt_s": 0.0025}
        with self.assertRaises(SchemaError):
            SliceManifest.from_mapping(manifest_dict)

    def test_slice_manifest_sha256_wrong_rejected(self):
        manifest_dict = make_manifest((1.0,), reference_length=1.0).to_dict()
        manifest_dict["slice_manifest_sha256"] = "1" * 64
        with self.assertRaises(HashValidationError):
            SliceManifest.from_mapping(manifest_dict)

    def test_delta_s_is_applied_once(self):
        manifest = make_manifest((0.25,), refs=(0.125,), reference_length=0.25)
        conversion = convert_openfoam_force((10.0, 0.0, 0.0), 1.0, 0.25)
        self.assertEqual(conversion.force_N, (2.5, 0.0, 0.0))
        result = map_integrated_slice_forces(
            manifest,
            {0: ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))},
            {0: conversion},
        )
        self.assertEqual(result.generalized_force, (2.5, 0.0, 0.0))
        METRICS["max_force_conversion_relative_error"] = max(
            METRICS["max_force_conversion_relative_error"],
            max(_relative(actual, expected) for actual, expected in zip(conversion.force_N, (2.5, 0.0, 0.0))),
        )
        METRICS["delta_s_applied_once"] = True

    def test_uniform_constant_force_total(self):
        manifest = make_manifest((0.2,) * 5, reference_length=1.0)
        H = {sid: ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)) for sid in range(5)}
        loads = {sid: make_load(manifest, sid, force=(0.0, 2.0, 0.0)) for sid in range(5)}
        result = map_integrated_slice_forces(manifest, H, loads)
        self.assertAlmostEqual(result.generalized_force[1], 2.0)

    def test_antisymmetric_slice_forces_cancel(self):
        manifest = make_manifest((0.5, 0.5), refs=(0.25, 0.75), reference_length=1.0)
        H = {sid: ((1.0,), (0.0,), (0.0,)) for sid in range(2)}
        # Use a custom 3 x 1 H and opposite integrated forces.
        result = map_integrated_slice_forces(manifest, H, {0: (1.0, 0.0, 0.0), 1: (-1.0, 0.0, 0.0)})
        self.assertAlmostEqual(result.generalized_force[0], 0.0)

    def test_random_virtual_work_conservation(self):
        manifest = make_manifest((1.0,) * 5, reference_length=5.0)
        H = build_H_for_manifest(manifest, (0.0, 1.5, 3.0, 5.0))
        rng = random.Random(17)
        forces = {sid: tuple(rng.uniform(-3.0, 3.0) for _ in range(3)) for sid in range(5)}
        delta_q = [rng.uniform(-1.0, 1.0) for _ in range(24)]
        result = map_integrated_slice_forces(manifest, H, forces, delta_q=delta_q, random_seed=17)
        self.assertIsNotNone(result.virtual_work)
        assert_virtual_work(result.virtual_work)
        METRICS["max_virtual_work_absolute_error"] = max(METRICS["max_virtual_work_absolute_error"], result.virtual_work.error_abs_J)
        METRICS["max_virtual_work_relative_error"] = max(METRICS["max_virtual_work_relative_error"], result.virtual_work.error_rel)

    def test_multiple_random_seeds_virtual_work(self):
        manifest = make_manifest((0.5,) * 4, reference_length=2.0)
        H = build_H_for_manifest(manifest, (0.0, 0.6, 1.1, 2.0))
        for seed in (0, 1, 5, 19, 42):
            rng = random.Random(seed)
            forces = {sid: tuple(rng.uniform(-10.0, 10.0) for _ in range(3)) for sid in range(4)}
            delta_q = [rng.uniform(-2.0, 2.0) for _ in range(24)]
            audit = map_integrated_slice_forces(manifest, H, forces, delta_q=delta_q, random_seed=seed).virtual_work
            assert_virtual_work(audit)
            METRICS["max_virtual_work_absolute_error"] = max(METRICS["max_virtual_work_absolute_error"], audit.error_abs_J)
            METRICS["max_virtual_work_relative_error"] = max(METRICS["max_virtual_work_relative_error"], audit.error_rel)

    def test_local_global_local_roundtrip(self):
        rotation = ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        local = (1.25, -4.0, 2.0)
        global_force = local_to_global(local, rotation)
        self.assertEqual(global_force, (4.0, 1.25, 2.0))
        self.assertEqual(global_to_local(global_force, rotation), local)

    def test_nonunit_openfoam_span(self):
        conversion = convert_openfoam_force((6.0, -3.0, 0.0), 2.0, 0.5)
        self.assertEqual(conversion.force_2d_Npm, (3.0, -1.5, 0.0))
        self.assertEqual(conversion.force_N, (1.5, -0.75, 0.0))

    def test_represented_length_can_be_a_configured_subsection(self):
        manifest = make_manifest((1.0, 1.0), refs=(2.0, 8.0), reference_length=10.0)
        self.assertEqual(manifest.represented_length_m, 2.0)
        self.assertNotEqual(manifest.represented_length_m, manifest.reference_length_m)

    def test_old_schema_is_explicitly_rejected(self):
        with self.assertRaises(SchemaError):
            MotionRecord(
                schema_version="0.1.0", case_id="old", step=0, coupling_iteration=0, time_s=0.0,
                slice_id=0, s_ref_m=0.0, slice_length_m=1.0,
                x_ref_m=0.0, y_ref_m=0.0, z_ref_m=0.0, ux_m=0.0, uy_m=0.0, uz_m=0.0,
                x_m=0.0, y_m=0.0, z_m=0.0, vx_mps=0.0, vy_mps=0.0, vz_mps=0.0,
                ax_mps2=0.0, ay_mps2=0.0, az_mps2=0.0,
            )
        METRICS["old_schema_rejected"] = True

    def test_motion_interpolation_uses_same_H_for_r_v_a(self):
        H = ((1.0, 2.0), (3.0, 4.0), (5.0, 6.0))
        state = interpolate_ancf_state(H, (1.0, 2.0), (2.0, 3.0), (4.0, 5.0))
        self.assertEqual(state[0], (5.0, 11.0, 17.0))
        self.assertEqual(state[1], (8.0, 18.0, 28.0))
        self.assertEqual(state[2], (14.0, 32.0, 50.0))

    def test_motion_record_from_ancf_state(self):
        manifest = make_manifest((1.0,), refs=(0.5,), reference_length=1.0)
        H = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        record = motion_from_ancf_state(
            manifest, 0, H, (0.1, 0.2, 0.6), (1.0, 2.0, 3.0), (4.0, 5.0, 6.0), step=0, time_s=0.0
        )
        self.assertAlmostEqual(record.ux_m, 0.1)
        self.assertAlmostEqual(record.uy_m, 0.2)
        self.assertAlmostEqual(record.uz_m, 0.1)
        self.assertEqual((record.vx_mps, record.vy_mps, record.vz_mps), (1.0, 2.0, 3.0))

    def test_marker_roundtrip_and_consumed_marker(self):
        manifest = make_manifest((1.0,), reference_length=1.0)
        config = make_config(manifest)
        record = make_motion(manifest, 0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "motion_step00000004_iter0000.csv"
            atomic_write_csv(path, MOTION_FIELDS, record.to_dict())
            ready = create_ready_marker(path, record, manifest, config, payload_kind="motion")
            ready.validate_against(manifest, config, expected_step=4, expected_time_s=0.04, payload_path=path)
            consumed = create_consumed_marker(ready, manifest, config, "synthetic-test", payload_path=path)
            parsed = ConsumedMarker.from_mapping(consumed.to_dict())
            parsed.validate_against(manifest, config, expected_step=4, expected_time_s=0.04, payload_path=path)
            self.assertEqual(parsed.consumer, "synthetic-test")

    def test_canonical_hash_is_order_independent(self):
        left = {"b": 2, "a": [1, 3]}
        right = {"a": [1, 3], "b": 2}
        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(sha256_json(left), sha256_json(right))

    def test_rotation_matrix_must_be_proper(self):
        with self.assertRaises(NumericValidationError):
            SliceManifest(
                schema_version=SCHEMA_VERSION, case_id="bad", reference_length_m=1.0,
                represented_length_m=1.0, slices=(SliceDefinition(0, 0.5, 1.0, 1.0),),
                R_GL=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0)),
            )

    def test_mapping_rejects_missing_H_or_force(self):
        manifest = make_manifest((1.0, 1.0), reference_length=2.0)
        H = {0: ((1.0,), (0.0,), (0.0,))}
        with self.assertRaises(MappingError):
            map_integrated_slice_forces(manifest, H, {0: (1.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0)})

    def test_golden_fixture_has_exact_independent_field_sets_and_hashes(self):
        manifest_dict = load_fixture("golden_manifest_0.2.1.json")
        config_dict = load_fixture("golden_config_0.2.1.json")
        hashes = load_fixture("golden_hashes_0.2.1.json")
        manifest = SliceManifest.from_mapping(manifest_dict)
        config = RuntimeConfig.from_mapping(config_dict)
        config.validate_against_manifest(manifest)
        self.assertEqual(
            set(manifest_dict),
            {"schema_version", "case_id", "reference_length_m", "represented_length_m", "R_GL", "slices", "slice_manifest_sha256"},
        )
        self.assertEqual(
            set(config_dict),
            {"schema_version", "case_id", "dt_s", "timeout_s", "start_time_s", "coupling_iteration", "coupling_scheme", "slice_manifest_sha256", "config_sha256"},
        )
        self.assertEqual(manifest.slice_manifest_sha256, hashes["slice_manifest_sha256"])
        self.assertEqual(config.config_sha256, hashes["config_sha256"])
        self.assertEqual(manifest.computed_slice_manifest_sha256(), hashes["slice_manifest_sha256"])
        self.assertEqual(config.computed_config_sha256(), config.config_sha256)
        METRICS["golden_hash_repeat_pass"] = True
        METRICS["config_manifest_independent_pass"] = True

    def test_golden_hash_inputs_exclude_self_hash_fields(self):
        manifest_dict = load_fixture("golden_manifest_0.2.1.json")
        config_dict = load_fixture("golden_config_0.2.1.json")
        hashes = load_fixture("golden_hashes_0.2.1.json")
        manifest_content = dict(manifest_dict)
        manifest_content.pop("slice_manifest_sha256")
        config_content = dict(config_dict)
        config_content.pop("config_sha256")
        self.assertEqual(sha256_json(manifest_content), hashes["slice_manifest_sha256"])
        self.assertEqual(sha256_json(config_content), hashes["config_sha256"])

    def test_manifest_and_config_field_order_does_not_change_hash(self):
        manifest_dict = load_fixture("golden_manifest_0.2.1.json")
        config_dict = load_fixture("golden_config_0.2.1.json")
        manifest_reordered = dict(reversed(list(manifest_dict.items())))
        manifest_reordered["slices"] = list(reversed(manifest_reordered["slices"]))
        config_reordered = dict(reversed(list(config_dict.items())))
        self.assertEqual(
            SliceManifest.from_mapping(manifest_reordered).slice_manifest_sha256,
            SliceManifest.from_mapping(manifest_dict).slice_manifest_sha256,
        )
        self.assertEqual(
            RuntimeConfig.from_mapping(config_reordered).config_sha256,
            RuntimeConfig.from_mapping(config_dict).config_sha256,
        )

    def test_numeric_changes_change_only_the_relevant_hash(self):
        manifest = SliceManifest.from_mapping(load_fixture("golden_manifest_0.2.1.json"))
        changed_manifest = SliceManifest(
            schema_version=SCHEMA_VERSION,
            case_id=manifest.case_id,
            reference_length_m=manifest.reference_length_m,
            represented_length_m=manifest.represented_length_m,
            R_GL=manifest.R_GL,
            slices=(
                SliceDefinition(0, 2.6, 5.0, 1.0),
                SliceDefinition(1, 7.5, 5.0, 1.0),
            ),
        )
        self.assertNotEqual(changed_manifest.slice_manifest_sha256, manifest.slice_manifest_sha256)
        config = make_config(manifest)
        changed_config = RuntimeConfig(
            schema_version=SCHEMA_VERSION,
            case_id=manifest.case_id,
            dt_s=0.00125,
            timeout_s=config.timeout_s,
            start_time_s=config.start_time_s,
            coupling_iteration=0,
            coupling_scheme="explicit_weak",
            slice_manifest_sha256=manifest.slice_manifest_sha256,
        )
        self.assertNotEqual(changed_config.config_sha256, config.config_sha256)
        self.assertEqual(changed_config.slice_manifest_sha256, manifest.slice_manifest_sha256)

    def test_runtime_config_rejects_embedded_manifest(self):
        config_dict = load_fixture("golden_config_0.2.1.json")
        config_dict["slices"] = []
        with self.assertRaises(SchemaError):
            RuntimeConfig.from_mapping(config_dict)

    def test_old_020_manifest_and_config_are_rejected(self):
        manifest_dict = load_fixture("golden_manifest_0.2.1.json")
        config_dict = load_fixture("golden_config_0.2.1.json")
        manifest_dict["schema_version"] = "0.2.0"
        config_dict["schema_version"] = "0.2.0"
        with self.assertRaises(SchemaError):
            SliceManifest.from_mapping(manifest_dict)
        with self.assertRaises(SchemaError):
            RuntimeConfig.from_mapping(config_dict)

    def test_missing_unit_span_is_rejected(self):
        manifest_dict = load_fixture("golden_manifest_0.2.1.json")
        del manifest_dict["slices"][0]["unit_span_m"]
        with self.assertRaises(SchemaError):
            SliceManifest.from_mapping(manifest_dict)

    def test_nonunit_static_span_is_used_once_and_mismatch_is_rejected(self):
        manifest = make_manifest(
            (0.5, 0.5), refs=(0.25, 0.75), reference_length=1.0, unit_spans=(2.0, 2.0)
        )
        record = make_load(manifest, 0, force=(6.0, 0.0, 0.0), unit_span=2.0)
        self.assertEqual(record.force_2d_Npm, (3.0, 0.0, 0.0))
        self.assertEqual(record.force_N, (1.5, 0.0, 0.0))
        validate_load_record(record, manifest)
        with self.assertRaises(IdentityError):
            make_load(manifest, 0, force=(6.0, 0.0, 0.0), unit_span=1.0)
        mismatched_manifest = make_manifest(
            (0.5, 0.5), refs=(0.25, 0.75), reference_length=1.0, unit_spans=(1.0, 1.0)
        )
        with self.assertRaises(IdentityError):
            validate_load_record(record, mismatched_manifest)

    def test_runtime_config_rejects_nonzero_iteration_and_wrong_scheme(self):
        manifest = make_manifest((1.0,), reference_length=1.0)
        with self.assertRaises(SchemaError):
            RuntimeConfig(
                schema_version=SCHEMA_VERSION, case_id=manifest.case_id, dt_s=0.1,
                timeout_s=1.0, start_time_s=0.0, coupling_iteration=1,
                coupling_scheme="explicit_weak", slice_manifest_sha256=manifest.slice_manifest_sha256,
            )
        with self.assertRaises(SchemaError):
            RuntimeConfig(
                schema_version=SCHEMA_VERSION, case_id=manifest.case_id, dt_s=0.1,
                timeout_s=1.0, start_time_s=0.0, coupling_iteration=0,
                coupling_scheme="strong", slice_manifest_sha256=manifest.slice_manifest_sha256,
            )

    def test_marker_config_hash_tamper_is_rejected(self):
        manifest = make_manifest((1.0,), reference_length=1.0)
        config = make_config(manifest)
        record = make_motion(manifest, 0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "motion_step00000004_iter0000.csv"
            atomic_write_csv(path, MOTION_FIELDS, record.to_dict())
            ready = create_ready_marker(path, record, manifest, config, payload_kind="motion")
            tampered = ready.to_dict()
            tampered["config_sha256"] = "0" * 64
            parsed = ready.__class__.from_mapping(tampered)
            with self.assertRaises(HashValidationError):
                parsed.validate_against(manifest, config, payload_path=path)


def _relative(actual, expected):
    return abs(actual - expected) / max(1.0, abs(actual), abs(expected))


if __name__ == "__main__":
    unittest.main(verbosity=2)
