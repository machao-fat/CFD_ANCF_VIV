# 阶段三验收矩阵 v4

| 项目 | 证据 | 判定 |
|---|---|---|
| 频率算法修复 | 4 类 0.2 Hz 信号误差 0.158–0.241%，单元测试 6/6 | 通过 |
| Ur=5.2 后期稳态 | 60–86 与 86–112 s：RMS 0.654%、峰值 0.469%、功率 4.974%、频率 0.056% | 通过 |
| 五点 SDOF | Ur=4.0,5.2,6.0,7.1,8.0，完整终点与五周期窗口见 five_point_lockin_v4.json | 完成 |
| 五点逐点严格稳态 | `all_points_strict_steady_window_pass=False`；Ur=5.2 通过，Ur=4.0/6.0/7.1/8.0 保留未通过或锁定区外分类 | 条件通过/不宣称全点稳态 |
| 五点安全 | max |y|<1.5D、CFL<0.5 | 通过 |
| 时间步收敛 | dt/dt/2：位移 0.460%、力 0.579%、功率 1.176% | 通过（短窗） |
| 工程 restart | native/file=true，归一化力差 0.064080766% | 通过 |
| EB/ANCF 瞬态一致性 | 位移差 0.003%，功率差 0.011% | 通过（瞬态范围） |
| 网格/CFL/有限性 | Ur=5.2 网格记录 34 条全部 operational pass；无 NaN/Inf | 通过 |
| 弱耦合是否足够 | 当前完成证据无发散/added-mass 触发；能量缺陷约 1e-6 J | 暂不需要 Aitken |
| 多切片/整根立管 | 本阶段明确未做 | 不准入 |

总判定：`stage3_conditionally_passed_with_outside_lockin_point_review`。
