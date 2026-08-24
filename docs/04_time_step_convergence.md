# 时间步与弱耦合收敛

## 定义

至少比较 `dt=0.0025 s` 与 `dt=0.00125 s`，使用相同物理初场、相同物理终止时间、相同去瞬态规则和相同统计归一化，而不是比较相同步数。每档报告振幅、频率、Fx/Fy、相位、平均功率、储能、阻尼耗散、耦合缺陷、CFL 和网格指标。

## 旧短窗证据

旧 EB dt/2 只有 `0.25 s`，并且响应接近数值噪声；粗/细短窗的峰值和功率差异很大，不能作为物理时间收敛。该证据保留为“未通过/需重算”，不再用短窗误判。

## 通过门槛

稳定窗口关键振幅/频率对 dt/2 变化目标小于约 5%；平均功率和结构能量平衡应随加密收敛。若残差或耦合缺陷随 dt 不降，先判定弱耦合/added-mass 问题，不把差异解释成 VIV 物理。

当前没有完整物理窗口 dt/2 证据，因此时间步准入未通过。
## Latest same-initial-flow result (2026-08-04)

The invalid first dt/2 run used a different developed-flow snapshot and is excluded. The valid comparison uses the same `medium_dt0p0025/30` initial U/p fields and the same physical end time of 10 s. With dt=0.0025 s versus 0.00125 s, displacement RMS changed 6.25%, transverse-force RMS changed 16.03%, and mean power changed 31.64%. Both windows contain only 0.9615 structural cycles, so this is a valid screening comparison but not time-step convergence evidence. See `results/04_time_step_convergence/sdof_ur5p2_dt_comparison.json`.
