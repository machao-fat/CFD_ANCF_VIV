# Stage75 candidate 1 attempt9 report

`STAGE75_E5_CANDIDATE_1_GATE: do_not_pass`

attempt9 使用全新 run/case/runtime，从 Stage74 step559 正常完成并审计了 step520：1 physical committed、1 fully audited checkpoint、3 raw snapshots，三个 slice 均 OpenFOAM return code 0，日志含 `End`，时间/tick 为 2.20875 s / 2208750000。

step521 seed 阶段 fail-closed。原因是清理旧 consumed ack 时错误使用了 global step 520，而 legacy bridge ack 使用 case-local step 1；因此旧 target ack 被视为当前 seed ack。没有继续启动后续 block 或 step，attempt9 未重试，owned residual=0。source SHA 前后一致：`341b9ccf21e0436791456333a6c3baccfde69c3735f717763d576952dba0a226`。

已完成离线修复：旧 seed ack 清理改为按 `current_clock_step` 的 case-local bridge step。物理核心、0.2.1 协议、物理参数和数值阈值未修改。attempt9 partial runtime 只读封存；需要新的明确授权后才能以全新 runtime 重新申请完整 segment。统计状态保持未完成。
