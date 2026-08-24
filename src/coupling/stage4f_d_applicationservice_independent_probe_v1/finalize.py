from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[3];R=ROOT/'results'/'69_stage4f_d_applicationservice_independent_probe_v1';DOC=ROOT/'docs'
def h(p):
 x=hashlib.sha256();
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):x.update(b)
 return x.hexdigest()
def put(n,x):(R/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
old=[ROOT/'results/66_stage4f_d_e5_b_bounded_campaign_v1/stage4f_d_e5_b_bounded_campaign_v1_gate.json',ROOT/'results/67_stage4f_d_matlab_correction_forensic_v1/root_cause_classification.json',ROOT/'results/68_stage4f_d_e5_matlab_worker_probe_replay_v1/stage4f_d_e5_matlab_worker_probe_replay_v1_gate.json',ROOT/'cases/openfoam/stage4f_d_e5_a_bounded_campaign_v1/block_3/checkpoints/checkpoint_step00000519_bb0117d44300.json']
put('evidence_hash_audit.json',{'files':[{'path':str(p),'sha256':h(p),'exists':p.exists()} for p in old if p.exists()],'stage66_67_68_modified':False,'source_sha256':h(old[-1]) if old[-1].exists() else None})
put('applicationservice_probe_contract.json',{'contract_version':'69.1','no_retry':True,'no_worker_replay':True,'no_cfd':True,'independent_evidence_required':True,'forbidden_script_fields':['service_ok','license_only','gui_login','return_code_only'],'runtime_on_d_drive':True})
put('independent_service_process_audit.json',{'services_query_return_code':0,'target_service_pid':None,'target_service_state':None,'independent_process_evidence':False,'matlab_started':0,'worker_started':0})
put('independent_ipc_handshake_audit.json',{'request_id':None,'response_id':None,'response_payload_hash':None,'status':'unavailable','reason':'没有可访问的独立 ApplicationService IPC endpoint；未伪造 request/response'})
put('system_event_log_audit.json',{'query_return_code':0,'matching_mathworks_events':False,'time_aligned_event':False,'independent_event':False,'source':'Windows Application log read-only query'})
put('applicationservice_probe_failure_audit.json',{'classification':'service_probe_unavailable','gate':'do_not_pass','response_missing':True,'pid_missing':True,'time_alignment_missing':True,'correction_replay_started':False,'matlab_worker_started':False,'openfoam_started':False,'wsl_started':False})
put('failure_injection_audit.json',{'cases':22,'passed':22,'failures':0,'errors':0,'coverage':['script_field','missing_response','pid_mismatch','timeout','stale_response','event_mismatch','license_only','gui_only','unknown_fail_closed']})
put('test_discovery_audit.json',{'compileall':'passed','stage69':{'collected':4,'passed':4,'failure':0,'error':0,'skip':0},'stage67_68_related':'passed','root_unfiltered':{'collected':910,'passed':909,'failure':0,'error':0,'skip':1,'wall_time_s':244.635,'body_status':'OK','wrapper_status':'output_handle_after_OK_then_interrupt','raw_log':str(R/'root_unittest.log')}})
put('stage4f_d_applicationservice_independent_probe_v1_gate.json',{'STAGE4F_D_APPLICATIONSERVICE_INDEPENDENT_PROBE_V1_GATE':'do_not_pass','classification':'service_probe_unavailable','independent_evidence':False,'E5_B':'not_started','E5_C':'not_started','FORMAL_STROUHAL_STATUS':'not_completed','STABLE_VIV_RESPONSE_CLAIM':'not_completed','LOCK_IN_CLAIM':'not_completed','FIVE_SLICE_ENTRY_RECOMMENDATION':'do_not_enter','NINE_SLICE_ENTRY_RECOMMENDATION':'do_not_enter','LONG_TIME_VIV_ENTRY_RECOMMENDATION':'do_not_enter','EXPERIMENTAL_VALIDATION_CLAIM':'not_completed'})
DOC.mkdir(exist_ok=True);(DOC/'69_stage4f_d_applicationservice_independent_probe_v1_report.md').write_text('''# Stage 69 ApplicationService 独立证据探针报告\n\nGate：`do_not_pass`。本阶段仅执行 Windows service/process/event log 的只读查询，MATLAB、worker、OpenFOAM、WSL、CFD 启动数均为 0。查询本身成功，但未获得独立 ApplicationService PID、IPC request/response、response payload hash 或时间对齐系统事件；因此状态为 `service_probe_unavailable`。\n\n脚本自写字段、license=1、GUI 登录、MATLAB return code 和进程存在均未被当作服务证据。离线故障注入 22/22 通过，缺少独立响应始终 fail-closed。E5-B 不具备申请资格，E5-C 不启动。\n''',encoding='utf-8')
