# Stage 294：C++ worker + preCICE 三切片 10 s 运行报告

## 结论

三切片 10 s 运行已实际完成，但原始 launcher Gate 为 `do_not_pass`，原因仅为 checkpoint 数量断言错误：既定策略是每 100 步保存一次，因此 2000 步应为 20 个 checkpoint（step 100 至 2000），而不是包含 step 0 的 21 个。物理推进、preCICE barrier、worker 和三个 fluid participant 均正常完成。

## 运行范围

- OpenFOAM 10；preCICE 3.4.1；固定 `dt=0.005 s`。
- 3 slices；2000/2000 global steps；最终时间 `10.0 s`。
- 一个持久 C++ ANCF worker；每个 slice 一个 OpenFOAM 进程。
- `purgeWrite=1`；保留 barrier 尾部 20 条、每 100 步 checkpoint、最终 `q/qdot/qddot`。

## 复核结果

- `committed_steps=2000`；三个 slice 计数均为 2000；global barrier 连续完成。
- checkpoint 共 20 个，步号为 100, 200, …, 2000，时间覆盖 0.5 s 至 10.0 s。
- 最终 `q/qdot/qddot` 存在且全部为有限值，可作为后续续算入口。
- C++ worker 返回码 0 且已关闭；三个 OpenFOAM fluid 均返回码 0 并输出 `End`；stderr 均为空。
- `owned_residual=0`；MATLAB=0；OpenFOAM=3；WSL=1；CFD=3。
- 本次墙钟：1120.133474 s（约 18.67 min）；runtime 约 108,177,096 bytes。

## Gate 解释

原始证据 `results/294_cpp_worker_precice_three_slice_10s_v1/stage4f_d_cpp_worker_precice_three_slice_10s_v1_gate.json` 保持不变，其 `do_not_pass` 只反映旧的 `checkpoint_count_21` 检查条件。已修正 launcher，使后续同范围运行检查 20 个 checkpoint 及 100 步间隔；未修改本次旧结果，也未在同一 runtime 重试。

本次是长窗口稳定性/续算 smoke，不是正式 15 周期 VIV 收敛证明。正式状态继续为：

`FORMAL_STROUHAL_STATUS=not_completed`  
`STABLE_VIV_RESPONSE_CLAIM=not_completed`  
`LOCK_IN_CLAIM=not_completed`

下一次更长运行或正式统计仍需新的明确授权，并必须使用新的 run_id、case_id 和 runtime。
