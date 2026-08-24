# Stage 4F-C 稳定化候选离线回放失败报告

Gate：`do_not_pass`。唯一终态为 `offline_replay_failed_frozen_raw_gates_probe_not_started`。

repair2 与 D1 保存序列均只接受前两个离线步，并在 step 2 同时因 raw `|Cd|` 和速度一致性越过冻结门槛而拒绝。repair2 step 2 max raw `|Cd|=11.003110867115256`、速度误差 `0.01873367971574207`；D1 step 2 max raw `|Cd|=22.95586340396227`、速度误差 `0.02157847178976052`。欠松弛降低前两步 applied Cd 幅值，但符号翻转仍存在，且协议禁止用 applied force 绕过 raw gate。因此交替放大抑制未获证明，技术 CFD probe 未启动。

只读接口审查同时确认：生产 scheduler 在 load consumption 后直接进入 structure correction，checkpoint 仅保存一组 `previous_slice_forces_N`。当前没有独立 hook 同时满足 raw gate、applied force 和双力 lineage。任何真实接入都需要修改生产 scheduler/checkpoint 接口，超出本轮授权。

compileall 与专项测试 11/11 通过；由于离线停止条件先触发且未启动 probe，全仓 unittest 不作为该失败终态的后置条件。owned process 为 0/0/0。父 checkpoint 与生产核心 hash 未变。

下一步只能二选一：授权修改生产 scheduler/checkpoint 接口以支持候选协议，或修改候选协议/冻结合同。两者均属于明确要求停下来询问的授权边界。
