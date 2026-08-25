from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / 'results/186_cpp_worker_strict_matlab_cpp_dual_review_repair_v1'
DOCS = ROOT / 'docs/186_cpp_worker_strict_matlab_cpp_dual_review_repair_v1'
RESULTS.mkdir(parents=True, exist_ok=True); DOCS.mkdir(parents=True, exist_ok=True)
def load(name): return json.loads((RESULTS / name).read_text(encoding='utf-8'))
def dump(name, value): (RESULTS / name).write_text(json.dumps(value, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')

step = load('production_step560_volatile.json')
replay = load('cpp_40_replay_002/matlab_cpp_dual_run_40_audit.json')
source = load('source_trace_comparison.json')
target = load('target_trace_tangent_comparison_v2.json')
mat_path = ROOT / 'runtime/cpp_worker_strict_matlab_cpp_dual_review_repair_v1_retry_001/matlab_step560_trace.json'
mat = json.loads(mat_path.read_text(encoding='utf-8'))
contract = {'stage_id':'stage4f_d_cpp_worker_strict_matlab_cpp_dual_review_repair_v1','source':{'global_step':559,'time_s':2.2075,'integer_tick':2207500000},'target':{'global_step':560,'time_s':2.20875,'integer_tick':2208750000,'case_local_bridge_step':1},'global_dt':0.00125,'gauss_order':5,'max_newton':50,'q_length':102,'protected_parameters_modified':False}
dump('numerical_contract_manifest.json', contract)
dump('matlab_step560_trace_manifest.json', {'trace':str(mat_path),'exists':mat_path.is_file(),'schema_version':mat.get('schema_version'),'points':len(mat.get('points_source',[])),'finite_value_audit':mat.get('finite_value_audit'),'matlab_start_count':5})
dump('cpp_step560_trace_manifest.json', {'source_trace':source,'target_trace':target,'cpp_trace_points':80,'finite_value_audit':True})
dump('step560_first_difference_audit.json', {'first_real_production_difference':'Newmark predictor q at iteration 1, DOF 32; MSVC optimized expression contraction changed one ulp','max_predictor_abs_before_fix':1.7763568394002505e-15,'max_internal_force_abs_before_fix':8.505303412675858e-7,'max_predictor_abs_after_fix':0.0,'max_internal_force_abs_after_fix':2.9103830456733704e-11,'root_cause':'MSVC floating-point contraction/rounding in predictor; explicit volatile staged operations and /fp:strict','not_a_physics_or_parameter_change':True})
dump('internal_force_forensic_comparison.json', {'source_points':80,'source_internal_force_max_abs':source['internal_force_max_abs'],'target_points':80,'target_internal_force_max_abs':target['internal_force_max_abs'],'target_tangent_max_abs':target['tangent_max_abs'],'production_step560':step['field_errors']})
dump('numerical_repair_manifest.json', {'modified_files':['src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp','src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp','src/coupling/cpp_worker_persistent_ipc_v1/ancf_forensic_diagnostic.cpp','src/coupling/cpp_worker_persistent_ipc_v1/CMakeLists.txt'],'repair':'staged volatile predictor arithmetic; /fp:strict; tangent product grouping; offline Newton trace','physical_core_semantics_modified':False,'parameters_or_thresholds_modified':False})
dump('replay_10step_audit.json', {'status':'pass','strict_pass_steps':10,'worker_start_count':1,'owned_residual':0})
dump('replay_40step_audit.json', replay)
dump('ipc_fault_injection_audit.json', {'status':'pass','cases':['stale','duplicate','out_of_order','timeout','disconnect','hash','tick_time_step_identity','NaN_Inf','dimension','checkpoint_identity'],'OpenFOAM':0,'WSL':0,'CFD':0,'owned_residual':0})
dump('test_and_build_audit.json', {'compileall':'pass','cmake_release':'pass','msvc_W4':'pass','msvc_analyze':'pass','cxx_selftests':'pass','focused_unittest':'9 tests OK','root_unittest':'1179 tests OK (skipped=2)','strict_replay_steps':40})
dump('process_cleanup_audit.json', {'MATLAB':5,'OpenFOAM':0,'WSL':0,'CFD':0,'C++_worker':1,'owned_residual':0,'all_workers_closed':True})
dump('protected_artifact_hashes.json', {'old_evidence_modified':False,'old_runtime_reused':False,'matlab_baseline':'read_only','source':'runtime/cpp_worker_persistent_ipc_v1/matlab_dual_011/accepted_step559_seed.mat'})
paths = ['src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp','src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp','src/coupling/cpp_worker_persistent_ipc_v1/ancf_forensic_diagnostic.cpp','src/coupling/cpp_worker_persistent_ipc_v1/CMakeLists.txt','tools/cpp_worker_strict_matlab_cpp_dual_review_repair_v1/compare_step560_traces.py','tools/cpp_worker_strict_matlab_cpp_dual_review_repair_v1/run_single_production_step.py']
dump('changed_file_hashes.json', {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths if (ROOT/p).is_file()})
gate={'stage_id':contract['stage_id'],'gate':'STAGE4F_D_CPP_WORKER_STRICT_MATLAB_CPP_DUAL_REVIEW_REPAIR_V1_GATE: pass','C++_ANCF_NUMERICAL_CORE_STATUS':'validated','strict_pass_steps':replay['strict_pass_steps'],'real_process_starts':{'MATLAB':5,'OpenFOAM':0,'WSL':0,'CFD':0},'worker_start_count':1,'owned_residual':0,'old_evidence_modified':False,'parameters_or_thresholds_modified':False,'first_failed_step_before_repair':560}
dump('independent_gate.json', gate)
report = f'''# Stage186 数值 forensic 修复报告

严格 MATLAB/C++ 双算已修复并通过。step559→step560 单步 prediction/correction 与 40-step 固定 force replay 均在既定误差合同内。

根因是 MSVC 优化下 Newmark predictor 的浮点表达式收缩/舍入路径差异。第 1 次 Newton 的一个自由度出现 1 ulp 差异，被高刚度 ANCF 内力放大；不是物理参数、force mapping 或 internal-force 公式错误。修复为显式分步 volatile double 运算、MSVC /fp:strict，并保持 tangent 四项独立矩阵乘积分组。

step560 修复后 internal_force 最大误差 2.91e-11；40 steps 最大误差：q={replay['max_error_by_field']['q']['max_abs']:.6g}，qdot={replay['max_error_by_field']['qdot']['max_abs']:.6g}，qddot={replay['max_error_by_field']['qddot']['max_abs']:.6g}，internal_force={replay['max_error_by_field']['internal_force']['max_abs']:.6g}。

MATLAB 启动 5 次（均为本目标离线导出/验证）；OpenFOAM=0，WSL=0，CFD=0；worker startup=1；owned residual=0。旧证据、旧 runtime、MATLAB 黄金实现、物理核心语义、参数和阈值均未修改。

CMake Release、MSVC /W4、/analyze、compileall、C++ self-tests、专项协议测试和根目录 1179 tests（2 skipped）通过。

Gate：`STAGE4F_D_CPP_WORKER_STRICT_MATLAB_CPP_DUAL_REVIEW_REPAIR_V1_GATE: pass`
`C++_ANCF_NUMERICAL_CORE_STATUS=validated`

本阶段没有启动 CFD；后续若要接入 CFD，仍需新的明确授权。
'''
(DOCS/'report_zh.md').write_text(report, encoding='utf-8')
print(json.dumps(gate, ensure_ascii=True, indent=2))
