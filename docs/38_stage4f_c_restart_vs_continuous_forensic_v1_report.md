# Stage 38 restart versus continuous forensic

`STAGE4F_C_RESTART_CONTINUOUS_FORENSIC_V1_GATE: pass`  
`RESTART_CONTINUOUS_ROOT_CAUSE_STATUS: classified`  
`DT_0_00125_BASELINE_STATUS: still_blocked_pending_restart_decision`

本阶段仅读取 Stage 34 C、Stage 37 10+30 restart 及父 checkpoint artifact，未启动 MATLAB/OpenFOAM/WSL，未修改旧证据。父 checkpoint 实测 SHA-256 为 `5db86ae104015d51a8268862a1551579d96d0d80ddc7f55536371efc0334e`。

Stage 37 source checkpoint 为 step 9、tick `1520000000`；与 Stage 34 连续 C 的同一 tick 对齐。前 10 个共同步的 q/qdot/qddot、raw/applied force 数值逐项一致。首个真实分叉发生在 restart 后第一步 step 10、tick `1521250000`：q 最大绝对差 `4.429718281047726e-07`，qdot `0.0007087549249676361`，qddot `1.1340078799482178`，raw force 相对差 `0.22423037618960798`，applied force 相对差 `0.5024588683549213`。

首个分叉同时包含 parent checkpoint ID 和 config hash：连续 C 使用 `checkpoint_step00000009_743eeef030ec` / `ed9ecbf5869d3cbe17661cd250e6bf39a7b0a6b46d4c8b4bb336bc7de6d1e226`，restart 使用 `checkpoint_step00000009_5b31bf03ea30` / `acba94289fd2ccd5b0fb1340abc631f51b2922c0162814810134735c4df861cf`。这证明 restart 分支虽从同一原始父 checkpoint开始且自身 lineage 连续，但其 source state/config/CFD continuation artifact 并非连续 C 的同一内容；不是比较 tick 错位。所有 manifest 均为三 slice、raw、唯一 path、正确 run/tick。

根因分类：`mixed_restart_state_and_initialization_mismatch`，具体表现为 restart source checkpoint/config/CFD field continuation 与连续 baseline 不同，首个 restart continuation motion 后立即传播到结构和 raw/applied force。不能通过放宽 `1e-11` 解决，也不能直接接受 dt=`0.00125 s` baseline。Stage 34 C 的连续资格保持为历史连续证据；Stage 37 restart 资格冻结失败。

测试：compileall 通过；Stage 38 专项 `2/2 OK`；根目录 `906/906 OK`，1 项既有 Windows symlink skip。未重跑 Stage 37、C 或其他 CFD。

最小下一步是新授权的 restart state/config/CFD-field 修复，并以全新 baseline/restart attempt 验证；若要重生成连续 baseline，则需单独 CFD 授权。不得修改 1e-11 门槛或 dt 合同作为默认补救路径。
