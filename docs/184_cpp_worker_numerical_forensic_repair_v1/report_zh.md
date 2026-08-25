# Stage184 数值 forensic 修复报告

## 结论

本阶段没有通过数值等价 Gate。Stage183 的严格 MATLAB/C++ 双算仍为 `0/40`，首个失败为 `global_step=560`。Stage184 在不启动真实计算的条件下加入了逐单元/Gauss 点 C++ trace，并验证了 C++ 侧中间量均为有限值、80 个 Gauss 点完整存在。

当前可以确认：

- C++ 直接在 MATLAB target `q` 上评估的历史误差约为 `2.91e-11` 绝对值（Stage169 只读证据）；
- C++ worker 40-step 固定 force replay 为 `40/40`，但这不是 MATLAB 数值等价证明；
- 重新计算最终 `qddot/qd` 并复用 `dt^2` 暂存量没有消除严格双算差异；
- 首个 MATLAB 中间量与 C++ 中间量的对应导出不存在于受保护证据中，因此不能声称已经定位“第一个分歧来源”。

## 保护与进程

本阶段未修改 Stage1–183 旧证据、旧 runtime、MATLAB 参考实现、物理参数、global dt、slice 数、阈值或正式协议。真实进程启动数为 MATLAB=0、OpenFOAM=0、WSL=0、CFD=0；C++ worker 离线 replay 启动 1 次，owned residual=0。

## 修改

- C++ 新增独立 forensic trace API 和诊断程序，记录 `a/b/v/a2/v2/eps`、bending/axial 中间量、`B.'*ga`、`C.'*gb` 和 Gauss contribution；
- Newmark accepted state 在 Newton 退出后按 MATLAB 语义重新计算，并复用 `dt^2` 暂存量；该候选改变未通过严格双算；
- C++ selftest 增加零变形、刚体平移和刚体旋转不变量检查；
- 新增 Stage184 专项离线脚本、测试和证据。

## Gate

`STAGE4F_D_CPP_WORKER_NUMERICAL_FORENSIC_REPAIR_V1_GATE: do_not_pass`

`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`

下一步需要在新的明确 MATLAB 授权下导出与 C++ trace 同 schema 的 MATLAB step560 中间量；在该对照找到首个分歧并修复前，不具备新的 CFD confirm 资格。

## Git 版本记录

- 实现/证据提交：`e1266c1680fa4d2278b2727550887e9a90a0ac9a`。
- Git manifest 提交：`698cc09`；推送审计修订提交：`8e39297`。
- annotated tag：`cfd-ancf-viv-cpp-worker-numerical-forensic-repair-v1-stage184`。
- 分支 `codex/cpp-worker-comprehensive-audit-repair-v1` 和上述 tag 均已成功推送到 `origin`。
- `cases/`、`references/`、`FAKE_PROCESS_SUMMARY.json` 及其他无关用户文件未提交。
