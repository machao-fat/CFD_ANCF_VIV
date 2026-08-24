import unittest
from src.coupling.stage4f_d_e4_campaign_orchestration_repair_v1.gate import Contract, Gate, TERMINAL

SRC='D:/source/checkpoint_step00000319.json'
def c(**kw): return Contract(run_id='stage57', source_checkpoint_path=SRC, source_checkpoint_sha256='5cf040d090d1c57a4ac73cbbd7b3c59898ba1520db9aaa1b61ffaf3218323c8b', **kw)

class RepairTests(unittest.TestCase):
    def test_four_blocks_and_terminal(self):
        g=Gate(c())
        for b in range(4):
            g.begin_block(b)
            for s in range(320+b*10,330+b*10): g.commit_step(s)
            if b<3: g.next_block()
        self.assertEqual(g.state, TERMINAL); self.assertEqual(len(g.created),40)
        with self.assertRaises(RuntimeError): g.begin_block(4)
        with self.assertRaises(RuntimeError): g.commit_step(360)
    def test_contract_mismatch_rejected(self):
        with self.assertRaises(ValueError): Gate(c(authorized_steps=41))
        with self.assertRaises(ValueError): Gate(c(first_target_step=321))
        with self.assertRaises(ValueError): Gate(c(last_target_tick=1958750000))
    def test_no_extra_artifacts_after_terminal(self):
        g=Gate(c())
        for s in range(320,360): g.commit_step(s)
        before=len(g.created)
        with self.assertRaises(RuntimeError): g.next_block()
        self.assertEqual(before,len(g.created))
    def test_source_step_and_hash_are_explicit(self):
        self.assertEqual(c().source_step,319); self.assertEqual(len(c().sha256()),64)

if __name__=='__main__': unittest.main()
