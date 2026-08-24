# Stage 4E-B1 Sol 主 Agent 复核

## 结论

状态：`cfd_subgate_passed_project_gate_pending_runner_hygiene`

路线 G 的正向/反向刚性圆柱 OpenFOAM 烟测在边界角色、网格镜像、流场镜像、全局力符号、通量守恒和运行稳定性方面通过。该 CFD 证据无需重跑。

项目级 Gate 暂缓，原因是 persistent ANCF 测试环境存在 MATLAB worker 生命周期缺陷和大量历史残留进程。下一轮只允许修复 runner 启动失败清理、测试隔离和回归审计，不得重跑 CFD。

## 接收的 B1 证据

- 最终 run：`stage4e_b1_20260812T155537Z_586210c4`。
- 正向：左入口、右出口、`U=(+1,0,0)`。
- 反向：右入口、左出口、`U=(-1,0,0)`。
- 正反网格相同，`checkMesh` 均为 `Mesh OK`。
- 最大点镜像误差 `2.6645e-15 m`，最大单元中心镜像误差 `3.6737e-15 m`。
- 正反求解器返回码均为 0，均完成 210 步并到达 0.525 s。
- 最大 CFL 分别约 0.18416666 和 0.18416645。
- 最大 `E_U=2.6700e-5`，最大 `E_p=5.7309e-4`。
- `E_Fx=2.0478e-5`，`E_Fy=7.5706e-3`，`E_Cd=2.0478e-5`。
- 正反通量误差分别约 `7.72e-13` 和 `1.31e-12`。
- 父 Stage 4E-A 证据保持不变。
- B1 专项测试由 Sol 独立复跑：24/24 通过。
- 不含 persistent ANCF 的全项目测试由 Sol 独立复跑：340/340 通过。

OpenFOAM 日志中的 `sigFpe : Enabling floating point exception trapping` 是正常启动信息，不是 `SIGFPE` 崩溃。日志包含 `End`，结构化结果无 NaN/Inf/FATAL。

## 回归失败归因

原全量回归记录为 344 项中 1 failure、4 errors：

1. `multi_slice_driver` 的 `correct_calls` 断言失败单独复跑通过；排除 persistent ANCF 后的 340 项整体也全部通过。因此该项属于一次性顺序/资源污染证据，不构成稳定代码回归。
2. 4 个 `persistent_ancf` 用例可稳定复现为 MATLAB worker 初始化超时或启动器退出码 1。
3. 系统中存在大量跨多日的 MATLAB 进程；本次诊断启动的 MATLAB 子进程已被精确识别并只清理本轮 PID，未触碰更早的用户进程。
4. `PersistentANCFRunner.start()` 在 `_call("initialize")` 抛出 timeout/worker-exit 异常时没有执行自己的进程和日志句柄回收。由于异常发生在 unittest `setUp()` 内，`tearDown()` 不会执行，导致每个失败用例继续遗留 MATLAB 进程。
5. `shutdown()` 只捕获 `PersistentRunnerError`，但初始化超时抛出内置 `TimeoutError`，生命周期处理需要统一。

## Gate 决定

- 路线 G 边界/坐标 CFD 子门：`passed_with_scope_limits`。
- B1 项目级 Gate：`pending_runner_hygiene_and_full_regression`。
- B1 CFD 重跑：`not_required`。
- 高 Re 模型试算：暂不授权。
- 真实九切片 CFD–ANCF：不授权。
- 自由 VIV、锁定区、严格试验幅值：不授权。

## 下一步

执行 Stage 4E-B1-v2 回归环境收口：

- 修复 `PersistentANCFRunner` 对自己创建的子进程的异常回收；
- 不自动杀死任何既有或非本 runner 拥有的 MATLAB 进程；
- 增加无 MATLAB 依赖的 fake-worker 生命周期测试；
- 在运行真实 persistent ANCF 测试前审计环境；
- 若因历史 MATLAB 进程导致真实测试仍不能执行，应输出 `environment_blocked`，不得伪造成代码失败或通过；
- 复跑 24 项 B1、340 项非 MATLAB 回归和完整回归；
- 不运行 OpenFOAM。
