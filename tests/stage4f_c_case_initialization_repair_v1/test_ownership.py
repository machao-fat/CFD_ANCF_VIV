import tempfile
import unittest
from pathlib import Path
from src.coupling.stage4f_c_case_initialization_repair_v1.ownership import prepare_stage_parent, validate_factory_target


class OwnershipTests(unittest.TestCase):
    def test_absent_branch_is_factory_owned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'stage34'
            prepare_stage_parent(root)
            validate_factory_target(root, root / 'C')

    def test_precreated_branch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'stage34'; prepare_stage_parent(root)
            (root / 'C').mkdir()
            with self.assertRaises(FileExistsError): validate_factory_target(root, root / 'C')

    def test_file_and_escape_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'stage34'; prepare_stage_parent(root)
            (root / 'C').write_text('partial', encoding='utf-8')
            with self.assertRaises(FileExistsError): validate_factory_target(root, root / 'C')
            with self.assertRaises(ValueError): validate_factory_target(root, root.parent / 'outside')

    def test_symlink_fails_closed_when_supported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'stage34'; prepare_stage_parent(root)
            target = Path(td) / 'target'; target.mkdir()
            link = root / 'C'
            try: link.symlink_to(target, target_is_directory=True)
            except OSError: self.skipTest('symlink creation unavailable')
            with self.assertRaises(FileExistsError): validate_factory_target(root, link)
