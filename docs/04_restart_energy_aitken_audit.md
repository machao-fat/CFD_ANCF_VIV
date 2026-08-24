# 阶段三 restart、能量与 Aitken 专项审计（2026-08-05）

## 结论

本专项修复了能量初值、ANCF 顶张力势能、raw/applied 载荷功和 Aitken 公式等确定性代码问题；轻量自动测试通过。但严格 OpenFOAM restart 计算尚未执行，Aitken 也没有接入 CFD 场回滚，因此阶段三仍不通过，不能宣称“强耦合完成”，也不能进入多切片。

## 1. 严格 restart 等价测试

已新增只读分析器 `tests/online_motion_adapter/analyze_restart_equivalence.py`。它会合并 restart 前后不同 function-object 起始目录的 `forces.dat`，保留并核对 restart 边界重复样本，并逐步比较：

- native 连续解与 native restart 解；
- `ancfFileMotion` 连续解与 file restart 解；
- restart 后 native 与 file 解；
- restart 时刻和终止时刻的 `U`、`p`、`polyMesh/points`。

隔离算例已准备在：

- `cases/openfoam/online_motion_restart_audit_native_20260805`
- `cases/openfoam/online_motion_restart_audit_file_20260805`

两者只复制原严格 A/B 的 `0/constant/system`，第一段设置为 `0 -> 0.5 s`，旧 A/B 结果没有覆盖。由于同时有 SDOF 计算，本专项没有继续启动 OpenFOAM；故 restart 状态仍是 `not_run_or_incomplete`。

后续最小执行顺序为：

1. 两个隔离算例分别运行 `0 -> 0.5 s`；文件式算例由逐步正弦 publisher 驱动。
2. 把 `controlDict` 改为 `startFrom latestTime; endTime 1;`。
3. 文件式 restart 使用新的空确认目录，例如 `coupling/consumed_restart`；publisher 从 step 200 开始。不能复用第一段的 `motion_consumed_200.json`，否则会提前发布 step 201。
4. 分别运行 `0.5 -> 1 s`，保留 `postProcessing/.../0` 与 `postProcessing/.../0.5`。
5. 用新增分析器输出正式 JSON。只有逐步力、时间序列以及 restart/终止状态场同时通过，才可把 `restart_checked` 设为 true。

## 2. 能量审计修复

### 2.1 初始能量丢失

`PersistentMatlabRunner.get_energy()` 已经返回内部 `energy` 字典；连续驱动器原来又调用一次 `.get("energy")`，把真实初始能量变成空字典。首步于是错误地以零储能为基准，污染全窗残差。现已改为直接保存 `runner.get_energy()`，并逐步输出 `stored_energy_previous_J`。

### 2.2 ANCF 顶张力势能

ANCF 将顶张力作为恒定端部 `base_load`，`ancf_postprocess` 已计算 `external_potential_J`，完整机械能为动能、内能和该势能之和。旧在线审计只取动能与内能，定义不闭合。现在结构 runner 显式输出：

- `external_potential_energy_J`；
- `stored_energy_J = mechanical_energy_J`。

EB/ANCF 均以求解器完整 `mechanical_energy_J` 作为保守储能；相对残差尺度只使用功、能量变化和结构功通量，不再使用巨大但不参与增量平衡的绝对基线能量。

### 2.3 raw/applied 力与缺陷分解

与 `load_mode=transverse_only` 合并后采用：

```text
P_CFD        = F_raw · v_pred
P_structure  = F_applied · v_corr
P_projection = (F_raw-F_applied) · v_pred
P_temporal   = F_applied · (v_pred-v_corr)
P_defect     = P_projection + P_temporal
```

这样不会把人为去掉顺流向力造成的功差误叫作弱耦合时间误差。离线审计优先使用 `applied_force_*_N` 计算结构功；旧CSV没有该字段时才回退到 raw force。

### 2.4 窗口和单位

- 功率单位为 `N·m/s = W`，时间积分后为 `J`。
- 新结果必须逐行声明 `force_representation=integrated_N`；缺失或使用 `N/m` 时，工具准入标志为 false 或直接拒绝。
- 显式审计窗口采用状态边界 `(t_start,t_end]`，边界必须与保存状态对齐。
- 默认“后半段”只叫 `heuristic_last_half_not_verified_steady`，不能自动代表稳态。
- 只有显式窗口、外部稳态判据、已知窗口初始储能、完整储能字段和积分力单位同时满足时，`physical_energy_acceptance_ready` 才可能为 true。

旧 100 步结果重新审计后，EB 后半窗诊断残差约 `11.7%~11.8%`，ANCF 约 `0.74%`。这些数都不能用于物理验收，因为旧CSV初始能量不是独立状态、缺少力表示元数据、窗口未证明稳态，而且位移仍接近数值容差。

## 3. Aitken 与强耦合准入

### 3.1 已修复部分

原矢量 Aitken 的更新分子误用了当前残差。现采用标准形式：

```text
omega_k = -omega_(k-1) r_(k-1)^T (r_k-r_(k-1)) / ||r_k-r_(k-1)||^2
```

`reset()` 现在同时清空残差历史并恢复初始松弛因子。标量解析固定点测试验证第二次更新得到理论 `omega=2` 并精确到达固定点。

Python ready 协议现在要求 marker 包含 `coupling_iteration`，核对 marker 与CSV一致，并可要求指定迭代号。

### 3.2 仍缺失的闭环

当前不能集成真实强耦合，原因是：

1. `ancfFileMotion.C` 没有读取、校验或回写 `coupling_iteration`。
2. C++运动函数按 OpenFOAM `timeIndex` 缓存，同一物理时刻的新迭代运动不会自动刷新。
3. 载荷发布器以 `step` 去重，无法区分 `(step, coupling_iteration)`。
4. 当前 `pimpleFoam` 连续进程只能向前推进，没有恢复同一时间步起点的接口。
5. 尚无对 `U/p/phi`、动网格、旧时间层、湍流/输运状态以及 function-object 输出的原子 checkpoint/rollback。
6. MATLAB结构 checkpoint 已存在，但没有驱动器把它与CFD checkpoint组成同一事务。

此外，`continuous_fsi_driver.py` 的命令行入口仍把单切片 `s_ref_m=[0.5]` 以及 `L/D/nSlices` 写死在示例配置中。本专项没有改动该研究参数；在后续生产算例前应改为显式配置文件或CLI输入，并由 motion/load 合约核对，不能直接沿用到多切片。

最小强耦合烟测应先在一个物理步内执行两次完全相同界面猜测：每次均从同一CFD/结构 checkpoint 恢复，要求水动力和修正位移逐步相同。该“回滚确定性”通过后，再启用2~5次 Aitken 子迭代并检查位移、速度、力三个残差。最终接受的CFD场必须对应最终松弛界面，而不是上一轮临时场。

## 4. 自动测试

- Python `py_compile`：5/5；
- Python unittest/直接断言：16/16；
- MATLAB persistent EB/ANCF runner：2/2；
- Aitken专项：4/4；
- restart 合并分析器合成数据测试：1/1。

证据位于：

- `results/04_coupling_audit_review_20260805/coupling_audit_summary.json`
- `results/04_coupling_audit_review_20260805/python_lightweight_tests.log`
- `results/04_coupling_audit_review_20260805/matlab_structure_runner_contract.log`
- `results/04_coupling_audit_review_20260805/energy/existing_case_reaudit_summary.json`

## 5. 验收表述

可以声明：“能量审计工具、结构能量初值、顶张力势能、载荷投影分解及Aitken数学模块已修复并通过轻量回归。”

不能声明：“稳态物理能量已经守恒”“OpenFOAM restart 已严格等价”“Aitken 强耦合已经完成”或“阶段三通过”。
