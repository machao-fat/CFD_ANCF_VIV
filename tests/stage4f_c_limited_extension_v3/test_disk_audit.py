import unittest
from pathlib import Path
from src.coupling.stage4f_c_limited_extension_v2.disk_audit import DiskAuditError, audit_block

class Tests(unittest.TestCase):
    def test_failed_or_partial_block_rejected_before_disk_scan(self):
        base={"status":"failed","committed_steps":0,"processes":{"started":0,"closed":0,"residual":0,"nonzero_return_codes":0},"steps":[]}
        with self.assertRaises(DiskAuditError):audit_block(base,case_block_root=Path("none"),expected_start=20,expected_end=25)
    def test_process_residual_rejected(self):
        base={"status":"passed","committed_steps":0,"processes":{"started":1,"closed":0,"residual":1,"nonzero_return_codes":0},"steps":[]}
        with self.assertRaises(DiskAuditError):audit_block(base,case_block_root=Path("none"),expected_start=20,expected_end=20)
    def test_off_by_one_schedule_rejected(self):
        base={"status":"passed","committed_steps":1,"processes":{"started":1,"closed":1,"residual":0,"nonzero_return_codes":0},"steps":[{"physical_step":21}]}
        with self.assertRaises(DiskAuditError):audit_block(base,case_block_root=Path("none"),expected_start=20,expected_end=21)

if __name__ == "__main__":unittest.main()
