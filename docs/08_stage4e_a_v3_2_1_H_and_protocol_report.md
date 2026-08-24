# Stage 4E-A-v3.2.1：正式 H 留出验证与协议边界报告

状态：完成离线正式接口验证；未宣布真实 CFD 可用。

## 正式 H 留出验证

验证直接读取 v3.2 的真实 nElem=8/16 ANCF MAT 文件，并调用生产 `build_H_for_manifest`，其内部为正式 `ancf_hermite_H`。没有使用正弦曲线、归一化采样曲线、手工插值或解析梁振型冒充 H 证据。

对 nElem=8/16 分别在独立 401 点公共致密网格构造 H 投影，用致密网格做简并子空间 Procrustes 对齐，再在最终零交叉感知 7 与零交叉感知 9 切片中心评价。候选中心未参与对齐求解。H 维度为 7×3×54 / 7×3×102 或 9×3×54 / 9×3×102；qmode 维度为 54×12 与 102×12。刚体平移和线性轴向构型误差均低于 `1e-12 m`。

报告中的误差明确标记为 `shape-scaled modal projection diagnostic`，不代表真实 VIV 幅值误差。频率差均低于 2%，致密网格子空间 MAC 均高于 0.95，最终候选中心最大 shape-scaled 物理投影差均低于 1%；CF mode 1、IL mode 2、IL mode 4 全部通过。详情见 [final_candidate_formal_H_projection.json](../results/08_stage4e_physical_baseline_v3_2_1/final_candidate_formal_H_projection.json)。

## 0.2.1 协议边界

正式 `SliceManifest` 与 `RuntimeConfig` 保持生产 0.2.1 字段集合。路线 G 的 `signed_U_global_mps`、`flow_sign`、`active`、`boundary_role` 和局部速度信息没有注入正式对象；额外字段解析会被正式数据类拒绝。manifest/config hash 均可重复计算。详情见 [official_0_2_1_compatibility.json](../results/08_stage4e_physical_baseline_v3_2_1/official_0_2_1_compatibility.json)。

路线 G 仅输出独立 `FlowProfileV1Candidate` 工件，哈希名称严格为 `flow_profile_sha256`，不冒充 `config_sha256`。速度、符号和边界角色变化均会改变候选 restart identity。负向来流未来真实 CFD 需互换上/下游边界角色、使用负入口速度矢量、保持圆柱/网格/全局坐标不变、按全局坐标解释 OpenFOAM 力、不额外旋转载荷，并检查出口回流边界条件；本阶段未进行 smoke test，因此状态只能为 `provisional_pending_reverse_flow_smoke`。路线 L 仍为 0.2.2 candidate，未升级或冻结。
