# Stage 4D-B Restart 与耦合功审计报告

## 范围

本文件只报告 Stage 4D-B 的 100 步工程稳定性、原子 checkpoint 和 5+5 restart 对照。它不作锁定区、稳定振幅或长期 VIV 统计结论。协议为 `0.2.1`，冻结 manifest hash 为 `d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3`。

## 耦合功

正式 run 为 `stage4d_b_formal100_20260811T044351Z_7e8682bdbf`。每步使用发送给 CFD 的预测切片中心速度和校正后通过相同 H 插值得到的切片中心速度；力已经是积分力，没有再次乘切片长度。

审计结果：

- `W_CFD` 和 `W_structure` 各 100 项，单位 J；逐步 `delta_W` 已写入 `stage4d_b_energy_audit.json`；
- `sum(delta_W) = -0.0003265586261691226 J`；
- 分子 `abs(sum(delta_W)) = 0.0003265586261691226 J`；
- 分母 `sum(abs(W_CFD)) = 3.2963482091793406 J`；
- `E_c = 9.906678707660641e-05`；
- 状态为 `evaluable`，满足建议阈值 `E_c <= 0.10`，且分母不属于低功不可评价情形。

能量原始数组、预测/校正速度、每步三切片积分力和累计量位于：

`D:\研二文件\开题准备\CFD_ANCF_VIV\results\06_stage4d_medium_run\stage4d_b_energy_audit.json`

## 5+5 restart

restart run 为 `stage4d_b_restart_20260811T045710Z_6603883e16`：

1. phase1 新鲜运行 step 0–4，5 步、15 个切片进程，worker PID `37536`、start count 1；
2. 从 phase1 的正式 committed checkpoint
   `phase1/checkpoints/checkpoint_step00000004_2ed1bffd58a7.json` 恢复；
3. phase1 worker 关闭后启动新的 phase2 worker，PID `29028`、start count 1，运行 step 5–9，5 步、15 个切片进程；
4. phase2 仅从 step 4 manifest 引用的字段和原生 ANCF checkpoint 恢复，没有从最新残留文件、CSV 或残留 exchange 近似重建结构状态。

step 0–9 的逐步比较结果全部通过：

- time absolute error 为 0；
- q、qdot、qddot 相对误差为 0；
- 三切片积分力相对误差为 0；
- `U`、`p`、`phi`、`Uf`、`meshPhi`、`uniform/time`、`polyMesh/points` 和 `motionScale` 的文件 hash 全部一致；
- manifest/config/physics hash 全部一致；
- 事务状态全部为 committed，切片顺序、坐标和时间无跳跃或回退；
- restart 两个 phase 的 ProcessLimiter 均为上限 2、峰值 2、无 permit 泄漏，日志正常结束。

结果文件为：

`D:\研二文件\开题准备\CFD_ANCF_VIV\results\06_stage4d_medium_run\stage4d_b_restart_comparison.json`

## 证据与复核边界

两步预检和正式运行均为真实 OpenFOAM 10 `pimpleFoam` 进程，并由现有 `PersistentANCFRunner` / `PersistentProductionANCFAdapter` 驱动。主 run 的 MATLAB worker 启动次数为 1；restart 阶段各自允许启动新的单 worker，并分别记录生命周期。Sol 主Agent仍需重新计算共享工作区 hash、抽查 OpenFOAM 日志与 checkpoint 引用，并重跑测试后决定正式 Gate。

