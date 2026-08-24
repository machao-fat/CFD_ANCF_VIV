# 阶段四进入决定 v2

决定：**暂缓进入阶段四多切片/整根立管**。

保留的可继续工作范围：

- 修复 forces function-object 在 restart 边界首两步的差异，并使 `restart_checked=true`；
- 将修正 Ur=5.2 运行延长到至少 10 个稳定周期，再重新做 dt/2 和整周期功率审计；
- 在 Ur=5.2 稳定后重新执行五点 SDOF 锁定趋势；
- 将 EB/ANCF 同工况横流运行延长到至少 2–3 个一阶周期，比较整周期相位、功率和 RMS；
- 只有在上述项目通过后，才评估弱耦合是否足够；若仍有 added-mass/残差增长，再实现带 CFD checkpoint 的固定点+Aitken。

禁止事项：

- 不得复用旧 noSlip/movingWall 不一致案例、旧 checkpoint 或旧 Ur 曲线；
- 不得把 10 s/1.55 周期结果称为稳态 VIV 锁定；
- 不得把单切片闭环称为整根柔性立管验证；
- 不得在当前 restart 和时间步判据未通过时开始多切片。
