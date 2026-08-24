# EB/ANCF 同工况在线比较

## 已有旧证据的限制

旧高张力案例使用 `topTension=1e8 N`，EB/ANCF 位移 RMS 约 `2.8e-10/2.9e-10 m`，已接近求解器/接口数值尺度；虽然旧位移绝对差很小，力相对 RMS 仍为 `5.56%`，不能称为有物理意义的同工况验证。旧 ANCF 能量列还包含大的外部势能，不能直接拿来做结构能量平衡。

## 当前统一条件

两个 runner 共用：`L,D,dInner,nElem,nSlices,s_ref,H/H^T`、质量、EI、Rayleigh 阻尼、`T0(s)`、时间步、初始结构状态和同一 CFD 网格/初场。EB 明确为小位移/小转角线性模型；ANCF 使用 Green 应变和非线性曲率。二维 CFD 的 `Fz` 对 EB 在进入结构前投影为零，同时保留原始 Fz 审计。

## 待补物理比较

需要先降低刚度或提高载荷使响应显著大于接口数值容差，再分别独立运行在线 CFD，不能把一套 CFD 载荷离线转给另一分支。比较项目包括 `y/v` RMS、峰值、主频、相位、Fx/Fy、周期平均功率、储能、阻尼耗散、Newton 残差、张力和计算成本。目标是高张力小变形下关键量差异约小于 5%；若超限，按边界、T0、阻尼、坐标、时间步、H 顺序和 predictor/corrector 顺序逐项排查。

## 当前判断

为获得明显响应，额外尝试了两分支共同 `topTension=1e6 N`、`E=2.07e8 Pa` 的诊断参数。EB 在 `t=0.015 s` 即出现 CFL `7.75`、力达 `O(1e7 N)` 并触发 pimpleFoam SIGFPE；依据停止条件未启动对应 ANCF，不把该试验当作物理结果。

EB/ANCF 物理在线比较：未通过。基础 runner/接口和新张力/残差字段通过，旧近零响应比较不具物理判别力；降低刚度的可见响应尝试又暴露出网格/弱耦合稳定性问题，因此不得进入低张力/大变形结论。
## Latest online comparison result (2026-08-04)

The same-mesh, same-time-grid 100-step EB/ANCF online diagnostic used T0=1e6 N and E=2.07e11 Pa. Both responses remained at numerical-tolerance scale: EB y RMS=4.03e-10 m and ANCF y RMS=2.99e-10 m. Their apparent 25.8% displacement-RMS and 44.1% transverse-force-RMS differences therefore have no accepted physical meaning.

The reduced-stiffness visible-response attempt was stopped safely at t=0.015 s after CFL reached 7.75 and the force grew to O(1e7 N), followed by pimpleFoam SIGFPE. ANCF was not started for that invalid case. The result is an interface pass but a physical-amplitude comparison failure. See `results/04_eb_ancf_physical_comparison/online_comparison_100.json` and `online_comparison_status.json`.
