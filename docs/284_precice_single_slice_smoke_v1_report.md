# Stage 284 单切片 preCICE/OpenFOAM smoke 报告

## Gate

`STAGE4F_D_PRECICE_SINGLE_SLICE_SMOKE_V1_GATE: pass`

## 范围

本次只运行一个隔离单切片 case，固定 `deltaT=0.005 s`、coupling window `0.005 s`、8 步、终止时间 `0.04 s`。Structure participant 使用 604 个圆柱面顶点施加预设微小位移；Fluid 使用 OpenFOAM 10 `pimpleFoam` 和公开 preCICE adapter。未启动 MATLAB、ANCF worker、WSL CFD 之外的研究任务，也未修改 Stage 268 原始 case、历史证据、物理参数或数值阈值。

## 结果

- preCICE 配置检查：通过；双网格 `Structure-Mesh`/`Fluid-Mesh`，位移 consistent 映射，力 conservative 映射。
- Structure：8/8 个 time windows，时间 `0.005 ... 0.04 s`，每步读取 604 个有限力向量，正常 finalize。
- OpenFOAM：8 个时间步完成，日志包含 `Reached end ... final time 0.04` 和 `End`，stderr 为空。
- 力输出：`postProcessing/forces1/0/forces.dat` 存在且为有限数值。
- 墙钟：OpenFOAM 日志约 6 s（求解器自身 ExecutionTime 约 4.33 s）。
- 进程：OpenFOAM=1、preCICE Structure=1；MATLAB=0；结束后 owned residual=0。

## 兼容修复

对隔离的公开 adapter 增加了 OF10 兼容处理：若 `cellDisplacement` 未被 solver 注册，FSI displacement 模块创建并登记该辅助场；`preciceDict` 显式设置 `namePointDisplacement unused`、`rho` 和 `nu`。这不改变 ANCF 核心、物理参数、global dt 或正式协议语义。

## 限制与下一步

该 Gate 只证明 preCICE 生命周期、双网格映射和 OpenFOAM 10 adapter smoke 可运行，不证明 C++/MATLAB 数值等价、不证明单切片 VIV 正确性，也不授予三切片、长时间或正式统计运行资格。后续任何 ANCF 耦合运行都必须使用新的明确授权、新 `run_id/case_id/runtime`，并继续保持正式统计状态为 `not_completed`。

证据：`results/284_precice_single_slice_smoke_real_v1/stage4f_d_precice_single_slice_smoke_v1_gate.json`，运行日志和 Structure 记录位于 `runtime/284_precice_single_slice_smoke_real_v1/logs_run/`。
