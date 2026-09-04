# Stage 297：三切片 30 s -> 70 s 长窗口续算报告

## Gate

`STAGE4F_D_CPP_WORKER_PRECICE_THREE_SLICE_CONTINUE40S_RETRY1_GATE: pass`

Stage 297 从 Stage 295 的 `global_step=6000, t=30.0 s` 续算到 `global_step=14000, t=70.0 s`，新增 8000 步（40 s）。Stage 296 的错误启动已 fail-closed 且未被复用；Stage 295 源 runtime 保持不变。

## 运行审计

- OpenFOAM 10，preCICE 3.4.1，三个 slice，固定 `dt=0.005 s`。
- 三个 slice 各完成 8000/8000 local steps；global barrier 连续提交。
- 三个 slice 均生成 `70` 时间目录；C++ worker 返回码 0 并正常关闭；三个 OpenFOAM 返回码均为 0。
- stderr 全部为空；尾部 barrier 记录 20 条；checkpoint 80 条，global step 6100, 6200, …, 14000。
- 最终 `q/qdot/qddot` 已保存且可作为下一次续算入口；`owned_residual=0`。
- 真实进程计数：MATLAB=0，OpenFOAM=3，WSL=1，CFD=3，C++ worker=1。
- 墙钟 `4089.655167 s`（约 68.2 分钟）；runtime `74,759,966 bytes`。
- 正常 solver stdout 未持久化，仅保留 stderr、结构化 checkpoint/barrier、最终状态和 purgeWrite 管理的场数据。

## 频率和周期初步观察

从三个 slice 的 `30–70 s` `forces.dat` 升力序列（801 点，间隔 0.05 s）计算，完整窗口 FFT 主峰约 `0.12484 Hz`（周期 `8.01 s`）；尾部窗口主峰约 `0.0998 Hz`（周期 `10.02 s`）。因此当前只能报告初步范围：

`f ≈ 0.10–0.125 Hz`，`T ≈ 8–10 s`。

40 s 窗口约包含 4–5 个周期，说明振荡持续存在，但频率估计仍受有限窗口、启动/幅值演化影响。它不满足正式 15 周期统计收敛，也不构成锁定区或实验验证结论。

## 其他必须满足的收敛条件

周期数只是一个条件，还必须同时满足：

1. **周期统计稳定**：连续多个周期的主频、峰峰值、均值、RMS 和相位变化低于预设统计门槛；不能只看 FFT 单峰。
2. **结构响应稳定**：位移、速度、加速度、动态张力、曲率热点和模态能量不持续漂移，且无 NaN/Inf 或非物理突跳。
3. **流体数值稳定**：每个时间步的 PIMPLE/线性求解残差达到既定要求，Courant 数和质量守恒保持在原数值合同范围内。
4. **耦合接口完整**：每个 step 的三 slice 位移、CFD advance、力读取、consumed ack、tick/time/identity 校验和 global barrier 全部完成。
5. **切片一致性与守恒**：位移/载荷映射、合力、力矩和虚功传递满足原有接口审计要求；不能因某一 slice 停滞而只用其他 slice 统计。
6. **续算可重复**：checkpoint、最终 `q/qdot/qddot`、源/目标时间和 hash 完整，重启后第一步 identity 连续。
7. **资源稳定**：owned residual=0，进程正常退出，滚动存储不发生无界增长，且没有旧 runtime 或 partial artifact 混入。

## 正式状态

`FORMAL_STROUHAL_STATUS=not_completed`  
`STABLE_VIV_RESPONSE_CLAIM=not_completed`  
`LOCK_IN_CLAIM=not_completed`

70 s 结果具备三切片长窗口稳定性和续算能力证据，但不能自动升级为正式 15 周期 VIV 收敛。任何继续计算或正式统计都需要新的明确授权、新的 run_id/case_id/runtime。
