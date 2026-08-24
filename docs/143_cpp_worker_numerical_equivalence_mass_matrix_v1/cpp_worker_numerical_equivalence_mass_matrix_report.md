# C++ ANCF MATLAB 数值等价 Gate

- Gate: `STAGE4F_D_CPP_WORKER_NUMERICAL_EQUIVALENCE_BEFORE_CFD_V1_GATE: pass`
- MATLAB 黄金：step559 seed，target step560-599，40/40 identity/payload/checkpoint 验证通过。
- MATLAB/C++ 合同：Gauss=5、max_newton=50、dt=0.00125 s；source mass_matrix 102x102 以显式状态输入传输。
- 根因修复：原 C++ 重建质量矩阵与 MATLAB accepted seed 最大相对差异约 1/6；修复后 q 最大误差 6.75016e-13，qddot 最大误差 1.81899e-08，内力最大误差 7.27295e-05。
- 既有工程误差合同：40/40 通过；1e-11 严格比较为 0/40，仅作跨 BLAS 诊断，不作为 bitwise Gate。
- 故障注入：全部 fail-closed；C++ worker startup=1；owned residual=0。
- 验证阶段 MATLAB/OpenFOAM/WSL/CFD 启动数：0；授权 MATLAB exporter 启动数：4；未启动 confirm。
- 旧证据、旧 runtime、物理参数、global dt、阈值和正式协议：未修改。

数值核心可标记为 `validated`。但最终 C++ worker + persistent IPC 目标仍为 `not_completed`，因为真实 CFD bounded confirm 尚未获得新的明确授权并执行。
