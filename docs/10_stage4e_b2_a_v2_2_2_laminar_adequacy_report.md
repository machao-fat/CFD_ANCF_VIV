# Stage 4E-B2-A-v2.2.2 最大 Re 二维 laminar 适用性审计

本轮仅审计 v2.2.1 的时间离散与二维 laminar 空间适用性，不进入九切片、ANCF、SST 长算或域敏感性。

## 结果

medium dt1 (`dt=0.0001 s`) 统计有效：mean Cd=1.08320684716，Cd fluctuation RMS=0.0353925434238，Cl fluctuation RMS=0.536965848514，St=0.158809537784，有效周期=32.9988，生产最大 CFL=0.116192717408。

fine dt1 使用同一 v2.2.1 final checkpoint continuation；原始历史有 65.998 个有效周期，离线固定保留 59 个完整周期，对应频率门控有效周期 59.9984。fine dt1 的正式统计窗口、三窗口稳定性、force crosscheck、checkpoint lineage 均通过；mean Cd=1.78987748205，Cd fluctuation RMS=0.245901303583，Cl fluctuation RMS=1.48535662816，St=0.212729547773，生产最大 CFL=0.284661254497。

## Gate 判定

medium dt2→dt1 的 Cd fluctuation RMS 相对变化为 7.444324%，超过 5% 时间阈值。medium→fine dt1 的 mean Cd、Cd fluctuation RMS、Cl fluctuation RMS 和 St 相对变化分别为 39.481509%、85.607013%、63.849365%、25.346742%，均未满足空间阈值。

结论：本轮完成审计，但 laminar high-Re 模型不具备进入后续网格/域/低中 Re campaign 的冻结条件；Gate 建议不通过。
