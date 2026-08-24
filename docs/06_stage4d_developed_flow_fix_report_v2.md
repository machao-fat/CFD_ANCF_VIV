# Stage 4D-A-v2 developed-flow 修复报告

## 判定

本报告只覆盖 developed-flow continuation、初始化速度定义、统计审计和真实 ProcessLimiter overlap 证据。未启动100步真实三切片耦合、真实3+5 restart、长时间VIV、锁定区扫描或强耦合。

v2 bank 状态为 `blocked`，因为 Re=80 在物理时间240 s仍未满足稳定准入；Re=100 和 Re=120 已分别满足连续三个评估点的全部稳定条件。候选文件只写入 `blocked`，未宣称 Stage 4D-A 通过。

## 根因确认

旧60 s证据未被修改，三套源 force CSV 的 hash 在续算前后保持一致。用修正后的无量纲统计重新计算旧60 s尾段，升力包络仍明显增长：

| 工况 | 60 s有效周期数 | 末端包络单周期最大相对变化 | 结论 |
|---|---:|---:|---|
| Re=80 | 4 | 11.68% | 未饱和 |
| Re=100 | 5 | 38.42% | 未饱和 |
| Re=120 | 7 | 44.35% | 未饱和 |

因此旧60 s失败确认为尾流/升力包络未达到极限状态，不是单纯由5%阈值或旧 raw RMS 定义造成的假失败。

## 初始化修复

v2 fresh-case 生成器统一从同一个 `U` 参数生成：

```text
default internal U = (U, 0, 0)
inlet U            = (U, 0, 0)
perturbed region  = (U, 0.1*U, 0)
```

对应值为：

| Re | default/inlet | perturbation |
|---:|---|---|
| 80 | (0.8, 0, 0) | (0.8, 0.08, 0) |
| 100 | (1.0, 0, 0) | (1.0, 0.1, 0) |
| 120 | (1.2, 0, 0) | (1.2, 0.12, 0) |

初始化参数测试 `19/19` 通过。continuation case 不调用 `setFields`，而是复制同一 Re 源 case 的60 s最终目录，设置 `startFrom latestTime` 后继续推进。

## 自适应 continuation

三工况均从各自旧60 s最终场开始，`dt=0.0025 s`，每个续算块按当前周期估计并对齐到 dt，物理时间上限240 s。每个 v2 flow 目录包含 `continuation_lineage.json`、`force_history_merged.csv`、`convergence_history.json`、`flow_summary_v2.json` 和三类诊断图。

统计定义为：

```text
Cl = Fy / (0.5*rho*U^2*D*Lspan)
Cl_rms = sqrt(mean((Cl-mean(Cl))^2))
Cd_fluctuation_rms = sqrt(mean((Cd-mean(Cd))^2))
```

旧 raw RMS 仍作为 `legacy_*_rms_raw` 保存；`cl_chunk_rms` 使用去均值后的无量纲 Cl。频率同时用 FFT 和 upward zero-crossing 估计，并记录相对差异。

## 三工况结果

| 工况 | 终止物理时间 | 周期数 | 主频 Hz | 零交叉 Hz | St | mean Cd | Cl RMS | Cl峰峰值 | 窗口Cl RMS差异 | 峰峰值差异 | 包络最大变化 | CFL | 状态 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Re=80 | 240.0000 s | 23 | 0.108456 | 0.107773 | 0.135570 | 1.391776 | 0.036948 | 0.107331 | 9.84% | 7.18% | 1.74% | 0.16458 | blocked |
| Re=100 | 188.6725 s | 24 | 0.141760 | 0.142576 | 0.141760 | 1.334787 | 0.091068 | 0.264233 | 0.566% | 0.243% | 0.044% | 0.18723 | developed |
| Re=120 | 139.9125 s | 21 | 0.177692 | 0.176706 | 0.148077 | 1.295092 | 0.132424 | 0.376888 | 0.231% | 0.074% | 0.039% | 0.22499 | developed |

Re=80 已到240 s上限，仍失败于 Cl fluctuation RMS 5%条件和峰峰值5%条件；不得把单个 Re=80失败的 bank 标记为 developed。

所有正式 v2 solver run 均正常结束、无 NaN/Inf，CFL 小于0.8；最终字段 U、p、phi、uniform/time 完整。

## 身份与 hash

- Re80 developed-flow hash：`25f51c748c95a040723d236fe34882d9c5551b9ad62644f80d8cd6295fa35c9d`
- Re100 developed-flow hash：`1df0bca9593e550a2dbb06fae431aa017a77a8def95b70058f07d58160ee2faa`
- Re120 developed-flow hash：`4a785653b6d0c850062f334ff43209fc479c78ca38bb2a9d70c32b0da214efe5`
- v2 bank hash：`e1662351813002a71f2604c08f6399e0ec388189c24879036c0b1429a60ea613`

hash 审计对三个 v2 summary 均通过。物理 hash 输入不包含绝对路径。

