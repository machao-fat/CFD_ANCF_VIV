from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coupling.multi_slice_driver.real_process import atomic_text, set_ephemeral_bridge_roots
from coupling.multi_slice_mapping.mapping import atomic_write_json, set_ephemeral_atomic_roots


class EphemeralExchangeIOTests(unittest.TestCase):
    def test_mapping_fast_mode_keeps_atomic_bytes_but_skips_fsync(self):
        with tempfile.TemporaryDirectory(dir="D:/研二文件/开题准备/CFD_ANCF_VIV/runtime") as temp:
            root = Path(temp)
            exchange = root / "exchange"
            target = exchange / "ready.json"
            previous = set_ephemeral_atomic_roots((exchange,))
            try:
                with patch("os.fsync") as sync:
                    atomic_write_json(target, {"step": 560, "time_s": 2.20875})
                    sync.assert_not_called()
                self.assertEqual(target.read_text(encoding="utf-8"), '{"step":560,"time_s":2.20875}\n')
                checkpoint = root / "checkpoints" / "manifest.json"
                with patch("os.fsync") as sync:
                    atomic_write_json(checkpoint, {"committed": True})
                    sync.assert_called_once()
            finally:
                set_ephemeral_atomic_roots(previous)

    def test_bridge_fast_mode_keeps_atomic_bytes_but_skips_fsync(self):
        with tempfile.TemporaryDirectory(dir="D:/研二文件/开题准备/CFD_ANCF_VIV/runtime") as temp:
            root = Path(temp)
            case = root / "cases" / "slice_0000"
            previous = set_ephemeral_bridge_roots((case,))
            try:
                with patch("os.fsync") as sync:
                    atomic_text(case / "coupling" / "motion_ready", "ready\n")
                    sync.assert_not_called()
                self.assertEqual((case / "coupling" / "motion_ready").read_text(encoding="utf-8"), "ready\n")
                outside = root / "checkpoint.json"
                with patch("os.fsync") as sync:
                    atomic_text(outside, "committed\n")
                    self.assertGreaterEqual(sync.call_count, 1)
            finally:
                set_ephemeral_bridge_roots(previous)


if __name__ == "__main__":
    unittest.main()
