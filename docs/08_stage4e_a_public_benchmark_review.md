# Stage 4E-A 公开柔性管 VIV 基准审查

## Scope and boundary

本报告只完成公开文献/数据源审查、参数重建和离线 ANCF 结构审计。没有启动 OpenFOAM、pimpleFoam、checkMesh、setFields，也没有修改生产 ANCF、映射、driver、checkpoint 或既有 Stage 4D 证据。正式基准、阻尼、湿模态处理和真实 CFD 入口仍由 Sol 冻结。

冻结身份复核：协议 `0.2.1`；三切片 manifest identity `d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3`；Stage 4D-B 的 machine evidence 文件 hash 为 `33f5c1145e405b3e88dc13f41181b0ab47f7a3a4511f787df955ca3e0b80ffc5`，其接受文件中记录的 developed-flow bank file hash 为 `d3d9954290d7d14810e173b7e928d2386022b9e27f0233f9652b38a25864110a`。

## Candidate survey

### Candidate 1: SJTU/VIVdatashare bidirectional shear, Umax = 0.48 m/s

来源为 Fu et al. 2025 开放预印本及其 GitHub 仓库。公开树中可直接审计的实验目录是 `VIV_Experimental_Results/Bidirectionally_sheared_flow`，包含选定原始 CSV 和 MATLAB 处理脚本。CSV `DSF_S0T1_V048_1.csv` 的下载 hash 为 `507b6aadcda9437350c5035db384e7fbbbc0ebe708a6554df851c10498c743df`，大小 17,142,838 bytes。

重建参数：`L=7.64 m`、`D=0.02841 m`、`m=1.24 kg/m`、`EI=58.6 N m²`、`EA=9.4e5 N`、`T=980 N`、`zeta=2.58%`、采样率 250 Hz、`Umax=0.48/0.77/0.99 m/s`。公开脚本包含两端力传感器 `TF1/TF2`、CF 9 个测点和 IL 14 个测点的原始通道/处理路径。

限制：README 明确说明完整数据需协商；仓库未发现显式 LICENSE；公开 CSV 的 fluid density/viscosity、温度和完整标定信息不完整；其流场是双向剪切，不是本项目三切片的同向非均匀流。因此这是“可复核公开数据候选”，不是已冻结的当前物理基准。

### Candidate 2: Chaplin / Huera Huarte Delft Delta stepped-current riser

端木玉论文第 6 章表 6-1 给出：`D=0.028 m`、`L=13.12 m`、`L/D=469`、均匀流浸没长度 `5.94 m`、`EI=29.88 N m²`、`T=1610 N`、`U=0.605 m/s`、`m*=3`、`Re=16940`。表 6-2 给出前十个频率 `[1.2237, 2.4516, 3.6878, 4.9364, 6.2014, 7.4867, 8.7961, 10.133, 11.520, 12.906] Hz`。

该候选与顶张柔性立管和阶梯/非均匀流拓扑最接近，且可从论文/论文仓储追踪参数和图表。但本次审计没有取得原始位移、应变和力时间序列，表 6-2 的干/湿频率身份也未被局部文本明确标注；`EA`、单位长度质量和阻尼不完整。因此暂定为高价值 fallback，而不是冻结 primary。

### Candidate 3: Trim et al. 2005 Trondheim/NDP high-mode riser

公开论文记录了约 `38 m`、`L/D≈1400` 的长立管，测试覆盖均匀和线性剪切流，341 个 runs、拖速约 `0.3–2.4 m/s`，目标 CF 模态约 2–14。相关参数资料还给出外/内径约 `0.027/0.024 m`、单位长度质量约 `0.76 kg/m`、`EI≈37.2 N m²`、顶张力约 `3700 N`。它是高模态 benchmark，但原始时程、阻尼和全部标定元数据未在本次公开审查中定位，且与当前 Re=80–120 工况差异很大。

### Candidate 4: Song et al. 2011 Dalian uniform-flow riser

公开摘要给出 `L=28.04 m`、`D=16 mm`、`L/D≈1750`、拖速 `0.18–0.60 m/s`、`Re≈3000–10000`、端张力 `600/700/800 N`，采用 FBG 测量 CF/IL 应变，CF 最高约 6 阶、IL 最高约 12 阶，响应 Strouhal 数约 0.18。它适合高长细比均匀流对照，但原始时程和完整结构参数未取得，且为水平拖曳与当前竖直 TTR 不同。

## Candidate status

Luna 的候选推荐为：

- primary candidate（未冻结）：`vivdatashare_bidirectional_shear_v048`，理由是存在公开原始 CSV 和处理脚本；
- fallback candidate（未冻结）：`chaplin_huera_delft_delta_stepped_current`，理由是拓扑与顶张柔性立管最接近。

这两个状态都不是 Sol 的正式冻结。若 Sol 要求“完整、可合法再分发、与同向非均匀三切片完全同构”的实验数据，则本次审查结论是 `primary benchmark未冻结`，需要数据授权或改用文献图表级验证。

## Source traceability

- VIVdatashare: https://github.com/xuepengfu/VIVdatashare
- Fu et al. 2025 preprint: https://arxiv.org/abs/2502.05748
- Chaplin et al. 2005 repository record: https://ora.ox.ac.uk/objects/uuid:d451bda3-8d21-4e16-b0e7-0e0593a603cf
- Trim et al. 2005: https://www.sciencedirect.com/science/article/pii/S0889974605001325
- Song et al. 2011: https://www.sciencedirect.com/science/article/pii/S0029801811001107

机器可读矩阵见 `results/08_stage4e_physical_baseline/benchmark_candidate_matrix.json`，源文件和 hash 见 `source_inventory.json`。
