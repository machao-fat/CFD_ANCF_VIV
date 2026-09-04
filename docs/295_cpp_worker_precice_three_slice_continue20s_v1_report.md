# Stage 295：三切片 10 s -> 30 s 续算报告

## 运行结论

Stage 295 从 Stage 294 的 `global_step=2000, t=10.0 s` 续算新增 4000 步，完成至 `global_step=6000, t=30.0 s`。Gate：

`STAGE4F_D_CPP_WORKER_PRECICE_THREE_SLICE_CONTINUE20S_V1_GATE: pass`

## 审计结果

- 固定 `dt=0.005 s`，OpenFOAM 10，preCICE 3.4.1，三个 slice。
- 三个 slice 各完成 4000/4000 local steps，global barrier 连续提交。
- 源状态 `10.0 s` 未修改；目标时间目录 `30` 均生成。
- C++ worker 返回码 0 且已关闭；三个 OpenFOAM 返回码均为 0；stderr 全部为空。
- 尾部 barrier 记录 20 条；checkpoint 40 条，global step 2100, 2200, …, 6000。
- 最终 `q/qdot/qddot` 已保存且可作为续算入口；`owned_residual=0`。
- 真实进程计数：MATLAB=0，OpenFOAM=3，WSL=1，CFD=3，C++ worker=1。
- 墙钟 `2053.409092 s`（约 34.2 分钟）；runtime `71,959,491 bytes`。
- 正常 stdout 重定向丢弃，仅保留 stderr、结构化 barrier/checkpoint、最终状态和 OpenFOAM 保留的末尾场数据。

## 频率初步估计

从三个 slice 的 `10–30 s` `forces.dat` 升力序列（401 点，间隔 0.05 s）计算，线性去趋势 FFT 主峰约 `0.14963 Hz`，对应周期 `6.683 s`；自相关首个峰约 `7.4 s`。因此当前可报告的初步范围为：

`f ≈ 0.135–0.15 Hz`，`T ≈ 6.7–7.4 s`。

这 20 s 窗口只有约 2.7 个周期，且振幅仍在变化，因此该频率只能用于规划下一窗口，不能作为正式收敛频率。正式 15 周期统计仍未完成，不能据此宣称 VIV 收敛。

## 状态与后续

`FORMAL_STROUHAL_STATUS=not_completed`  
`STABLE_VIV_RESPONSE_CLAIM=not_completed`  
`LOCK_IN_CLAIM=not_completed`

Stage 295 已终止且无残留进程。继续更长窗口或正式统计需要新的明确授权、新的 run_id/case_id/runtime；不得在本 runtime 自动续跑。
