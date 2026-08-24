import unittest
from src.coupling.stage4f_c_stabilized_protocol_candidate_v1.protocol import *

class TestProtocol(unittest.TestCase):
    def tx(self): return CandidateTransaction(2,(100.0,-5.0),(20.0,-1.0))
    def test_raw_force_is_preserved_and_applied_is_separate(self):
        audited=self.tx().audit(max_cd=9,velocity_error=.009,max_cfl=.2)
        prepared,applied=audited.prepare_applied()
        self.assertEqual(prepared.raw_force,(100.0,-5.0))
        self.assertEqual(applied,(28.0,-1.4))
    def test_frozen_gate_rejects_before_checkpoint(self):
        for kwargs in ({'max_cd':10.01,'velocity_error':0,'max_cfl':.1},{'max_cd':1,'velocity_error':.0101,'max_cfl':.1},{'max_cd':1,'velocity_error':0,'max_cfl':.8}):
            tx=self.tx().audit(**kwargs)
            self.assertEqual(tx.state,State.REJECTED)
            with self.assertRaises(ValueError): tx.prepare_checkpoint()
    def test_rejected_rollback_only_to_committed(self):
        tx=self.tx().audit(max_cd=11,velocity_error=0,max_cfl=.1)
        self.assertEqual(tx.rollback_target('checkpoint_parent'),'checkpoint_parent')
        with self.assertRaises(ValueError): tx.rollback_target('')
    def test_checkpoint_order(self):
        audited=self.tx().audit(max_cd=1,velocity_error=0,max_cfl=.1)
        prepared,_=audited.prepare_applied()
        self.assertEqual(prepared.prepare_checkpoint().state,State.CHECKPOINT_PREPARED)

if __name__ == '__main__': unittest.main()
