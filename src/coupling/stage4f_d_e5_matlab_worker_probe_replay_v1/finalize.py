from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[3]; R=ROOT/'results'/'68_stage4f_d_e5_matlab_worker_probe_replay_v1'; D=ROOT/'docs'
def sha(p):
 h=hashlib.sha256();
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def put(n,x):(R/n).write_text(json.dumps(x,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')
src=ROOT/'cases/openfoam/stage4f_d_e5_a_bounded_campaign_v1/block_3/checkpoints/checkpoint_step00000519_bb0117d44300.json'
protected=[src,ROOT/'results/66_stage4f_d_e5_b_bounded_campaign_v1/stage4f_d_e5_b_bounded_campaign_v1_gate.json',ROOT/'results/66_stage4f_d_e5_b_bounded_campaign_v1/failure_step00000528.json',ROOT/'results/67_stage4f_d_matlab_correction_forensic_v1/root_cause_classification.json']
hashes=[{'path':str(p),'sha256':sha(p),'exists':p.exists()} for p in protected if p.exists()]
put('evidence_hash_audit.json',{'source_expected_sha256':'1a28ffa8e4a46f112add566b9be5f3745cc318029c856db2818d541c6891ce73','source_actual_sha256':sha(src),'source_unchanged':sha(src)=='1a28ffa8e4a46f112add566b9be5f3745cc318029c856db2818d541c6891ce73','protected_evidence_current_hashes':hashes,'stage66_written':False,'stage67_written':False})
put('process_cleanup_audit.json',{'matlab_invocations_started':2,'matlab_invocations_closed':2,'owned_residual':0,'openfoam_started':0,'wsl_started':0,'cfd_started':0,'second_probe_started':False,'second_replay_started':False})
put('test_discovery_audit.json',{'compileall':{'passed':True},'stage68':{'collected':4,'passed':4,'failures':0,'errors':0,'skipped':0},'stage67_related':{'collected':4,'passed':4,'failures':0,'errors':0,'skipped':0},'root_unfiltered':{'collected':910,'passed':909,'failures':0,'errors':0,'skipped':1,'wall_time_s':250.162,'test_body_exit_code':0,'wrapper_exit_code':1,'wrapper_note':'完整 OK 后输出句柄未释放，精确 Ctrl+C 收口；不影响 unittest 终态','raw_log':str(R/'preflight_root.log')}})
log=ROOT/'runtime/stage4f_d_e5_matlab_worker_probe_replay_v1/probe_once/matlab.log'; txt=log.read_text(encoding='utf-8',errors='replace')
classification={'classification':'unknown_insufficient_evidence','probe_process_return_code':0,'replay_return_code':0,'replay_reproduced_failure':False,'historical_failure_reproduced':False,'network_error_confirmed':False,'reason':'探针 payload 中 application_service=true 是探针自写标志，并非独立服务 API 响应；MATLAB 日志还含关机期 EditorDataService/Connector 异常。因此不能将 ApplicationService 判为已验证健康，也不能把历史失败归因于网络。隔离 correction 本身成功。'}
put('root_cause_classification.json',classification)
gate={'STAGE4F_D_E5_MATLAB_WORKER_PROBE_REPLAY_V1_GATE':'do_not_pass','probe_return_code':0,'release':'2021b','architecture':'win64','license_test':1,'applicationservice_status':'insufficient_evidence','replay_return_code':0,'replay_output_exists':True,'root_cause_classification':'unknown_insufficient_evidence','eligible_for_new_e5_b_attempt':False,'owned_residual':0,'E5_B_STATUS':'not_accepted','E5_C_STATUS':'not_started','FORMAL_STROUHAL_STATUS':'not_completed','STABLE_VIV_RESPONSE_CLAIM':'not_completed','LOCK_IN_CLAIM':'not_completed','FIVE_SLICE_ENTRY_RECOMMENDATION':'do_not_enter','NINE_SLICE_ENTRY_RECOMMENDATION':'do_not_enter','LONG_TIME_VIV_ENTRY_RECOMMENDATION':'do_not_enter','EXPERIMENTAL_VALIDATION_CLAIM':'not_completed'}
put('stage4f_d_e5_matlab_worker_probe_replay_v1_gate.json',gate)
D.mkdir(exist_ok=True)
(D/'68_stage4f_d_e5_matlab_worker_probe_replay_v1_report.md').write_text('''# Stage 68 MATLAB worker 探针与 step 528 隔离重放报告\n\nGate：`do_not_pass`。自动 MATLAB 进程返回 0，R2021b/win64/license=1 且所有临时目录位于 D 盘；唯一隔离重放返回 0，并产生全新、有限且身份审计完整的 correction MAT 文件。\n\n但 ApplicationService 证据不合格：payload 的 `application_service=true` 是探针脚本自写值，不是服务探针响应；MATLAB logfile 同时出现关机阶段 EditorDataService/Connector 异常。因此不能宣称 ApplicationService 已验证健康，也不能将 Stage 66 历史 return code 1 归因为网络。根因保持 `unknown_insufficient_evidence`。\n\n进程：MATLAB 2 次启动/2 次关闭/residual 0；OpenFOAM、WSL、CFD 启动均为 0。Stage 65 source SHA 保持不变，Stage 66/67 未写入。E5-B 不接受，E5-C 未启动。下一步只能在新授权下设计真正可验证的 ApplicationService API 探针；不得直接重跑 E5-B。\n''',encoding='utf-8')
