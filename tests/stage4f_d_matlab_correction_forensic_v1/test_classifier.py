import unittest
from src.coupling.stage4f_d_matlab_correction_forensic_v1.classifier import *

class ForensicTests(unittest.TestCase):
    def test_nonzero_fail_closed_unknown_without_worker_evidence(self):
        self.assertEqual(classify(CorrectionEvidence(return_code=1)), FailureClass.UNKNOWN)
    def test_gui_login_cannot_replace_worker_probe(self):
        self.assertEqual(classify(CorrectionEvidence(return_code=1, worker_license=None, network_error=True)), FailureClass.UNKNOWN)
        self.assertEqual(classify(CorrectionEvidence(return_code=1, worker_license=False)), FailureClass.AUTHORIZATION)
    def test_artifact_identity_and_numerical_failures(self):
        self.assertEqual(classify(CorrectionEvidence(return_code=0, output_exists=False)), FailureClass.OUTPUT)
        self.assertEqual(classify(CorrectionEvidence(return_code=1, finite=False)), FailureClass.NUMERICAL)
        self.assertEqual(classify(CorrectionEvidence(return_code=1, identity_ok=False)), FailureClass.TRANSACTION)
    def test_timeout_and_finite(self):
        self.assertEqual(classify(CorrectionEvidence(return_code=1, timeout=True)), FailureClass.TIMEOUT)
        self.assertTrue(finite_values([0, 1.5]))
        self.assertFalse(finite_values([0, float('nan')]))

if __name__ == '__main__': unittest.main()
