# Stage 4E-A-v3.2 Sol 主 Agent 复核

## 结论

状态：`partially_accepted_python_correction_required`

Stage 4E-A-v3.2 的 MATLAB/ANCF 模态状态导出、质量正交性、特征残差、正式 `H` 接口调用及既有模块回归证据可接收。但离线 Gate 暂不通过，且不授权真实 OpenFOAM。进入下一步前需要完成一次不重跑 MATLAB、不运行 OpenFOAM 的 v3.2.1 修正。

## 已接收证据

- nElem=8/16 的真实 ANCF `qmode` 已导出，维数、固定自由度、质量正交性和特征残差满足要求。
- 新旧模态频率和目标简并子空间 MAC 一致。
- 已实际调用生产 `build_H_for_manifest` / `ancf_hermite_H`，刚体平移和线性轴向构型检查通过。
- 切片候选、Monte Carlo 框架及 G/L 两条双向来流路线的概念验证具有继续使用价值。
- 未启动 OpenFOAM，未覆盖 v3/v3.1 证据。

## 阻断问题

### 1. 速度量纲缩放错误

v3.2 将图像数字化的 `VELOCITY_MMPS` 直接除以 1000，得到最高约 1.365 m/s；冻结基准的最大来流速度应为 0.48 m/s。应使用固定名义归一化：

`U(s) = 0.48 * U_digitized(s) / 1365`

不能按每个不确定性样本自身最大值重新归一化。当前候选中心速度及后续 Reynolds 数会被放大约 2.84375 倍，因此切片速度、配置 hash 和不确定性结果必须重新生成。

### 2. 最终候选缺少专属正式 H 投影

现有正式 H 审计覆盖旧 5 切片、均匀 7 切片和均匀 9 切片，但没有覆盖最终推荐的 `zero_crossing_aware_7_point_sampling` 中心。必须对修正后最终 7 切片及 9 切片备选直接调用生产 H 接口。

子空间对齐应在独立致密公共网格上确定，再在候选切片中心作留出评价，避免在评价点本身拟合 Procrustes 变换。

### 3. 路线 G 不是正式 0.2.1 配置字段

正式 0.2.1 `SliceDefinition` 和 `RuntimeConfig` 不包含 `signed_U_global_mps`、`flow_sign`、`active` 等字段。当前路线 G 字典及其 SHA-256 只是候选配置，不能称为正式 `config_sha256`，也没有通过正式 checkpoint/restart 校验器。

建议保留正式 0.2.1 manifest/config 不变，把双向速度表定义为独立、不可变、可哈希的 case-generation/provenance artifact，并明确其 checkpoint 绑定仍是候选扩展，不得修改生产协议。

### 4. 全项目测试未收集 v3.2

`tests/stage4e_physical_baseline_v3_2` 缺少 `__init__.py`。专项测试能得到 11/11，但从 `tests` 根目录执行 unittest discovery 仍只有 288 项，说明新的 11 项未进入全量回归。修正后必须证明根目录 discovery 明确收集 v3.2 与 v3.2.1 测试。

## 次要问题

- 最终 JSON 的路线推荐字段存在乱码，应统一为 UTF-8。
- 不确定性分析应直接使用扰动后的严格递增深度坐标，不应先把扰动曲线重新采样回名义坐标后再插值。
- 对可能产生重复深度点的样本，应拒绝并重采样，同时报告拒绝次数。
- 路线 G 的负向来流入口/出口互换和回流边界尚未通过真实 OpenFOAM 烟测，因此只能作暂定路线。

## Gate 决定

- Stage 4E-A-v3.2 离线 Gate：`not_passed`
- MATLAB 模态导出子项：`accepted`
- 正式 H 基础设施子项：`accepted_with_final_candidate_test_missing`
- 切片方案冻结：`not_frozen`
- 路线 G：`provisional_architecture_candidate`
- 真实 CFD 入口：`not_authorized`

完成 v3.2.1 后，Sol 主 Agent 应重新核对修正后的速度、7/9 切片、正式 H 留出投影、协议兼容性和根目录测试收集，再决定离线 Gate。
