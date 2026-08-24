# Stage 4E-A-v3.2.2：最终九切片 Gate 候选

## 状态

`V3_2_2_IMPLEMENTED: yes`

本阶段完成最终九切片协议身份物化和跨工件一致性收口，不重复执行 v3.2.1 的速度、不确定性或 H 数值计算。

## 最终身份

- `SELECTED_CANDIDATE: zero_crossing_aware_9_point_sampling`
- `FINAL_MANIFEST_SLICE_COUNT: 9`
- `FINAL_FLOW_PROFILE_SLICE_COUNT: 9`
- `FINAL_CHECKPOINT_BINDING_SLICE_COUNT: 9`
- `CROSS_ARTIFACT_IDENTITY: passed`
- `target_mesh_recommendation: nElem=8`
- `case_id: stage4e_v3_2_2_final_zero_aware_9`

正式 manifest/config、九切片 H 身份、Route-G flow profile 与 checkpoint binding 均指向同一九切片候选。7 切片工件冒充最终身份的测试已明确拒绝。

## 范围边界

未运行 MATLAB、Monte Carlo、H 重算、OpenFOAM、真实 CFD、长时间 VIV 或锁定区分析。路线 G 不能宣布真实可用，真实 CFD 入口建议仍为“建议不进入”。

完整 hash、跨工件 checks 和测试结果见 [stage4e_a_v3_2_2_final_candidate_summary.json](../results/08_stage4e_physical_baseline_v3_2_2/stage4e_a_v3_2_2_final_candidate_summary.json)、[cross_artifact_identity_audit.json](../results/08_stage4e_physical_baseline_v3_2_2/cross_artifact_identity_audit.json) 和 [final_candidate_identity.json](../results/08_stage4e_physical_baseline_v3_2_2/final_candidate_identity.json)。
