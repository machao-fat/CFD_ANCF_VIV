# Stage94 MATLAB worker bridge adapter

`STAGE4F_D_PERFORMANCE_MATLAB_WORKER_BRIDGE_V1_GATE: pass`

本阶段为离线接入验证。新 adapter 保持现有 campaign 的 `initialize`、`predict`、`correct`、`finalize_committed`、`discard_staged` 和 `shutdown` 接口；高 step `560--599` 共执行 40 次 prediction 和 40 次 correction，由一个 persistent worker 完成。

Stage94 没有修改 `multi_slice_real_campaign/campaign.py`，没有修改 ANCF/EB 核心、物理参数、global dt、slice 数量、稳定化参数、数值阈值、统计门槛或正式 0.2.1 语义。旧 evidence、attempt7--19 runtime 和 Stage93 产物保持只读。

当前仍未实现用户 SessionId=1 runner 对完整 worker contract 的真实 MATLAB 执行，因此本阶段没有真实收益测量。直接启动旧 campaign 只能重复得到 attempt19 的旧架构耗时，不能作为优化结果。

专项测试：bridge 4 passed、user-session contract 2 passed，0 failure，0 error；根目录 unittest 965 tests，0 failure，0 error，1 skipped，`OK`。compileall 通过。真实 MATLAB/OpenFOAM/WSL/CFD 启动数均为 0，owned residual=0。

下一步是建立用户会话 MATLAB worker contract；该 contract 离线 Gate 通过后，才能使用新的 run_id、case_id 和 runtime 做一次固定 40-step 真实测量。
