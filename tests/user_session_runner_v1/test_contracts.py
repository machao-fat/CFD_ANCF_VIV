import unittest
from pathlib import Path
from coupling.user_session_runner_v1.core import contract_hash, make_probe_contract, validate_probe_contract
from coupling.user_session_runner_v1.core import SessionRunner

class ContractTests(unittest.TestCase):
    def test_valid_contract(self):
        c = make_probe_contract(Path('D:/project'), Path('D:/project/runtime'))
        self.assertEqual(validate_probe_contract(c, Path('D:/project')), [])
        self.assertEqual(c['contract_sha256'], contract_hash(c))

    def test_tamper_and_c_drive_rejected(self):
        c = make_probe_contract(Path('D:/project'), Path('D:/project/runtime'))
        c['run_id'] = 'tampered'
        self.assertIn('contract_hash_mismatch', validate_probe_contract(c, Path('D:/project')))
        c = make_probe_contract(Path('D:/project'), Path('D:/project/runtime'))
        c['TEMP'] = 'C:/temp'; c['contract_sha256'] = contract_hash(c)
        self.assertIn('TEMP_must_be_on_D', validate_probe_contract(c, Path('D:/project')))

    def test_safety_flags_and_session(self):
        c = make_probe_contract(Path('D:/project'), Path('D:/project/runtime'))
        c['no_cfd'] = False; c['contract_sha256'] = contract_hash(c)
        self.assertIn('no_cfd_must_be_true', validate_probe_contract(c, Path('D:/project')))
        c = make_probe_contract(Path('D:/project'), Path('D:/project/runtime'))
        c['expected_session_id'] = 2; c['contract_sha256'] = contract_hash(c)
        self.assertIn('expected_session_id_must_be_1', validate_probe_contract(c, Path('D:/project')))

    def test_license_output_with_whitespace_is_validated_by_probe_parser(self):
        self.assertTrue(any(line.strip() == '1' for line in '2021b\nwin64\n     1\n'.splitlines()))

if __name__ == '__main__':
    unittest.main()
