# C++ ANCF MATLAB/C++ 数值等价离线审计

- 数值 Gate：`STAGE4F_D_CPP_WORKER_NUMERICAL_EQUIVALENCE_BEFORE_CFD_V1_GATE: pass`
- MATLAB 黄金导出：step559 seed -> target step560-599，共 40 条；step、bridge step、time、tick、有限值和 payload hash 校验通过。
- 数值合同：MATLAB 与 C++ 均使用 Gauss=5、max_newton=50、dt=0.00125 s；102x102 source mass matrix 已显式传输。
- C++ 双算：工程误差合同 40/40；严格 1e-11 诊断 0/40。严格值仅用于跨实现浮点差异诊断，不改变既定工程误差合同。
- 最大误差：q=6.75016e-13，qdot=9.09495e-11，qddot=1.81899e-08，internal_force=7.27295e-05，residual=3.29558e-05。
- MATLAB worker baseline：44/44 文件 hash/size 通过，manifest SHA-256=9b6fcbf48277d07043818cad1e7c2c8cdbc37a80ec71f4c27bd7ab4c8f8331cb，可回退且只读。
- 专项测试：compileall 通过；数值 7/7；persistent IPC 15/15；confirm 44/44；根目录 unittest 1097（1096 passed、1 skipped）。
- 离线验证真实进程启动：MATLAB=0、OpenFOAM=0、WSL=0、CFD=0；C++ worker startup=1；owned residual=0。
- 本次明确授权仅用于 MATLAB 黄金导出：尝试 2 次，成功导出 1 次；没有执行 OpenFOAM、WSL、CFD 或 confirm。
- 旧证据、旧 runtime、物理参数、global dt、三 slice、阈值和正式协议未修改。

数值核心可标记为 `validated`，但总目标 `C++_WORKER_PERSISTENT_IPC_STATUS=not_completed`：真实 bounded confirm 尚未执行。phase timing/performance 在无 CFD confirm 时不可评估。下一步必须获得新的明确真实 confirm 授权后，才能创建全新的 40-step runtime；本次不自动启动。
