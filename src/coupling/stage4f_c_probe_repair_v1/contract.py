"""Strict, payload-first validation for the R2021b environment probe."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "stage4f-c-probe-repair-v1-1.0.0"
EXPECTED_RELEASE = "2021b"
EXPECTED_ARCHITECTURE = "win64"
EXPECTED_LICENSE = 1
EXPECTED_EXECUTABLE = Path(r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")
EXPECTED_VERSION = re.compile(r"^9\.11(?:\.|\s|$)")
REQUIRED = (
    "schema_version", "run_id", "run_token", "probe_begin", "probe_end", "version",
    "release", "architecture", "license_test_matlab", "TEMP", "TMP", "TMPDIR",
    "tempdir", "prefdir", "pwd", "application_service",
)


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, Mapping):
        return all(_finite(k) and _finite(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return all(_finite(v) for v in value)
    return True


def read_json_payload(path: str | Path) -> dict[str, Any]:
    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant: {value}")

    payload = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(payload, dict) or not _finite(payload):
        raise ValueError("payload must be a finite JSON object")
    return payload


def _normal(path: str | Path) -> Path:
    return Path(str(path).replace("/", "\\")).resolve(strict=False)


def path_is_under(path: str | Path, parent: str | Path) -> bool:
    try:
        _normal(path).relative_to(_normal(parent))
        return True
    except (OSError, ValueError, TypeError):
        return False


def validate_console_consistency(payload: Mapping[str, Any], console_text: str) -> dict[str, Any]:
    """Detect a structured console echo that disagrees with the payload.

    Ordinary MATLAB diagnostics are never used as the source of truth.  A
    launcher may optionally echo ``PROBE_PAYLOAD_JSON=...`` for diagnostics;
    when present it must agree with the file payload on identity fields.
    """
    result = {"console_payload_present": False, "console_payload_valid": True, "mismatch": False}
    marker = "PROBE_PAYLOAD_JSON="
    for line in console_text.splitlines():
        if not line.startswith(marker):
            continue
        result["console_payload_present"] = True
        try:
            echoed = json.loads(line[len(marker):], parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (TypeError, ValueError, json.JSONDecodeError):
            result["console_payload_valid"] = False
            result["mismatch"] = True
            continue
        keys = ("run_id", "run_token", "version", "release", "architecture", "license_test_matlab")
        result["mismatch"] = any(echoed.get(key) != payload.get(key) for key in keys)
    return result


def validate_payload(
    payload: Mapping[str, Any], *, runtime_root: str | Path, return_code: int | None,
    run_id: str, run_token: str, executable: str | Path, console_text: str = "",
) -> dict[str, Any]:
    runtime = _normal(runtime_root)
    tmp_root = runtime / "tmp"
    pref_root = runtime / "matlab_pref"
    checks: dict[str, bool] = {
        "finite_json": _finite(payload),
        "required_fields": all(key in payload for key in REQUIRED),
        "schema": payload.get("schema_version") == SCHEMA,
        "run_id": payload.get("run_id") == run_id,
        "run_token": payload.get("run_token") == run_token,
        "probe_begin": payload.get("probe_begin") is True,
        "probe_end": payload.get("probe_end") is True,
        "version_9_11_series": isinstance(payload.get("version"), str) and bool(EXPECTED_VERSION.match(payload["version"])),
        "release_2021b": payload.get("release") == EXPECTED_RELEASE,
        "architecture_win64": payload.get("architecture") == EXPECTED_ARCHITECTURE,
        "license_test_matlab_one": type(payload.get("license_test_matlab")) is int and payload.get("license_test_matlab") == EXPECTED_LICENSE,
        "TEMP_under_runtime_tmp": path_is_under(payload.get("TEMP", ""), tmp_root),
        "TMP_under_runtime_tmp": path_is_under(payload.get("TMP", ""), tmp_root),
        "TMPDIR_under_runtime_tmp": path_is_under(payload.get("TMPDIR", ""), tmp_root),
        "tempdir_under_runtime_tmp": path_is_under(payload.get("tempdir", ""), tmp_root),
        "prefdir_under_runtime": path_is_under(payload.get("prefdir", ""), pref_root),
        "pwd_under_runtime": path_is_under(payload.get("pwd", ""), runtime),
        "application_service_ok": payload.get("application_service") == "ok",
        "executable_exact": _normal(executable) == _normal(EXPECTED_EXECUTABLE),
        "return_code_zero": return_code == 0,
    }
    console = validate_console_consistency(payload, console_text)
    checks["payload_console_consistent"] = not console["mismatch"]
    return {"checks": checks, "all_checks_passed": all(checks.values()), "payload": dict(payload), "return_code": return_code, "console_consistency": console}
