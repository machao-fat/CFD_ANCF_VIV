# Stage 4E-A VIVdatashare 与端木玉方法审计

## VIVdatashare

仓库主页将内容分为实验结果和数值代码两部分。实验 README 说明公开的是受合同限制的选定原始数据，完整数据 availability after negotiation；当前公开树中实际可见的实验目录为 `Bidirectionally_sheared_flow`。数值 README 明确写明：OpenFOAM-8、MATLAB 2018、二维条带法、Euler beam、constant tension。它不是本项目的 OpenFOAM-10 + ANCF 生产实现，不能作为代码等价证据。

本次审计的公开原始文件：

| 项目 | 结果 |
|---|---|
| 文件 | `DSF_S0T1_V048_1.csv` |
| 下载大小 | 17,142,838 bytes |
| SHA-256 | `507b6aadcda9437350c5035db384e7fbbbc0ebe708a6554df851c10498c743df` |
| 采样 | 250 Hz，脚本设 `dt=0.004 s` |
| 通道 | 两组三分量力传感器、CF 9 个应变测点、IL 14 个应变测点 |
| 处理 | `main1.m`；CF/IL 模态重构；异常尖峰处理；脚本中含滤波路径 |
| 许可 | 未发现仓库 LICENSE；README 要求协商完整数据访问 |

CSV 首行存在一个编码损失的时间/元数据列名，且本次不把该列猜测为可用物理时间。原始力传感器通道保留为传感器信号，不能直接宣称是已校准的分布式水动力力。

## Duanmu dissertation

本地 Zotero PDF：

`D:\zotero\数据保存位置\storage\IVBQKJJU\细长柔性立管涡激振动数值计算软件开发与应用研究_端木玉.pdf`

PDF SHA-256：`47299c66c9fb88d8e268843f4ed4f1d88f7f6d18e252c82abc2a5a2c4256e417`；228 页。

### Chapter 6 benchmark extraction

端木玉论文将 F. J. Huera Huarte (2006) 的 Delft Delta 试验作为柔性立管标准验证。表 6-1：

| 参数 | 值 |
|---|---:|
| D | 0.028 m |
| L | 13.12 m |
| L/D | 469 |
| 浸没均匀流长度 | 5.94 m |
| EI | 29.88 N m² |
| 顶张力 | 1610 N |
| U | 0.605 m/s |
| 质量比 | 3 |
| Re | 16940 |

表 6-2 前十频率为：`1.2237, 2.4516, 3.6878, 4.9364, 6.2014, 7.4867, 8.7961, 10.133, 11.520, 12.906 Hz`。频率表在本地提取文本中没有明确写出 dry/wet 标签，因此本报告只保存其原文身份，不将其直接与本项目 ANCF dry frequency 合并。

论文采用 91 个结构节点、90 个单元、20 个流场切片；网格 I/II/III 分别为 46820/71653/98640 cells，随后选 Mesh I。论文表 6-4 给出 Mesh I `Cd_mean=1.136`、`Cl_rms=0.851`、`St=0.22`，MARIN 实验 `Cd_mean=1.16`、`Cl_rms=0.83`、`St=0.19`。这些是文献/二次审计结果，不是本项目的新 CFD 结果。

### Method boundary

端木方法基于 viv-FOAM-SJTU、OpenFOAM 和 Euler–Bernoulli/FEM 条带法；本项目使用 ANCF 几何非线性结构核心和既定 H/Hᵀ 映射。可复用的是参数组织、标准实验的物理背景和“分布式切片载荷—结构响应”验证思路，不能复用其核心代码语义或把其数值结果当作本项目证据。

机器可读审计见 `results/08_stage4e_physical_baseline/vivdatashare_audit.json` 和 `duanmu_method_audit.json`。
