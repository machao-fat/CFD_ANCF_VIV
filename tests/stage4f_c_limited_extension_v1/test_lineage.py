import copy
import unittest

from src.coupling.stage4f_c_limited_extension_v1.lineage import LineageError, validate_ledger


def record(step, parent, child, contract="c"):
    from src.coupling.stage4f_c_limited_extension_v1.lineage import _canonical
    value = {"block_id": "b", "physical_step": step, "time_s": 1.0 + step, "parent_checkpoint_absolute_path": "p", "parent_sha256": parent, "child_checkpoint_absolute_path": "q", "child_sha256": child, "contract_sha256": contract, "cfd_field_hashes_sha256": "f", "previous_slice_forces_sha256": "l", "runner_checkpoint_sha256": "r"}
    value["record_sha256"] = _canonical(value)
    return value


class LineageTests(unittest.TestCase):
    def test_contiguous_hash_chain_passes(self):
        validate_ledger([record(10, "p0", "c0"), record(11, "c0", "c1")], contract_sha256="c")

    def test_reorder_or_wrong_parent_fails(self):
        with self.assertRaises(LineageError):
            validate_ledger([record(10, "p0", "c0"), record(12, "c0", "c2")], contract_sha256="c")
        with self.assertRaises(LineageError):
            validate_ledger([record(10, "p0", "c0"), record(11, "bad", "c1")], contract_sha256="c")

    def test_tamper_or_contract_mismatch_fails(self):
        row = record(10, "p0", "c0")
        changed = copy.deepcopy(row)
        changed["child_sha256"] = "other"
        with self.assertRaises(LineageError):
            validate_ledger([changed], contract_sha256="c")
        with self.assertRaises(LineageError):
            validate_ledger([row], contract_sha256="other")

    def test_empty_ledger_fails(self):
        with self.assertRaises(LineageError):
            validate_ledger([], contract_sha256="c")

    def test_wrong_initial_parent_fails(self):
        with self.assertRaises(LineageError):
            validate_ledger([record(10, "p0", "c0")], contract_sha256="c", expected_initial_parent_sha256="wrong")


if __name__ == "__main__":
    unittest.main()
