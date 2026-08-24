# Stage 4E-A-v3.2.1 Sol 主 Agent 复核

## 最终判断

状态：`numerical_evidence_accepted_protocol_identity_fix_required`

Stage 4E-A-v3.2.1 已解决 v3.2 的速度量纲、最终候选 H 留出验证、路线 G 与正式 0.2.1 字段隔离和全量测试发现问题。速度、7/9 切片积分、不确定性、正式 H 投影、旧证据保护和 311 项回归证据可以接收。

离线 Gate 暂不正式通过，原因是最终推荐方案与正式协议工件的切片身份不一致。不得在修正前启动真实 OpenFOAM。

## 主 Agent 独立复核结果

- `python -m compileall -q src tests`：通过。
- v3.2 专项测试：11/11 通过。
- v3.2.1 专项测试：12/12 通过。
- 根目录全量测试：311/311 通过，耗时约 92.844 s。
- 速度缩放实现采用 `0.48/1365`，不再直接除以 1000。
- 1000 组不确定性结果支持零交叉感知 9 切片；零交叉感知 7 切片因 PCHIP 模态 p95 为约 10.42% 未冻结。
- 最终 9 切片的正式 H 留出验证满足频率、MAC 和 1% 投影误差阈值。
- 路线 G 字段没有注入正式 0.2.1 数据类。

## 阻断问题：7/9 切片协议身份错配

最终摘要冻结：

`zero_crossing_aware_9_point_sampling`

但下列正式/候选工件仍绑定零交叉感知 7 切片：

- `official_0_2_1_compatibility.json`
- `route_G_flow_profile_candidate.json`
- `route_G_checkpoint_binding_candidate.json`

具体证据：

- 正式 case_id 为 `stage4e_v3_2_1_final_zero_aware_7`；
- 正式 manifest 只有 7 个 slice；
- 路线 G flow profile 只有 slice_id 0–6；
- checkpoint binding 只有 7 个 slice；
- 正式 manifest hash 为 `8b5bfccd655546fd5acba6c477c47bf6d073d2a8b19b58ca161b7987ad23d967`，对应 7 切片而不是最终 9 切片；
- flow profile hash `bb2ee58630bd3507ea718d5118b56479951e3664fb53d153239d34b442b87b35` 同样绑定 7 切片；
- 最终摘要中的目标网格判断也读取 7 切片 H 结果，而不是最终 9 切片结果。

根因位于 `correct_stage4e_v3_2_1.py`：

- `protocol_compatibility()` 硬编码读取 `zero_crossing_aware_7_point_sampling`；
- `route_G_artifacts()` 硬编码读取 `zero_crossing_aware_7_point_sampling`；
- `target_mesh_recommendation` 硬编码读取 7 切片目标结果；
- Gate 判据没有检查推荐候选、manifest、flow profile、checkpoint binding 和 H 证据是否属于同一切片集合。

## 接收范围

- 速度量纲修正：`accepted`
- 7/9 切片及不确定性：`accepted`
- 最终 9 切片 H 留出验证：`accepted`
- nElem=8 最低生产网格：`accepted_for_offline_candidate`
- 311 项回归：`accepted`
- 零交叉感知 9 切片冻结：`accepted_pending_identity_materialization`
- 当前 7 切片 manifest/flow/checkpoint 工件：`rejected_as_final_identity`
- 路线 G：`provisional_pending_reverse_flow_smoke`

## 下一步

执行 Stage 4E-A-v3.2.2 微修复：只根据已通过的最终 9 切片结果重新物化正式 0.2.1 manifest/config、路线 G flow profile、checkpoint binding 和一致性摘要，并增加跨工件身份测试。

不需要重跑 MATLAB、Monte Carlo 或 H 数值计算，也不允许启动 OpenFOAM。v3.2.2 通过后，才可正式通过离线 Gate，并生成正/反向刚性圆柱边界烟测任务。

## Gate

- Stage 4E-A-v3.2.1 离线 Gate：`not_passed_identity_fix_required`
- 真实 CFD：`not_authorized`
- 所需修正规模：`small_offline_artifact_rematerialization`
