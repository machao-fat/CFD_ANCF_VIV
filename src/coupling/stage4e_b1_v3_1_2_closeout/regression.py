from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Iterable


def flatten(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    tests: list[unittest.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            tests.extend(flatten(item))
        else:
            tests.append(item)
    return tests


def discover(project_root: str | Path, *, exclude_id_prefixes: Iterable[str] = ()) -> tuple[list[unittest.TestCase], list[str]]:
    root = Path(project_root).resolve()
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test*.py", top_level_dir=str(root))
    all_tests = flatten(suite)
    prefixes = tuple(exclude_id_prefixes)
    selected = [test for test in all_tests if not test.id().startswith(prefixes)]
    return selected, [test.id() for test in all_tests]


class RecordingTextResult(unittest.TextTestResult):
    pass


def run_non_matlab_regression(project_root: str | Path) -> dict:
    selected, all_ids = discover(project_root, exclude_id_prefixes=("tests.persistent_ancf.test_persistent_ancf_protocol",))
    suite = unittest.TestSuite(selected)
    stream = __import__("sys").stdout
    runner = unittest.TextTestRunner(stream=stream, verbosity=1, resultclass=RecordingTextResult)
    result = runner.run(suite)
    return {
        "schema_version": "stage4e-b1-v3.1.2-non-matlab-regression-1.0.0",
        "status": "passed" if result.wasSuccessful() else "failed",
        "tests_collected_root": len(all_ids),
        "tests_run": result.testsRun,
        "excluded_real_matlab_test_count": len(all_ids) - len(selected),
        "excluded_prefixes": ["tests.persistent_ancf.test_persistent_ancf_protocol"],
        "test_module_names": sorted({test.rsplit(".", 1)[0] for test in all_ids}),
        "failures": [{"test": test.id(), "traceback": traceback} for test, traceback in result.failures],
        "errors": [{"test": test.id(), "traceback": traceback} for test, traceback in result.errors],
        "unexpected_successes": [test.id() for test in getattr(result, "unexpectedSuccesses", [])],
    }


def write_json(path: str | Path, value: object) -> None:
    Path(path).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")

