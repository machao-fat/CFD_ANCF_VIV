# Stage 4E-A-v2：VIVdatashare 数据处理与验证观测量审计

## 结论摘要

本次完成了 VIVdatashare 选定双向剪切工况 `DSF_S0T1_V048_1.csv` 的离线来源、编码、schema、时间语义、原始统计和非 redistributive 派生观测量审计。没有启动 OpenFOAM、pimpleFoam、setFields 或任何真实 CFD campaign。

选定文件的原始 SHA-256 为 `507b6aadcda9437350c5035db384e7fbbbc0ebe708a6554df851c10498c743df`。CSV 使用 GB18030 编码，共 18,000 个数据样本、56 个数据列，采样频率按仓库 `main1.m` 的 `Fs=250` Hz 解释，派生时间范围为 0–71.996 s、`dt=0.004 s`。

仓库没有包含 `bpass.m` 或其阶数/相位说明。因此本报告保存了不依赖滤波器的原始统计，并另外计算了明确标记为“诊断性”的四阶零相位 Butterworth 0.01–20 Hz 结果。诊断性曲线不能作为论文滤波结果的精确复现，也不能直接作为 CFD 验证通过证据。

## 来源与分类

- Fu et al. 2022, *Journal of Fluids and Structures* 114, 103722：主实验论文，DOI [10.1016/j.jfluidstructs.2022.103722](https://doi.org/10.1016/j.jfluidstructs.2022.103722)，作者 PDF [JFSbiflow.pdf](https://xuepengfu.github.io/assets/pdf/JFSbiflow.pdf)。
- Fu et al. 2025, *Marine Structures* 104, 103895：数值验证论文，DOI [10.1016/j.marstruc.2025.103895](https://doi.org/10.1016/j.marstruc.2025.103895)，不是主实验论文。
- [VIVdatashare repository](https://github.com/xuepengfu/VIVdatashare)：选定实验文件和数值代码的发布仓库。仓库 README 明确实验数据存在协商/许可边界，仓库中未观察到许可证文件。

论文正文将实验数据描述为 confidential；仓库说明部分实验数据可在协商后获得。两者均不等同于允许任意再分发。因此本任务只输出 hash、元数据、聚合统计和处理规则，不把原始 CSV 写入项目目录。

## Schema 与时间语义

| 项目 | 审计结果 |
|---|---:|
| 原始 CSV 编码 | GB18030 |
| 首行/语义首行列数 | 57 / 56 |
| 数据行数 | 18,000 |
| 数据列数 | 56 |
| RecordID | 2,758,587–2,776,586，严格单位递增 |
| TestID | 唯一值 80 |
| 源时间列 | 0–72，共 73 个整数值；17,927 个零差分、72 个单位差分 |
| 物理时间 | `t_n=n/250`，0–71.996 s |
| 有限性 | 全部数值字段有限 |

源时间列是量化/分段元数据，不能当作每个样本的物理时间戳。所有时程分析使用 `derived_index_time`，并保留源时间列的审计记录。

通道分组为 CF1/CF2 的 4 点和 5 点组共 9 个 CF 位置，以及 IL1/IL2 的 6 点和 8 点组共 14 个 IL 位置。该布局与论文及 `main1.m` 的 9 个 CF、14 个 IL 测点一致。

## 处理规则

按照仓库 `main1.m` 的可见部分复核：

1. CF 采用两侧通道去均值后差分的一半：`(CF1-mean(CF1) - CF2+mean(CF2))/2`。
2. IL 采用每个通道前 1000 点基线扣除。
3. 绝对值超过 2000 的点按 `x[n]=x[n-1]+x[n-1]-x[n-2]` 记录性修复，并报告修复计数。
4. 仓库代码使用 `bpass(signal,dt,0.01,20)`，但 `bpass.m` 未在公开仓库中找到，因此本次使用四阶零相位 Butterworth 仅作诊断分支。
5. 位移换算沿用可见代码的 `/1e6 * D/D1`，其中 `D=0.02841 m`、`D1=0.025 m`。
6. 力换算沿用 `main1.m`：`Fx=TF2_Fx*9.8`、`Fy=TF2_Fy*9.8`、`Fz=TF2_Fz/54.94505495*56.17977528*9.8`。

## 原始与诊断性聚合观测量

原始力统计（N）：

| 量 | 均值 | RMS | 最大绝对值 |
|---|---:|---:|---:|
| Fx | 5.3371 | 6.0925 | 15.4213 |
| Fy | -28.7029 | 28.8215 | 39.1957 |
| Fz | 986.3673 | 986.4862 | 1030.4151 |

诊断性滤波分支的代表结果为：CF 第 1 模态坐标 RMS `6.0024e-3`、峰值 `1.5042e-2`；IL 第 2 模态坐标 RMS `1.0031e-3`、峰值 `4.9111e-3`；IL 第 4 模态坐标 RMS `6.6903e-4`、峰值 `1.4393e-3`。这些量只用于检查数据链路和目标模态，不是经许可后的正式实验曲线。

诊断分支给出的频率峰值受有限记录长度和滤波器差异影响：CF mode 1 的 Welch 峰值约 1.556 Hz，IL mode 2 约 3.296 Hz，IL mode 4 约 6.622 Hz。论文的双向剪切工况目标是 CF mode 1、IL modes 2 和 4；频率峰值不能替代论文的稳定段、相位和跨测点统计分析。

## 结果与边界

可复算脚本：[audit_vivdatashare_v2.py](../src/coupling/stage4e_physical_baseline_v2/audit_vivdatashare_v2.py)。对应 JSON 产物位于 `results/08_stage4e_physical_baseline_v2`：schema、处理观测量、论文比较、来源修正和许可边界均独立保存。

本阶段状态为“离线审计完成、正式物理基准条件冻结待许可/滤波边界闭合”。不得据此宣布 VIV 物理验证、锁定区、稳定振幅或允许真实 CFD。
