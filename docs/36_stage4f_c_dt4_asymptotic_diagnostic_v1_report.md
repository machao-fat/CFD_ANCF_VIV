# Stage 36 dt/4 渐近趋势诊断

`STAGE4F_C_DT4_ASYMPTOTIC_DIAGNOSTIC_V1_GATE: pass`

`DT4_TREND_STATUS: classified`

`STAGE4F_C_NUMERICAL_ACCEPTANCE_STATUS: still_blocked_pending_contract_decision`

全新 D 使用 run_id `stage36_dt4_diagnostic_v1`、dt `0.000625 s`，完成 80/80 physical committed 和 80/80 fully audited，时间 `1.5075 -> 1.5575 s`，tick `1507500000 -> 1557500000`。checkpoint 80 个、raw snapshots 240 个，lineage、UTF-8、mtime_ns、tick、identity 和 manifest 全部通过。owned process 400/400/0（MATLAB 160、WSL/OpenFOAM 240）。

D 硬门槛：max CFL `0.03413064838562284`；max raw `|Cd|` `9.691461127590776`；velocity consistency `8.914089748292407e-05`；virtual-work `5.080411972828451e-16`；force conversion `0`；geometry error `8.326672684688674e-17 m`。未改变正式阈值。

按 Stage 35 冻结梯形积分合同，raw x normalized difference 为 A/C `0.057765616492638706`、C/D `0.022445713650885712`、A/D `0.08021133014352441`；raw y 为 `0.002306025190631599 / 0.003144383629047539 / 0.005450408819679137`；applied x 为 `0.009116491932023563 / 0.0042827310486069714 / 0.013399222980630536`。因此趋势分类为 `dt4_improves_monotonicity`：C 到 D 的 raw x 差减小，但 D 与 A 的差异扩大，尚不能视为正式时间收敛证明，也不能改变 A/C 的 5% Gate。

父 checkpoint 实测 SHA-256 保持 `5db86ae104015d51a8268862a1551579d96d0d80ddc7f55536371efc0334e`；历史转录冲突沿 Stage 35 记录。compileall 通过；Stage 36 专项 `2/2 OK`；根目录 `902/902 OK`，1 项既有 Windows symlink skip。未重跑 A/B/C，未进入五/九切片、长时 VIV、锁定区或实验验证。

下一步需要合同决策：保持正式 A/C 失败并停止，或另行授权共同 warm-up/初始化合同变更或 dt/4 后续研究；本诊断不构成正式数值接受。
