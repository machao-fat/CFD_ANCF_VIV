from __future__ import annotations

import unittest
from pathlib import Path

from src.coupling.stage4e_probe_verified_v1.launcher import (
    EXPECTED_EXECUTABLE,
    build_formal_argv,
    build_regression_argv,
    build_regression_expression,
)


class FormalLauncherContractTests(unittest.TestCase):
    def test_regression_expression_preserves_shell_sensitive_tokens(self):
        expression = build_regression_expression()
        self.assertIn("ARGV_REGRESSION_OK", expression)
        self.assertIn("(a;b)", expression)
        self.assertIn("single quote test", expression)
        self.assertEqual(build_regression_argv()[0], str(EXPECTED_EXECUTABLE))
        self.assertEqual(build_regression_argv()[1:3], ["-wait", "-batch"])
        self.assertEqual(len(build_regression_argv()), 4)

    def test_formal_argv_is_an_array_and_uses_current_installation(self):
        argv = build_formal_argv(
            run_id="run",
            token="token",
            payload_path=Path(r"D:\formal\responses\payload.json"),
            matlab_log=Path(r"D:\formal\logs\matlab.log"),
        )
        self.assertIsInstance(argv, list)
        self.assertEqual(argv[0], str(EXPECTED_EXECUTABLE))
        self.assertEqual(argv[1:3], ["-wait", "-logfile"])
        self.assertEqual(argv[4], "-batch")
        self.assertIn("PROBE_INTERPRETER_REACHED", argv[5])
        self.assertNotIn(r"D:\Matlab\bin\matlab.exe", argv[0])

    def test_no_powershell_argumentlist_shape_is_constructed(self):
        argv = build_regression_argv()
        self.assertNotIsInstance(argv, str)
        self.assertFalse(any(item == "Start-Process" for item in argv))


if __name__ == "__main__":
    unittest.main()
