import unittest
from src.coupling.stage4f_c_stabilized_adapter_probe_v1.interface_preflight import *

class TestInterfacePreflight(unittest.TestCase):
    def test_authorized_production_interface_is_attachable(self):
        result=audit_interfaces()
        self.assertTrue(result['passed'])
        self.assertEqual(result['scheduler_missing_hooks'],[])
        self.assertEqual(result['checkpoint_missing_fields'],[])
        require_probe_ready()
    def test_existing_transaction_order_is_identified(self):
        result=audit_interfaces(); self.assertTrue(result['existing_order_valid'])

if __name__=='__main__': unittest.main()
