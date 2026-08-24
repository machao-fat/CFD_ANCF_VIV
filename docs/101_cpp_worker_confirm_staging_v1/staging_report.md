# C++ worker bounded-confirm staging audit

`STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_STAGING_V1_GATE: do_not_pass`

本阶段只进行离线 staging 和审计，没有启动 MATLAB、OpenFOAM、WSL 或 CFD。

已完成：

- accepted source 固定为 step 559、time 2.2075 s、tick 2207500000，SHA-256 与只读 checkpoint 一致；
- MATLAB worker baseline manifest 44/44 文件、大小和 SHA-256 一致；
- 从旧 case 只读复制生成全新的三个 case，目标时间 2.2575 s、global dt 0.00125 s；
- 新 case 的 slice_id、s_ref_m、ANCF/CFD 物理配置、controlDict/dynamicMeshDict/fvSolution 和 warm-start 目录通过审计；
- 新 case 没有旧 coupling payload、postProcessing 输出、checkpoint 或 solver log；
- Release C++ worker 可执行文件存在；
- 新 runtime/results 仍为空，未启动任何外部进程。

当前阻塞：

1. 本轮只获得 MATLAB 授权，没有获得 OpenFOAM/WSL/CFD 启动授权；
2. D 盘没有可部署的 `libancfFileMotion.so`，只有源码和旧编译目录中的源码文件。该库必须在授权后、独立 build/runtime 中生成并 hash 审计，不能把源码路径冒充二进制库。

因此 staging Gate 严格为 `do_not_pass`，真实 C++ bounded confirm 尚未启动。旧 Stage 1--96 证据、accepted checkpoint、MATLAB baseline 和旧 runtime 未修改。

专项 staging 测试 29/29 通过，compileall 通过，owned residual=0，真实进程启动数 MATLAB=0、OpenFOAM=0、WSL=0、CFD=0。
