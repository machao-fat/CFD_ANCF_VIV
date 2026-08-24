"""Run the project unittest suite while excluding real persistent ANCF tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


def collect_non_matlab_tests(project_root: Path) -> tuple[unittest.TestSuite, list[str]]:
    # Match the repository's normal discover contract exactly: only
    # test*.py files are imported.  Some historical directories contain
    # helper scripts which are intentionally not importable as test modules.
    discovered = unittest.TestLoader().discover(str(project_root / "tests"), pattern="test*.py")
    flat: list[unittest.case.TestCase] = []

    def flatten(item: unittest.TestSuite | unittest.case.TestCase) -> None:
        if isinstance(item, unittest.TestSuite):
            for child in item:
                flatten(child)
        else:
            flat.append(item)

    flatten(discovered)
    selected = unittest.TestSuite(
        test for test in flat if not test.id().startswith("persistent_ancf.") and ".persistent_ancf." not in test.id()
    )
    modules = sorted({test.id().rsplit(".", 2)[0] for test in selected})
    return selected, modules


def main() -> int:
    project_root = Path(__file__).resolve().parents[3]
    suite, modules = collect_non_matlab_tests(project_root)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(f"MODULES {len(modules)}")
    print(f"COLLECTED {suite.countTestCases()}")
    print(f"FAILURES {len(result.failures)} ERRORS {len(result.errors)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
