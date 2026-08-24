# C++ Worker Numeric Diagnostic V1

## 结论

本阶段只执行了一个独立的 MATLAB 数值诊断和离线 C++ 对照，没有启动 OpenFOAM、WSL 或 CFD。MATLAB 直接启动 1 次并正常退出，return code=0；owned residual=0。

源状态为 global step 559、time 2.2075 s，诊断范围为 560--599 共 40 步。质量矩阵、位移预测器和速度预测器逐项一致；源状态内力最大绝对差为 4.7730282e-7，切线最大绝对差为 3.7252903e-7。外力和身份字段在既有 dual-run 中 40/40 一致。

长序列的差异从 step 560 开始累积，最大值为：q 4.1084e-5、qdot 1.7808e-3、qddot 5.1177e-1、internal force 397.1143、residual 1.0060e-2。将诊断 worker 的线性求解切换为普通 double LU 后结果不变，支持“MATLAB BLAS/LAPACK 与 C++ 运算顺序/求解路径的舍入差异被时间推进放大”的分类；这不是 IPC、载荷、step/time/tick 或身份错误。

## 保护与范围

- Stage 1--96、MATLAB 常驻基线和旧 runtime 未修改、未复用。
- 生产 ANCF 物理公式、物理参数、global dt、数值阈值和正式协议未修改。
- 新增内容仅为隔离诊断脚本、诊断 executable 和诊断编译分支；默认 Release worker 路径保持原有 long-double LU。
- MathWorksServiceHost 为非 owned 进程，仅观察，未终止。

## 验证

- compileall：pass。
- CMake/MSVC Release build：pass，MSVC 14.44.35207 x64，CMake 3.31.6。
- C++ worker/persistent IPC 专项：15/15 pass。
- C++ confirm 相关离线测试：39/39 pass。
- 根目录 unittest：1085 collected，1084 passed，0 failure，0 error，1 skipped，219.674 s。

## Gate

`STAGE4F_D_CPP_WORKER_NUMERIC_DIAGNOSTIC_V1_GATE: do_not_pass`

严格双算仍未完成，因此 `C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`，不能接入真实 OpenFOAM。下一步需要新的独立双算 runtime，并在通过明确误差合同后，另行取得 WSL/OpenFOAM/CFD 的明确授权；本阶段没有推断该授权。
