# Stage100 Repair 002

本次离线修复将每个逻辑 step 明确拆为两个连续 C++ transport request：

1. prediction：使用最后 committed state 和上一 step 的 audited slice force；
2. correction：恢复同一 committed state，使用当前三 slice 已审计 force/load；
3. 只有 correction 通过后，barrier 才原子写 checkpoint 并 finalize 三个 slice。

Stage100 三 slice barrier 现在保留经过 identity/hash/ack 校验的 payload，支持 correction 读取；新增 production factory 只做 lazy 构造和授权/路径校验，不在 import 或构造阶段启动外部进程。

验证结果：

- C++ adapter/Stage100 专项：22/22 passed；
- C++ persistent IPC 专项：14/14 passed；
- 根目录 unittest：1067 collected，1066 passed，1 skipped，0 failure/error；
- compileall：pass；
- 离线 40-step mock：40/40 physical committed，40/40 fully audited，worker startup=1，slice startup=[1,1,1]，owned residual=0；
- 真实 MATLAB/OpenFOAM/WSL/CFD 启动数：0/0/0/0。

没有修改 Stage 1--96 旧证据、MATLAB baseline、ANCF/EB 核心、物理参数、global dt、slice 数量、阈值或正式 0.2.1 协议。C++ 数值核心仍保持 `C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`，因为真实生产双算/confirm 尚未完成。

真实 Gate 仍为 `STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: do_not_pass`。用户此前授权的是 Codex 可直接启动 MATLAB；这不等同于 OpenFOAM、WSL 或 CFD 启动授权。获得新的明确三者授权后，才可用全新 run/case/runtime 执行 40-step bounded confirm。
