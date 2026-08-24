# Stage 41

STAGE4F_D_EXTENDED_TRANSIENT_ENTRY_DESIGN_V1_GATE: pass
STAGE4F_C_PARENT_STATUS: accepted_scope_limited
THREE_SLICE_EXTENDED_TRANSIENT_PILOT_STATUS: designed_pending_authorization

本阶段仅完成只读审计、离线时间尺度/成本分析和合同设计，未启动 MATLAB、OpenFOAM、WSL 或任何新 CFD。推荐一次 E1（额外 0.05 s，40 步，4 个 10 步 block）有限 pilot，需用户单独授权。当前 0.05 s 仅覆盖 5 个 convective times、0.1 个一阶结构周期及先验约 0.5–1 个脱涡周期，频率与稳定 VIV 不可评价；不输出 St 或长期结论。

基线 dt=0.00125 s，三 slice，source 为 Stage 40 已验收 committed checkpoint（具体路径/ID/hash 在 source_checkpoint_selection.json 中冻结）；父 checkpoint SHA-256 为 5db86ae104015d51a8268862a1551579d96d0ddc7f55536371efc0334e。硬停止沿用 CFL<0.8、|Cd|<=10、速度、虚功、力转换、几何、完整 slice/checkpoint/identity 和 residual 门槛，并增加墙钟/磁盘预算停止。五/九 slice、长时 VIV、锁定区和实验验证均保持 do_not_enter/not_completed。

离线专项测试、compileall 和回归结果见终端日志；Stage 40 旧证据未修改。
