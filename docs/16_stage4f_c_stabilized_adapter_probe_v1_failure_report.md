# Stage 4F-C 稳定化 adapter probe v1 失败报告

Gate：`do_not_pass`。唯一终态：`failure_pre_real_production_interface_extension_required`。

只读审查确认生产交易顺序为 motion publish/consume、CFD advance、raw load read、单次 H/Ht mapping、load consume、structure correction、checkpoint prepare/commit。当前 scheduler 在 raw load 与 correction 之间没有 raw gate 或 applied-force hook；checkpoint/restart 仅保存单一 `previous_slice_forces_N`，不能同时绑定 raw force、applied force、稳定化状态、integer tick 和 run identity。

独立 wrapper 无安全实现路径：替换 LoadRecord 会以 applied force 冒充 raw force；只在 `correct_all` 内松弛则缺少 CFL/Cd 上下文且 checkpoint lineage 不完整。该缺口经 Stage 16 可执行 preflight 和 Terra-A 只读复核一致确认。根据 Phase 2 停止规则，真实 CFD 与 restart probe 均未启动。

冻结合同已在真实计算前写入。离线回放引用的 repair2/D1 真实序列均在 step 2 因 raw Cd 与速度门槛被拒绝，协议实现确定但稳定性抑制未证明。

compileall 通过；Stage 16 2 项、candidate 11 项、timestamp 4 项，共 17 项专项测试全部通过。由于 pre-real interface gate 失败，全仓 unittest 和真实运行后审计不触发。owned process 0/0/0，checkpoint 数 0，父 checkpoint 与旧证据未改变。

最小修复需要新增正式 scheduler raw-gate/applied-force hook及 checkpoint/restart 双力状态字段。这属于生产核心接口修改，超出本任务冻结授权，不能通过 adapter 绕过。
