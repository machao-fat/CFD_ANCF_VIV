# Stage 78 Restart Bridge Time Mapping Repair

## Gate

`STAGE4F_D_RESTART_BRIDGE_TIME_MAPPING_REPAIR_V1_GATE: pass`

本阶段仅执行离线修复与验证，真实 MATLAB、OpenFOAM、WSL、CFD 启动数均为 0。

## 根因与修复

Stage74 step559 重启时，旧 bridge 将 global step 直接当作 reader step，且没有显式区分 source/current seed 与 target advance。新增 `src/coupling/multi_slice_driver/restart_bridge_mapping.py`，定义 canonical mapping：

- source/global：559，2.2075 s，2207500000
- target/global：560，2.20875 s，2208750000
- case-local bridge：seed=0，target=1

所有 seed、target、ack、step、time、tick 和 consumed 状态均 fail-closed 校验。未修改 ANCF/EB 核心、正式 0.2.1 协议、物理参数或数值阈值。

## 验证

- restart bridge fault injection：10 passed
- Stage67–77 相关离线回归：全部通过
- compileall：通过
- 根目录 unittest：932 tests，OK，1 skipped
- 真实进程启动：MATLAB=0，OpenFOAM=0，WSL=0，CFD=0

Stage75 attempt2/3/4 失败 runtime 只读保护，未复用、续跑或修改。Stage75 未启动。

正式统计状态仍为 `frequency=not_evaluable_insufficient_cycles`、`FORMAL_STROUHAL_STATUS=not_completed`、`STABLE_VIV_RESPONSE_CLAIM=not_completed`、`LOCK_IN_CLAIM=not_completed`。

只有取得新的明确授权后，才可使用全新 run/case/runtime 申请一个 Stage75 segment。
