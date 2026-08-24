# 阶段二定量欠项审计

审计对象为现有阶段二报告、OpenFOAM 日志、CSV、summary.json 和网格/时间步结果；已存在且证据充分的项目不重复计算。

| 项目 | 已完成且证据充分 | 已完成但证据不足/条件通过 | 未完成或本阶段补做 |
|---|---|---|---|
| 固定圆柱扩大域 | 16,244 cells、30 s、三档网格和两档时间步已有完整结果 | `checkMesh` 保留二维非对齐边诊断，不能称无警告 | 不重复重跑 |
| pimpleFoam A=0 极限 | `linear` 对齐结果 `Cd/St` 与 icoFoam 差约 0.14%/0.04% | 升力幅值仍约 7.2% 差异，属于条件一致 | 不重复重跑 |
| 规定运动长周期 | near-shedding 125 s、去瞬态后 12 周期，功率/相位/周期统计齐全 | below-shedding 周期功和幅值变化约 40%，标记非稳态 | 不重复重跑 |
| near-shedding medium/fine | medium/fine Euler 和 medium backward 已完成，10 周期窗口 | fine 与 medium 的功率差约 7.96%，保留离散不确定性 | 不重复重跑 |
| Euler/backward | medium 两种格式已比较 | phase/功率差约 2.44%，不是完全格式无关 | 后续冻结 backward |
| 整周期相位/功率 | near-shedding 已有谐波、复解调、交叉谱和周期功 | below-shedding 不是稳态窗口 | 不重复重跑 |
| interpolatingSolidBody 多周期网格 | A/D=0.1/0.3/0.5 均完成 20 s 筛选；修复后严格 native/file 401 步和网格点等价 | 尚无严格 A/B 中途 restart 差分；旧 25000 步文件回放已续传 | 继续补做 restart 等价 |
| A/D=0.1 以外网格 | A/D=0.3、0.5 已有动网格筛选 | 仅 20 s，不能外推长期自由响应 | 不再扩大振幅，先完成连续接口 |

## 审计结论

阶段二定量欠项中，严格同初场 A/B 的主要问题已定位为动网格字典缺少标准 `FoamFile` 头，且初始种子确认缺少 `consumedFile` 开关；修复后 401 步力差已降至 `1.08e-11` 相对 RMSE。剩余实质缺口是严格 A/B restart、自由 VIV 稳定统计和结构物理比较。本阶段不重复固定圆柱、A=0、near-shedding 125 s、medium/fine 或 Euler/backward 已有计算。

阶段二已有的 `below_shedding` 非稳态结果不作为自由 VIV 锁定前基准；单自由度自由 VIV 仍须独立建立结构方程和公开基准参数。
