# Stage 4E-A-v3.2：双向来流协议候选决策

## 正式协议边界

正式协议保持 `0.2.1`，三切片 manifest 的 `R_GL` 仍是全局字段，`SliceDefinition` 没有逐切片旋转字段。因此本报告只创建离线候选 JSON 和 mock，不修改正式协议、生产 mapping 或 OpenFOAM 模板。

## 路线 G：0.2.1 全局带符号来流

路线 G 保持全局 `R_GL=I`，每个切片保存 `signed_U_global_mps`、`local_inflow_speed_mps=abs(U)`、`flow_sign` 和 `active`。CFD 力直接按全局坐标解释，不做额外力旋转；mock 虚功残差为 0。

该路线的工程问题是负向来流必须交换几何入口/出口角色。当前模板是否完整支持负向入口、压力出口和回流，需要后续单独反向流烟测；本阶段禁止启动 OpenFOAM，因此只记录为接口请求。配置 hash 已包含 signed U，改变负向速度时 restart identity mock 拒绝。

## 路线 L：候选 0.2.2 逐切片局部正向来流

路线 L 为候选 schema `0.2.2-candidate`：每个活动切片有 `R_GL`、`R_LG`、`signed_U_global_mps`、`local_inflow_speed_mps`、`flow_sign`、`active` 和 `inactive_reason`。正向切片使用 I；负向切片使用 `diag(-1,-1,1)`，其正交性和行列式 +1 已在 mock 中验证。运动和力分别为：

`r_local = R_LG r_global`，`F_global = R_GL F_local`。

随机向量虚功最大绝对残差为 0。inactive 切片不等待 CFD ready 且载荷严格为零；R_GL、active 或 flow_sign 改变时 restart identity 拒绝。候选 JSON 保存 canonical hash 和附加字段设计，但没有把它写入正式 0.2.1 文件。

## 主 Agent 建议

当前建议为“推荐 G”，理由是它保持正式 0.2.1 身份、无需未经批准的逐切片旋转协议迁移。该建议附带前置条件：后续真实计算前必须在独立新 case 中验证负向来流边界角色、压力/速度回流处理和全局力符号。路线 L 在坐标变换和虚功上更完整，但需要 Sol 另行批准候选 0.2.2、checkpoint 扩展和迁移策略，不能在本阶段直接采用。

## 文件

- `results/08_stage4e_physical_baseline_v3_2/bidirectional_route_G_candidate.json`
- `results/08_stage4e_physical_baseline_v3_2/bidirectional_route_L_0_2_2_candidate.json`
- `results/08_stage4e_physical_baseline_v3_2/source_pin_and_hash.json`

VIVdatashare 来源 pin 为 commit `fe251f958ddf2f083b53cdb53a9d2addde85e17e`；CSV 与 `main1.m` hash 均与 v3.1 已核对值一致，项目中未保存原始 CSV。

本报告不宣称真实双向 CFD、真实 7/9 切片、严格试验幅值验证或长时间 VIV 完成。
