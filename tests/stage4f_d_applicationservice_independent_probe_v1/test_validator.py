import unittest
from src.coupling.stage4f_d_applicationservice_independent_probe_v1.validator import validate, classify
class T(unittest.TestCase):
 def test_script_field_rejected(self):
  self.assertFalse(validate({'service_ok':True,'request_id':'a','response_id':'a','time_aligned':True,'response_payload_hash':'x'}))
 def test_missing_response_fail_closed(self):
  self.assertEqual(classify({'license':1,'gui_login':True}), 'service_probe_unavailable')
 def test_independent_response(self):
  self.assertTrue(validate({'independent_response':True,'request_id':'a','response_id':'a','time_aligned':True,'response_payload_hash':'x'}))
 def test_mismatch_rejected(self):
  self.assertFalse(validate({'independent_response':True,'request_id':'a','response_id':'b','time_aligned':True,'response_payload_hash':'x'}))
