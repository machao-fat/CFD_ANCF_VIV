# Stage 4F-C 稳定化耦合协议候选

新增 `0.3.0-candidate.1`，正式协议 0.2.1 保持只读。该候选只授权离线伪 case，不授权真实 CFD。

候选固定 `alpha=0.1`，原始 CFD 力不可改写，applied force 单独生成并与原始力共同进入 checkpoint。冻结硬门槛必须在结构 correction 和 checkpoint prepare 前执行；失败步立即拒绝，不产生部分 commit。rollback 仅允许回到最后一个 unified committed checkpoint，失败 fields 保留为证据且禁止复用。

compileall 与状态机专项测试 4/4 通过。该结果只证明交易语义可被一致表达，不证明欠松弛能够稳定 CFD-ANCF，也不改变 repair2/D1 的数值失败。

Gate：`candidate_protocol_frozen_for_offline_fake_case_only`。下一授权点是独立伪 case adapter 与 transaction 审计，仍不能运行 A/B/C。
