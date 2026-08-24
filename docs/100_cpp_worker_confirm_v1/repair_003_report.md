# C++ Worker Confirm Repair 003

本修复只涉及新 C++ confirm 层的预测运动转换和真实入口保护：

- prediction 明确输出同一 committed Newmark 状态派生的 `predictor_qdot`、`predictor_qddot`；
- motion builder 要求 q/qdot/qddot、step/time/tick/run/case 完整一致；
- 真实启动必须先成功 preflight；
- stop audit 使用实际 worker/slice start count；
- 旧证据、物理核心、参数、阈值和 0.2.1 语义未修改。

专项测试为 26/26，持久 IPC 专项为 14/14，根回归为 1071 collected、1070 passed、1 skipped。

本修复未启动 MATLAB、OpenFOAM、WSL 或 CFD，owned residual=0。真实 bounded confirm 仍需新的明确 OpenFOAM/WSL/CFD 授权。
