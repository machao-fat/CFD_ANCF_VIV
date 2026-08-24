# Stage75 candidate 1 attempt8 report

`STAGE75_E5_CANDIDATE_1_GATE: do_not_pass`

attempt8 使用全新 run/case/runtime/results，从 Stage74 step559 source 启动。step520 的 target motion 消费阶段因外层 formal segment 仍传入旧时间 2.15875 s 而超时；没有提交 physical step、checkpoint 或 snapshot，未启动后续 block，也未重试 attempt8。

source SHA 前后均为 `341b9ccf21e0436791456333a6c3baccfde69c3735f717763d576952dba0a226`，owned residual 为 0。失败 runtime 只读封存。

已完成离线修复：formal segment target time 现在按 `start_time + (step-start_step+1)*dt` 计算，与 restart source/current/target 时间统一。未修改物理核心、协议、物理参数或阈值。需要新的明确授权后，才可使用新的 run/case/runtime 再申请 segment。
