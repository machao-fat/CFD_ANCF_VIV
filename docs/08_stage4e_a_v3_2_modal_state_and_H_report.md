# Stage 4E-A-v3.2：真实 ANCF 模态状态与正式 H 投影

## 范围与边界

本报告只覆盖离线模态导出、旧结果交叉核对和正式多切片 H 投影。没有启动 OpenFOAM、pimpleFoam、checkMesh 或 setFields，也没有执行真实 7/9 切片 CFD。

协议保持 `0.2.1`。导出脚本位于 `src/coupling/stage4e_physical_baseline_v3_2/export_ancf_modal_state_v3_2.m`，只调用现有 `vertical_ttr_case`、`ancf_initialize`、`ancf_constraints` 和 `ancf_internal_force_tangent`，没有修改 ANCF 核心。

## 模态状态导出

VIVdatashare 结构参数为 `L=7.64 m`、`D=0.02841 m`、`dInner=0.025 m`、`mass_per_length=1.24 kg/m`、`EI=58.6 N m²`、`EA=9.4e5 N`、`top_tension=980 N`，无重力、浮力和阻尼。MATLAB 为 R2020b，导出命令返回码为 0，MATLAB 启动次数为 1。

| nElem | qmode 形状 | 节点数 | 自由度 | 最大 M 正交误差 | 最大特征残差 | 固定 DOF qmode 最大值 |
|---:|---:|---:|---:|---:|---:|---:|
| 8 | 54×12 | 9 | 54 | 1.39e-15 | 5.77e-12 | 0 |
| 16 | 102×12 | 17 | 102 | 7.67e-16 | 4.23e-11 | 0 |

每个模态按 `v/sqrt(vᵀMffv)` 质量归一化，完整 `qmode(free,:)=V`，固定自由度置零。MAT 文件保存完整矩阵；JSON 只保存审计摘要和哈希。DOF 元数据同时说明 MATLAB 的 1-based 编号和 Python 审计的 0-based 数组索引。

## 旧结果交叉核对

新导出的前 8 阶频率与只保存采样曲线的 `ancf_design_raw.json` 相对误差为 0（双精度读回下）。目标简并对的子空间 MAC 为：

| nElem | CF mode 1 对 | IL mode 2 对 | IL mode 4 对 |
|---:|---:|---:|---:|
| 8 | 0.9999999062 | 0.9999999518 | 0.9999987239 |
| 16 | 0.9999999900 | 0.9999999998 | 0.9999999990 |

简并模态以子空间而非任意单个特征向量方向比较。旧 201 点采样网格与新导出采样网格一致；新结果没有把 201 点曲线反算为斜率自由度。

## 正式 H 投影

分析器实际调用 `src.coupling.multi_slice_mapping.mapping.build_H_for_manifest`，并由其内部 `ancf_hermite_H` 生成 H。节点 DOF 顺序为 `[position_x, position_y, position_z, slope_x, slope_y, slope_z]`，使用 MAT 中真实节点位置和完整 qmode。投影时对目标简并子空间执行 SVD/Procrustes 对齐。

在 v3 优化 5 切片参考中心、均匀 7 切片中心和均匀 9 切片中心均完成了离线投影。均匀 7 中，CF mode 1、IL mode 2、IL mode 4 的 8/16 子空间 MAC 分别为 0.9999999998、0.9999999557、0.9999770105；采用试验名义 RMS 做物理缩放后，最大切片相对误差分别为 2.17e-5、2.89e-4、7.83e-3，均低于 1%。

基础性质测试中，刚体平移最大误差为 `8.67e-19`，线性轴向构型最大误差为 `8.88e-16 m`。测试明确不要求 H 所有列的行和为 1，因为斜率列包含长度量纲。

## 幅值缩放语义

质量归一化 qmode 只用于模态身份、频率和 H 投影。物理切片位移另行将目标方向形状归一化到沿程最大绝对值 1，再乘带名义滤波协议标签的试验 RMS：CF mode 1 `6.821e-3 m`、IL mode 2 `1.240e-3 m`、IL mode 4 `8.177e-4 m`。IL mode 2 仍不作为严格幅值验收指标。

## 文件

- `results/08_stage4e_physical_baseline_v3_2/ancf_modal_state_nElem8.mat`
- `results/08_stage4e_physical_baseline_v3_2/ancf_modal_state_nElem16.mat`
- `results/08_stage4e_physical_baseline_v3_2/ancf_modal_state_export_audit.json`
- `results/08_stage4e_physical_baseline_v3_2/old_new_modal_crosscheck.json`
- `results/08_stage4e_physical_baseline_v3_2/formal_H_projection_with_qmode.json`
- `results/08_stage4e_physical_baseline_v3_2/physical_slice_displacement_convergence.json`

本报告不宣称真实 7/9 切片 CFD、严格试验幅值验证或长时间 VIV 完成。
