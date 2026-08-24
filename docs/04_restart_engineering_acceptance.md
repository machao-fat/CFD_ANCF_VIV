# Restart 分层验收

restart 不再使用单一布尔量描述，分为三层：

1. 严格逐步/bitwise 等价：要求每个时间步的力、时间序列和边界/终点状态均满足严格阈值；
2. native/file 运动适配器一致性：比较 native 与 file 重启后的轨迹、力和最终场；
3. 工程 restart 一致性：按 `0.5 rho U^2 D=500 N` 归一化力差，并检查差异是否只集中在重启后的首两个样本且随后衰减。

当前结果：

- 严格逐步等价：未通过，保留 `restart_checked_strict=false`；
- native/file 适配器一致性：通过，横向力相对 RMSE `1.0787e-11`，最终 U/p/网格点差异约 `8.88e-14`、`1.0e-8`、0；
- 工程 restart：通过。最大横向力差 `0.32040383 N`，归一化为 `0.06408%`；去掉重启后前两个样本后最大差降至 `0.00024638 N`，最终 U/p/网格点差异为 `1.0e-7`、`1.96e-8`、0。

因此工程判断为：**restart 条件通过，严格逐步等价未通过**。该短暂差异不能归因于 `ancfFileMotion` 运动读取失败，也不能伪装成严格等价；后续整周期统计中应保留 restart 边界标签，不把边界重复输出混入稳态窗口。

量化文件：`results/04_restart_equivalence/restart_engineering_acceptance.json`；原始严格审计仍保留在 `restart_equivalence.json`。
