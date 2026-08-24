import json,unittest
from src.coupling.stage4f_c_stabilized_production_hook_v1.hook import FrozenLoadStabilizer
from tests.multi_slice_driver.harness import make_harness

class LineageTests(unittest.TestCase):
    def source(self):
        s,structure,processes,root=make_harness(n_slices=2)
        hook=FrozenLoadStabilizer(slice_force_scales_N={x.slice_id:500*x.slice_length_m for x in s.config.specs})
        s.stabilization_hook=hook;s.run_id='source_run'
        s.stabilizer_state={'algorithm':'first_order_load_under_relaxation','version':'1.0.0','config_sha256':hook.config_hash,'previous_applied_force_N':[[0.,0.,0.] for _ in s.config.specs],'last_step':-1,'last_time_tick':0,'iteration':1,'residual':0.}
        hook.commit(s.stabilizer_state); result=s.run_step(step=0,time_s=0.0)
        return s,root,result.checkpoint_path
    def test_normal_source_binding(self):
        s,root,path=self.source(); data=s.bind_restart_source(path,expected_run_id='source_run',expected_next_step=1,expected_next_time_s=s.config.dt_s)
        self.assertEqual(s._committed_checkpoint_path,path.resolve());self.assertEqual(data['run_id'],'source_run')
    def test_wrong_run_step_tick_and_missing_fail_closed(self):
        s,root,path=self.source()
        cases=[('run identity',dict(expected_run_id='wrong',expected_next_step=1,expected_next_time_s=s.config.dt_s)),('step',dict(expected_run_id='source_run',expected_next_step=2,expected_next_time_s=s.config.dt_s)),('tick',dict(expected_run_id='source_run',expected_next_step=1,expected_next_time_s=s.config.dt_s+1e-9))]
        for token,kwargs in cases:
            with self.assertRaisesRegex(Exception,token):s.bind_restart_source(path,**kwargs)
        with self.assertRaisesRegex(Exception,'missing'):s.bind_restart_source(root/'absent.json',expected_run_id='source_run',expected_next_step=1,expected_next_time_s=s.config.dt_s)
    def test_null_parent_after_step_zero_is_rejected(self):
        s,root,path=self.source(); second=s.run_step(step=1,time_s=s.config.dt_s);data=json.loads(second.checkpoint_path.read_text());data['parent_checkpoint_id']=None
        with self.assertRaisesRegex(Exception,'parent identity'):s.checkpoint_manager._validate_manifest(data,require_status='committed',verify_files=False)
    def test_schema_missing_field_is_rejected(self):
        s,root,path=self.source();data=json.loads(path.read_text());del data['parent_checkpoint_id']
        with self.assertRaisesRegex(Exception,'missing fields'):s.checkpoint_manager._validate_manifest(data,require_status='committed',verify_files=False)
if __name__=='__main__':unittest.main()
