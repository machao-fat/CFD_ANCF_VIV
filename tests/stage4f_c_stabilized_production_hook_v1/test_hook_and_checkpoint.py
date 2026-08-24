import json
import copy
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from src.coupling.stage4f_c_stabilized_production_hook_v1.hook import FrozenLoadStabilizer,StabilizationGateError
from src.coupling.stage4f_c_stabilized_production_hook_v1.run_restart_probe import align_restart_identity
from tests.multi_slice_driver.harness import make_harness

class ProductionHookTests(unittest.TestCase):
    def scheduler(self):
        scheduler,structure,processes,root=make_harness(n_slices=2)
        scales={s.slice_id:500.0*s.slice_length_m for s in scheduler.config.specs}
        hook=FrozenLoadStabilizer(slice_force_scales_N=scales)
        scheduler.stabilization_hook=hook; scheduler.run_id='stage17_test'
        scheduler.stabilizer_state={'algorithm':'first_order_load_under_relaxation','version':'1.0.0','config_sha256':hook.config_hash,
            'previous_applied_force_N':[[0.0,0.0,0.0] for _ in scheduler.config.specs],
            'last_step':-1,'last_time_tick':0,'iteration':1,'residual':0.0}
        return scheduler,structure,processes,root,hook
    def test_extended_checkpoint_binds_raw_applied_state_and_tick(self):
        scheduler,structure,processes,root,hook=self.scheduler(); result=scheduler.run_step(step=0,time_s=0.0)
        manifest=json.loads(result.checkpoint_path.read_text(encoding='utf-8'))
        self.assertEqual(manifest['schema_version'],'0.2.1+stabilizer.1'); self.assertEqual(manifest['transaction_state'],'committed')
        self.assertIn('raw_slice_forces_N',manifest); self.assertIn('applied_slice_forces_N',manifest); self.assertEqual(manifest['time_tick'],0)
        self.assertNotEqual(manifest['raw_slice_forces_N'],manifest['applied_slice_forces_N'])
    def test_feature_disabled_is_legacy_schema(self):
        scheduler,structure,processes,root=make_harness(n_slices=2); result=scheduler.run_step(step=0,time_s=0.0)
        manifest=json.loads(result.checkpoint_path.read_text(encoding='utf-8')); self.assertEqual(manifest['schema_version'],'0.2.1')
        self.assertNotIn('raw_slice_forces_N',manifest)
    def test_duplicate_consumption_fails_without_commit(self):
        scheduler,structure,processes,root,hook=self.scheduler(); scheduler.run_step(step=0,time_s=0.0)
        scheduler.last_committed_step=-1; scheduler.state=type(scheduler.state).INITIALIZED
        with self.assertRaisesRegex(Exception,'duplicate'): scheduler.run_step(step=0,time_s=0.0)
        self.assertEqual(len(list((root/'checkpoints').glob('checkpoint_*.json'))),1)
    def test_raw_cd_gate_fail_closed(self):
        scheduler,structure,processes,root,hook=self.scheduler(); hook.scales={k:1e-12 for k in hook.scales}
        with self.assertRaisesRegex(Exception,'raw Cd'): scheduler.run_step(step=0,time_s=0.0)
        self.assertFalse(list((root/'checkpoints').glob('checkpoint_*.json')))
    def test_extended_missing_field_and_unknown_schema_rejected(self):
        scheduler,structure,processes,root,hook=self.scheduler(); result=scheduler.run_step(step=0,time_s=0.0)
        manifest=json.loads(result.checkpoint_path.read_text(encoding='utf-8'))
        missing=copy.deepcopy(manifest); del missing['stabilizer_state']
        with self.assertRaisesRegex(Exception,'missing fields'): scheduler.checkpoint_manager._validate_manifest(missing,require_status='committed',verify_files=False)
        unknown=copy.deepcopy(manifest); unknown['schema_version']='99.0'
        with self.assertRaisesRegex(Exception,'schema/status'): scheduler.checkpoint_manager._validate_manifest(unknown,require_status='committed',verify_files=False)
    def test_restart_restores_stabilizer_state(self):
        scheduler,structure,processes,root,hook=self.scheduler(); result=scheduler.run_step(step=0,time_s=0.0)
        restored=scheduler.checkpoint_manager.load_restart(result.checkpoint_path,slice_processes=scheduler.processes,structure=structure)
        self.assertEqual(restored['stabilizer_state'],scheduler.stabilizer_state)
        self.assertEqual(restored['raw_slice_forces_N'],json.loads(result.checkpoint_path.read_text(encoding='utf-8'))['raw_slice_forces_N'])
    def test_wrong_tick_rejected_before_prepare(self):
        scheduler,structure,processes,root,hook=self.scheduler()
        hook.apply(step=0,time_s=0.0,time_tick=0,case_id='case',run_id='run',raw_loads=[],previous_state={}) if False else None
        with self.assertRaisesRegex(StabilizationGateError,'tick'): hook.apply(step=0,time_s=0.01,time_tick=1,case_id='case',run_id='run',raw_loads=[],previous_state={})
    def test_restart_case_identity_is_aligned_to_extended_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            case=Path(tmp); (case/'system').mkdir(); (case/'constant').mkdir()
            (case/'system/controlDict').write_text('startFrom latestTime;\nstartTime 1.5075;\nendTime 1.51;\n',encoding='utf-8')
            (case/'constant/dynamicMeshDict').write_text('stepOffset 0;\nstartTime 1.5075;\n',encoding='utf-8')
            (case/'multi_slice_case_config.json').write_text('{}',encoding='utf-8')
            process=SimpleNamespace(case=case,current_time_s=1.5075,current_clock_step=0)
            engine=SimpleNamespace(processes=[process],dt_s=.0025)
            payload={'step':1,'time_tick':1512500000,'transaction_state':'committed'}
            align_restart_identity(engine,payload,2)
            self.assertEqual(process.current_time_s,1.5125); self.assertEqual(process.current_clock_step,2)
            self.assertIn('startTime 1.5125;', (case/'system/controlDict').read_text(encoding='utf-8'))
            self.assertIn('stepOffset 2;', (case/'constant/dynamicMeshDict').read_text(encoding='utf-8'))
            metadata=json.loads((case/'multi_slice_case_config.json').read_text(encoding='utf-8'))
            self.assertEqual(metadata['restart_time_tick'],1512500000)
            with self.assertRaisesRegex(RuntimeError,'integer tick'):
                align_restart_identity(engine,{**payload,'time_tick':1512500001},2)

if __name__=='__main__': unittest.main()
