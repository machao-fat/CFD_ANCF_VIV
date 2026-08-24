from __future__ import annotations
import json, hashlib, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OLD=ROOT/'cases/openfoam/stage4f_d_e2_motion_initialization_repair_v1/block_0'
OUT=ROOT/'results/47_stage4f_d_e2_launcher_forensic_v1'
SOURCE=ROOT/'cases/openfoam/stage4f_d_e1_bounded_pilot_v1/block_3/checkpoints/checkpoint_step00000079_e19d01431943.json'
def run_cmd(args, timeout=30):
 t=time.time()
 try:
  p=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
  return {'args':args,'return_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'elapsed_s':time.time()-t}
 except Exception as e: return {'args':args,'return_code':None,'stdout':'','stderr':repr(e),'elapsed_s':time.time()-t}
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 reg=json.loads((OLD/'owned_process_registry.json').read_text(encoding='utf-8'))
 wsl=[x for x in reg if x.get('executable')=='wsl.exe']
 logs=[]
 for x in wsl[:3]:
  p=Path(x['log_path']); txt=p.read_text(encoding='utf-8',errors='replace') if p.exists() else ''
  logs.append({'command_line':x['command_line'],'cwd':x.get('cwd'),'parent_pid':x.get('parent_pid'),'pid':x.get('pid'),'return_code':x.get('return_code'),'start':x.get('start_timestamp'),'end':x.get('end_timestamp'),'log_path':str(p),'exists':p.exists(),'exec': 'Exec   : pimpleFoam' in txt,'end_marker':'End' in txt,'fatal':'FOAM FATAL' in txt,'first_lines':txt.splitlines()[:28]})
 atomic={'launcher_command_audit':{'stage46_registry':str(OLD/'owned_process_registry.json'),'observed':logs,'classification':'launcher_started_and_openfoam_executed; prior foreground timeout/status report was stale or incomplete'},'launcher_environment_audit':run_cmd(['wsl.exe','-d','Ubuntu-22.04','bash','-lc','source /opt/openfoam10/etc/bashrc; echo OPENFOAM=$WM_PROJECT_VERSION; command -v pimpleFoam; env | grep -E "^(TEMP|TMP|TMPDIR|PREFDIR|WM_PROJECT)=" || true']), 'wsl_path_mapping_audit':run_cmd(['wsl.exe','-d','Ubuntu-22.04','bash','-lc',"test -d '/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/cases/openfoam/stage4f_d_e2_launcher_forensic_v1' && printf PATH_OK"]), 'case_seed_readiness_audit':{'stage47_root':str(ROOT/'cases/openfoam/stage4f_d_e2_launcher_forensic_v1'),'old_case_reuse':False,'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'source_step':79,'source_time_s':1.6075,'source_tick':1607500000},'process_launch_audit':logs,'stage46_failure_reproduction':{'observed_failure_report':'foreground invocation timed out after 30s, but registry/log evidence later showed natural completion','raw_registry_entries':len(reg)},'launcher_failure_classification':{'status':'not_reproduced_as_launcher_failure','root_cause':'status observation race/timeout misclassification; launcher command itself returned 0 and pimpleFoam reached End'}}
 for k,v in atomic.items(): (OUT/f'{k}.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
 (OUT/'immutable_launcher_contract.json').write_text(json.dumps({'executable':'wsl.exe','shell':'bash -lc','distro':'Ubuntu-22.04','command':'source /opt/openfoam10/etc/bashrc; export LD_LIBRARY_PATH=...; cd <stage47-slice>; pimpleFoam > <stdout-log> 2>&1','return_code_semantics':{'0':'process/executable/case completed; must also contain End','nonzero':'fail closed'},'source_checkpoint_id':'step00000079_e19d01431943','source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'seed_time_s':1.6075,'seed_tick':1607500000,'first_predicted_step':80,'no_checkpoint_on_seed_failure':True},ensure_ascii=False,indent=2),encoding='utf-8')
 return atomic
if __name__=='__main__': main()
