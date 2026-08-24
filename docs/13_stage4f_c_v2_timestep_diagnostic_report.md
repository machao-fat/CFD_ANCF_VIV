# Stage 4F-C-v2 时间步诊断报告

## Gate 与终态

`STAGE4F_C_V2_TIMESTEP_DIAGNOSTIC_GATE: do_not_pass`

唯一终态为 `failure_identity_or_runtime_blocked`。D1 完成全部 6 步，但 Cd 和速度一致性误差显著超限；D2 在首步 motion bridge 时间身份检查处失败，未形成任何 unified committed checkpoint。因此不能判定 dt/4 收敛，也不能启动完整 A/B/C。

## 父身份

父 checkpoint 原始文件大小为 12037 bytes，mtime UTC 为 `2026-08-17T03:49:41.4701056Z`，实测 SHA-256 为 `5db86ae104015d51a8268862a1551579d96d0d80d82ddc7f55536371efc0334e`。历史值与 repair3 转录值实际完全相同，不存在字符冲突。Stage 4F-B-v5 Gate 通过 preflight/checkpoint audit 间接绑定该对象，自身未重复存放 hash 字段。

## D1

D1 使用 `dt=0.00125 s`，连续完成 `6/6`，覆盖 `1.5075 -> 1.5150 s`，提交 6 个完整 checkpoint。max CFL 为 `0.0743405296853943`，max `|Cd|` 为 `346.65279016444276`，max velocity consistency error 为 `0.33929320974259647`，max virtual-work relative error 为 `3.983535693438037e-16`，max force conversion relative error 为 0。

逐步 max `|Cd|` 为 `4.2513, 7.9666, 22.9559, 54.2760, 139.5771, 346.6528`；速度误差为 `0.00294, 0.00853, 0.02158, 0.05389, 0.13527, 0.33929`。D1 从 step 2 起仅触发允许继续诊断的 Cd/velocity Gate，未触发日志、CFL、虚功、转换、checkpoint 或进程 blocking failure。该趋势比 repair2 更差，不能支持“减小 dt 已解决超限”。

## D2

D2 使用 `dt=0.000625 s`。step 0 冻结目标为 `1.5081250000000002 s`，slice 0 bridge consumed marker 为 `1.50813 s`，相差约 `5e-6 s`。transaction 在 `MOTION_PUBLISHED` 阶段以 `SchedulerError: motion consumed bridge time mismatch` 停止。slice 0/1 solver 日志到达 `End`，slice 2 在精确关闭时 return code 为 1；全局完成步数和 checkpoint 数均为 0。

这是 runtime transaction time identity 失败。按冻结停止规则，不修改精度、容差或生产 bridge 后在同阶段重跑，也不增加 dt/8。

`d2_execution.json` 中的 `D2_authorized:false` 是失败后 branch audit 的字段，不代表 D2 未获许可。D2 已由 D1 的 `D2_authorized:true` 明确授权并实际启动，随后在 step 0 被阻断。

## 进程与范围

全部 owned process 启动/关闭/残留为 `36/36/0`。D1 的 30 条和 D2 的 4 条记录均包含 PID、creation time、parent PID、executable、command line、cwd、时间、return code、日志、shutdown method 与 ownership basis。未按名称批量终止。

最终 `compileall` 通过；v2、repair3 forensic、原 Stage 4F-C 和 classifier repair 专项分别为 `28/28`、`24/24`、`26/26`、`37/37`。全仓 `-f` 实际收集 `698` 项，`698/698` 通过，0 failure、0 error。

该 0.0075 s 诊断不构成涡脱落统计、稳定 VIV 响应、锁定区、实验验证或物理验证。
