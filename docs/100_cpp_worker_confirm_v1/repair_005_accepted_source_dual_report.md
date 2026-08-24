# Repair 005 accepted-source dual run

`STAGE4F_D_CPP_WORKER_ACCEPTED_SOURCE_DUAL_V1_REPAIR005_GATE: pass_with_engineering_tolerance`

本次使用全新的 `matlab_dual_011` runtime 和 `repair_005` results。只读源身份为 global step 559、time 2.2075 s、integer tick 2207500000、dt 0.00125 s。MATLAB R2021b 由 Codex 按用户授权启动一次，return code=0；seed、fixture 和 40-step golden 均成功写入独立目录。

C++ worker 只启动一次，通过持久 IPC 处理 40/40 个请求，40/40 在明确 engineering tolerance 内通过，worker return code=0，owned residual=0。最大误差为 q=4.1084e-05、qdot=1.7808e-03、qddot=0.5118、internal force=397.11、residual=0.01006。严格窄诊断为 0/40，因此 `C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`，不能宣称 MATLAB/C++ 正式数值等价。

验证完成：compileall、CMake Release build、C++ worker selftest、C++ confirm 专项 26/26、persistent IPC 专项 15/15、根目录 unittest 1071 passed、1 skipped、0 failure/error。

本次真实进程计数为 MATLAB=1、OpenFOAM=0、WSL=0、CFD=0。没有启动真实 CFD、Stage75、E5-B/E5-C 或后续 segment。Stage 1--96、accepted checkpoint、MATLAB baseline 和旧 runtime 未修改。OpenFOAM/WSL/CFD 的明确授权仍缺失，因此最终 bounded confirm Gate 继续为 `STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: do_not_pass`。
