# Stage 4E-A-v3.2.1：最终离线 Gate 候选

## 结论

离线修正、正式 H 留出验证、0.2.1 兼容性审计和回归测试均完成。推荐切片方案为 `zero_crossing_aware_9_point_sampling`，目标网格推荐 nElem=8。由于本阶段禁止 OpenFOAM，真实 CFD 入口建议必须为“建议不进入”。

## 关键证据

- 速度：`0.48 * U_digitized / 1365`；名义最大值 0.48 m/s。
- 不确定性：1000 个样本，随机种子 20260812；两端固定、内部坐标严格递增，未使用 `maximum.accumulate`；零交叉感知 9 在线性和 PCHIP 下均满足 p95 阈值，中心方向变化次数为 0。
- H：真实 MAT、正式 `build_H_for_manifest`/`ancf_hermite_H`、401 点独立对齐网格；7/9 最终候选频率、MAC 和中心投影阈值均通过。
- 协议：正式 0.2.1 manifest/config 未加入路线 G 字段；路线 G 仅为独立候选工件。
- 测试：compileall 通过；v3.2 专项 11/11；v3.2.1 专项 12/12；根目录全量 311/311。

完整数值、文件哈希、停止条件和风险见 [stage4e_a_v3_2_1_final_candidate_summary.json](../results/08_stage4e_physical_baseline_v3_2_1/stage4e_a_v3_2_1_final_candidate_summary.json)。本报告不宣布 Stage 4E 或真实 CFD 验证完成。
