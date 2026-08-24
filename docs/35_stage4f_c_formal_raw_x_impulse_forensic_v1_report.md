# Stage 35 正式 A/C raw x impulse 离线取证报告

`STAGE4F_C_FORMAL_RAW_X_IMPULSE_FORENSIC_V1_GATE: pass`

`RAW_X_IMPULSE_ROOT_CAUSE_STATUS: classified`

`STAGE4F_C_NUMERICAL_ACCEPTANCE_STATUS: still_blocked_pending_contract_decision`

根因分类为 `mixed_initial_transient_and_raw_CFD_time_step_sensitivity`。本次只读取 Stage 30 A、Stage 34 C 和父 checkpoint 的 immutable artifacts，未启动 MATLAB、OpenFOAM 或 WSL，未修改旧证据。

父 checkpoint canonical path 为 `cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/formal_preflight_attempt3/checkpoints/checkpoint_step00000002_d4def62051c1.json`，实测 SHA-256 为 `5db86ae104015d51a8268862a1551579d96d0d80d82ddc7f55536371efc0334e`。历史转录值存在字符缺失；旧 JSON 未修改，冲突逐项记录于 `hash_conflict_audit.json`。

从 60 个 A raw snapshots 和 120 个 C raw snapshots 独立解析 terminal force，并按冻结合同复算。A raw impulse x/y 为 `1503.5493706783463 / 5.619662258457884 Ns`，C 为 `1525.2114768630838 / 4.75490281197104 Ns`。归一化差为 `0.057765616492633245 / 0.0023060251906315845`，精确复现 Stage 34；raw x 仍超过 0.05。applied x/y 诊断差为 `0.009116491932023563 / 0.0014486219745579636`，不能替代 raw Gate。

raw x 差异按 slice 0/1/2 分解为 `10.71744793712162 / 0.19343597852434868 / 10.75122226909167 Ns`。首个正式区间贡献最终 signed difference 的 `55.92961935692902%`；`1.5100 s` raw x 点值归一化差为 `0.8139009456199101`。A 和 C 使用相同父状态和相同 endpoint tick，但 A 通过一个全步到达 endpoint，C 通过两个半步到达，raw CFD 经历不同的 motion/field update history。P/Q 与正式 A/C 均表现出早期 raw-x 时间步敏感性。

已排除 snapshot hash/size/mtime/identity 错误、重复或缺失 slice、跨 run artifact、tick 错序、raw/applied 混用、三切片合并错误、单位/归一化错误和正式梯形比较器错误。左/右矩形仅为诊断，不能改变冻结 Gate。去除首区间的结果也仅作为 counterfactual 保存。

remediation matrix 的默认合规路径是保持正式失败并停止。仅修复比较器不适用，因为未发现实现错误。共同 warm-up 后重跑 A/C 会改变初始化和正式合同；dt/4 可用于独立渐近趋势诊断；改变窗口、排除首步或接受 5.7766% 都会改变冻结合同，未经授权不得实施。

compileall 通过；Stage 35 专项 `2/2 OK`；根目录 `900/900 OK`，1 项 Windows symlink 权限测试明确 skip。最小下一授权为二选一：独立 dt/4 离线趋势所需的新真实运行授权，或共同 warm-up/初始化合同的研究变更授权。两者均不得被视为当前数值 Gate 已通过。
