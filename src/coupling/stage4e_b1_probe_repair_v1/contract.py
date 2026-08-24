"""Strict structured-payload contract for the repaired MATLAB probe."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "stage4e-b1-probe-repair-v1-1.0.0"
EXPECTED_RELEASE = "2021b"
EXPECTED_ARCHITECTURE = "win64"
EXPECTED_LICENSE = 1
EXPECTED_VERSION = re.compile(r"^9\.11(?:\.|$)")
EXPECTED_EXECUTABLE = Path(r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")


def _normal(path: str | Path) -> Path:
    return Path(str(path).replace("/", "\\")).resolve(strict=False)


def path_is_under(path: str | Path, parent: str | Path) -> bool:
    try:
        _normal(path).relative_to(_normal(parent))
        return True
    except (OSError, ValueError, TypeError):
        return False


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, Mapping):
        return all(_finite(key) and _finite(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return all(_finite(item) for item in value)
    return True


def read_json_payload(path: str | Path) -> dict[str, Any]:
    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant: {value}")

    payload = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(payload, dict) or not _finite(payload):
        raise ValueError("payload must be a finite JSON object")
    return payload


def validate_payload(
    payload: Mapping[str, Any], *, runtime_root: str | Path, return_code: int | None,
    run_id: str, run_token: str, executable: str | Path,
) -> dict[str, Any]:
    runtime = _normal(runtime_root)
    tmp_root = runtime / "tmp"
    pref_root = runtime / "matlab_pref"
    checks = {
        "finite_json": _finite(payload),
        "schema": payload.get("schema_version") == SCHEMA,
        "run_id": payload.get("run_id") == run_id,
        "run_token": payload.get("run_token") == run_token,
        "probe_begin": payload.get("probe_begin") is True,
        "probe_end": payload.get("probe_end") is True,
        "version_9_11_series": isinstance(payload.get("version"), str) and bool(EXPECTED_VERSION.match(payload["version"])),
        "release_2021b": payload.get("release") == EXPECTED_RELEASE,
        "architecture_win64": payload.get("architecture") == EXPECTED_ARCHITECTURE,
        "license_test_matlab_one": type(payload.get("license_test_matlab")) is int and payload.get("license_test_matlab") == EXPECTED_LICENSE,
        "temp_on_d": path_is_under(payload.get("TEMP", ""), tmp_root),
        "tmp_on_d": path_is_under(payload.get("TMP", ""), tmp_root),
        "tmpdir_on_d": path_is_under(payload.get("TMPDIR", ""), tmp_root),
        "tempdir_on_d": path_is_under(payload.get("tempdir", ""), tmp_root),
        "prefdir_on_d": path_is_under(payload.get("prefdir", ""), pref_root),
        "pwd_on_d": path_is_under(payload.get("pwd", ""), runtime),
        "application_service_ok": payload.get("application_service") == "ok",
        "executable_exact": _normal(executable) == _normal(EXPECTED_EXECUTABLE),
        "return_code_zero": return_code == 0,
    }
    return {"checks": checks, "all_checks_passed": all(checks.values()), "payload": dict(payload), "return_code": return_code}
