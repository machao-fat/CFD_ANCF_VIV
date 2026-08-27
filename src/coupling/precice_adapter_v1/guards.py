from __future__ import annotations

from typing import Mapping, Any


class NoCfdViolation(ValueError):
    """Raised when a probe-only contract attempts to authorize a solver."""


def validate_probe_only_contract(contract: Mapping[str, Any]) -> None:
    """Fail closed unless all four solver prohibitions are explicit and true."""
    required = ("no_cfd", "no_correction", "no_openfoam", "no_wsl")
    missing = [name for name in required if contract.get(name) is not True]
    if missing:
        raise NoCfdViolation("probe-only contract missing true guard(s): " + ",".join(missing))


def assert_no_processes_started(counters: Mapping[str, int]) -> None:
    """Audit mock execution counters; any solver launch is a hard failure."""
    violations = {name: int(value) for name, value in counters.items() if int(value) != 0}
    if violations:
        raise NoCfdViolation(f"forbidden process start(s): {violations}")
