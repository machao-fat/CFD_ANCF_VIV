"""Generate the Draft-2 golden manifest/config using production hash code."""

from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coupling.multi_slice_mapping.mapping import (  # noqa: E402
    IDENTITY_R_GL,
    RuntimeConfig,
    SCHEMA_VERSION,
    SliceDefinition,
    SliceManifest,
    atomic_write_json,
)


def main() -> int:
    fixture_dir = HERE / "fixtures"
    manifest = SliceManifest(
        schema_version=SCHEMA_VERSION,
        case_id="golden_two_slice_v2",
        reference_length_m=10.0,
        represented_length_m=10.0,
        R_GL=IDENTITY_R_GL,
        slices=(
            SliceDefinition(0, 2.5, 5.0, 1.0),
            SliceDefinition(1, 7.5, 5.0, 1.0),
        ),
    )
    config = RuntimeConfig(
        schema_version=SCHEMA_VERSION,
        case_id=manifest.case_id,
        dt_s=0.0025,
        timeout_s=30.0,
        start_time_s=0.0,
        coupling_iteration=0,
        coupling_scheme="explicit_weak",
        slice_manifest_sha256=manifest.slice_manifest_sha256,
    )
    atomic_write_json(fixture_dir / "golden_manifest_0.2.1.json", manifest.to_dict())
    atomic_write_json(fixture_dir / "golden_config_0.2.1.json", config.to_dict())
    atomic_write_json(
        fixture_dir / "golden_hashes_0.2.1.json",
        {
            "schema_version": SCHEMA_VERSION,
            "slice_manifest_sha256": manifest.slice_manifest_sha256,
            "config_sha256": config.config_sha256,
        },
    )
    print(manifest.slice_manifest_sha256)
    print(config.config_sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
