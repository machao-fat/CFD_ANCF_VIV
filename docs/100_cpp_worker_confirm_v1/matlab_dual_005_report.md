# MATLAB/C++ Dual Run 005

本次只执行 MATLAB/C++ 数值双算，未启动 OpenFOAM、WSL 或 CFD。

- source：confirm_025 的只读 `committed.mat`，SHA-256 为 `C52A52C975353C552F81B02686972BEDB71A38B59C647A5707258716AD786766`；
- MATLAB：R2021b/win64，return code=0，启动 1 次，owned cleanup 完成；
- C++ worker：启动 1 次，40 个连续 step，return code=0，owned residual=0；
- 40/40 engineering-tolerance steps 通过；
- strict `1e-11/1e-9` 诊断为 0/40，不能宣称 bitwise 或严格逐位等价；
- 最大误差：q `6.7813e-05`，qdot `2.7367e-03`，qddot `4.6496e-01`，internal force `432.72`，residual `1.1792e-02`；
- external/generalized force 误差约 `3.64e-12`。

因此双算结果是 `pass_with_engineering_tolerance`，而不是完整数值核心完成。`C++_ANCF_NUMERICAL_CORE_STATUS` 继续保持 `not_completed`，这不会解除真实 CFD 的保护条件。

证据见同目录的 `matlab_process_audit.json`、`matlab_cpp_dual_run_40_audit.json` 和 `dual_run_gate.json`。真实 C++ bounded confirm 仍需新的明确 OpenFOAM、WSL、CFD 授权。
