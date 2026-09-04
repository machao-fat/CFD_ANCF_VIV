from __future__ import annotations


class NoSolverLaunch(RuntimeError):
    pass


def process_counts() -> dict[str, int]:
    return {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0}


def assert_no_solver_launch(counts: dict[str, int]) -> None:
    bad = {name: int(value) for name, value in counts.items() if int(value) != 0}
    if bad:
        raise NoSolverLaunch(f"forbidden solver launch: {bad}")
