from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "references/public_precice/openfoam-adapter/Adapter.C"


class AdapterReadPathTests(unittest.TestCase):
    def test_explicit_advance_reads_displacement_before_next_step(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        advance = source.index("    // Advance preCICE\n")
        checkpoint = source.index("    // Read checkpoint if required\n")
        block = source[advance:checkpoint]
        self.assertIn("advance();", block)
        self.assertIn("if (isCouplingOngoing())", block)
        self.assertIn("readCouplingData(0.0);", block)

    def test_terminal_step_is_guarded(self) -> None:
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertLess(source.index("if (isCouplingOngoing())"), source.index("readCouplingData(0.0);"))


if __name__ == "__main__":
    unittest.main()
