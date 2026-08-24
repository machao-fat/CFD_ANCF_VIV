# Stage 39 paired continuous/restart validation

`STAGE4F_C_PAIRED_RESTART_VALIDATION_V1_GATE: pass`  
`PAIRED_SOURCE_IDENTITY_STATUS: accepted`  
`RESTART_STATE_RESTORE_STATUS: accepted`  
`DT_0_00125_RESTART_STATUS: accepted`  
`DT_0_00125_BASELINE_STATUS: eligible_for_final_contract_gate`

Stage 39 使用全新 paired campaign。prefix 0--9 先生成一个 immutable unified committed source；其 source checkpoint 为 `step00000009_490b2bc460c1`，SHA-256 `37f7d7fa80ad0c3e3a37fbd379170e047a94d09568ceb369137d5dc8a96d5b6b`。CONT 和 REST 均从该同一 source 分叉，source 在 CONT 期间 hash 未改变。

执行步数：prefix `10/10`；CONT `30/30`（step 10--39）；REST `30/30`（step 10--39）。CONT/REST 每个共同 tick 的 q/qdot/qddot、raw force、applied force 最大相对差为 `0.0`，严格满足 `1e-11`。两个后缀 execution identity 不同，但 source ID/hash、numerical contract、tau、tick 和 parent lineage 一致。

配对后缀的 checkpoint、raw snapshot、UTF-8、mtime_ns、transaction identity、三 slice 完整性和 owned process 清理均通过。Stage 39 没有重跑 Stage 34/37，未启动五/九切片、长时 VIV、锁定区或实验验证。

父 checkpoint 实测 SHA-256 保持 `5db86ae104015d51a8268862a1551579d96d0d80ddc7f55536371efc0334e`。Stage 23--38 旧证据未修改。compileall 和 Stage 39 专项通过；根目录回归通过并保留既有 symlink skip。

该结果只证明 dt=`0.00125 s` 的 paired restart identity/state restore 合同可满足；完整 Stage 4F-C 最终证据聚合仍待授权，严格渐近收敛、GCI、五/九切片和长时物理验证均未完成。
