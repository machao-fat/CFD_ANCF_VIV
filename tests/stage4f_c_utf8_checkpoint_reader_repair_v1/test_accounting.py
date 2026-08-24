import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from coupling.stage4f_c_utf8_checkpoint_reader_repair_v1 import probe

class FakeEngine:
 manifest=adapter=scheduler=processes=None
 def __call__(self,step,time_s):
  p=Path(self.root)/f'checkpoint_{step}.json'; p.write_text('{}',encoding='utf-8'); return {'checkpoint':str(p)}

class AccountingTests(unittest.TestCase):
 def test_post_commit_failure_is_not_uncommitted(self):
  with tempfile.TemporaryDirectory() as d:
   e=FakeEngine(); e.root=d
   def builder(case): return e,lambda:None
   with patch.object(probe,'RESULT',Path(d)),patch.object(probe,'audit_engine',return_value={}):
    out=probe.run(engine_builder=builder,checkpoint_reader=lambda p:(_ for _ in ()).throw(UnicodeError('injected')))
   self.assertEqual(out['physical_committed_steps'],1); self.assertEqual(out['fully_audited_steps'],0); self.assertEqual(out['failed_post_commit_step'],0); self.assertEqual(out['restart_eligible_checkpoints'],[])

if __name__=='__main__': unittest.main()
