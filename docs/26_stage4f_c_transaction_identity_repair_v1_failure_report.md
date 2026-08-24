# Stage 26 transaction identity 修复失败报告

`STAGE4F_C_TRANSACTION_IDENTITY_REPAIR_V1_GATE: do_not_pass`

唯一终态：`P_snapshot_mtime_precision_failure`。

Stage 25 的首次 identity 分叉位于 `DiagnosticEngine` 创建 process：process 使用下游默认 `stage4f_timestep_diagnostic_v3_d2`，scheduler 后置覆盖为 `stage25_probe_P`。Stage 26 将 factory plan 的 `stage26_probe_P_exact_tau_v1` 作为唯一来源，并在真实 P 中确认 factory、scheduler、三个 process、artifact path/manifest 全部一致。

Stage 23 tau 仍为 `0.023728053952574758`，source hash `d24b089822478160986b93584f391dbe636de164994411938da5b5e850e77369`，canonical payload hash `cb2e95fc8c3f91769235a9799c6b6e7b1a628f630c5e0aa6342b786945181f78`。alpha 与两个半步验证保持通过。

离线门：compileall pass，Stage 26 专项 5/5，Stage 25 回归 8/8，根目录 872/872 OK。

唯一授权的全新 P 在 step 0、checkpoint commit 前失败。三个 snapshot 的 path、run/case/step/slice/tick、size 和 SHA-256 均正确；generic `_state_tree` 将 `mtime_ns` 整数转换成 binary float，写入 prepared manifest 后丢失纳秒整数精度，严格文件复验报 `raw force snapshot artifact changed`。无 committed checkpoint，稳定器未推进，P=0/6。同一 runtime 未重试，Q/A/B/C 未启动。

MATLAB 2/2/0、WSL/OpenFOAM 3/3/0，全部 return code=0。partial fields、三个 snapshot、prepared manifest、日志和 PID registry 均保留。

最小下一步需要新授权 attempt：为 identity/mtime/tick 等字段使用保整数的 manifest serializer，增加大于 2^53 的 mtime_ns round-trip 和 prepare/commit/restart 测试，然后仅重新运行全新 P。
