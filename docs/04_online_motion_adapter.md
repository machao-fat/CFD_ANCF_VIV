# OpenFOAM 10 在线未知运动适配

## 1. 方法选择

任务二已选定 `interpolatingSolidBody` 作为当前动网格方法。阶段三先审查了 OpenFOAM 原生 `tabulated6DoFMotion`：它能读取时间—平移/转动表，因此保留在 `motion_csv_to_openfoam.py` 作为兼容输出；但本项目需要每个耦合步由结构端发布未知运动，并让 CFD 对 `step/time/payload` 做确认，还要在旧标记、缺文件和非数值时立即停止。仅依赖预先加载的表不能完整表达这套握手，因此实现独立运行时库 `ancfFileMotion`，没有修改 `pimpleFoam` 主求解器。

## 2. 文件协议

运动端提交两个文件：

```text
coupling/motion.csv
coupling/motion_ready
```

CSV 沿用已有 `0.1.0` 协议，每个切片一行，字段包括位置、速度和加速度。CSV 完整写入临时文件并原子替换；随后 `motion_ready` 原子提交 JSON，绑定：

```text
kind, payload, step, time_s, coupling_iteration,
row_count, schema_version, sha256
```

CFD 在当前 OpenFOAM 时间 `t_n` 进入运动函数时计算期望步号，必须同时满足：

- marker 存在且 payload 文件存在；
- `step` 与 `startTime+n*couplingDeltaT` 一致；
- `time_s` 在严格容差内一致；
- 选定 `sliceId` 存在且全部运动量为有限数；
- 运动 CSV 的 schema、行和 slice 位置有效。

不接受旧 marker，不沿用上一个载荷或运动。Python 侧的 `protocol.py` 另外校验行数和 SHA-256；OpenFOAM 运行时库在 CFD 端再次校验 step/time、schema、slice 和有限性。

## 3. OpenFOAM 适配实现

文件位置：

- `src/openfoam/ancfFileMotion/ancfFileMotion.H`
- `src/openfoam/ancfFileMotion/ancfFileMotion.C`
- `src/openfoam/ancfFileMotion/Make/files`
- `src/openfoam/ancfFileMotion/Make/options`

运行时类型为 `solidBodyMotionFunction`，通过 `interpolatingSolidBody` 将选定切片的绝对位置相对于初始位置转换为网格刚体平移；当前只使用二维平移，旋转保持单位旋转。编译命令：

```bash
source /opt/openfoam10/etc/bashrc
wmake libso src/openfoam/ancfFileMotion
```

案例 `cases/openfoam/single_slice_ancf_fsi` 保留了任务二解析案例的同一网格、流体参数、圆柱力函数和时间步，仅把运动函数替换为 `ancfFileMotion`。

## 4. 已完成的在线验证

### 4.1 真实未知运动烟测

以 `t=0` 的静止 motion snapshot 启动，再由外部 producer 原子提交 `step=1, t=0.0025 s` 的运动。OpenFOAM 10 成功加载库、选择 `interpolatingSolidBody`、推进一个物理步，并写出 `forces.dat` 和 `forceCoeffs.dat`。结果保存在 `results/04_single_slice_weak_coupling/online_motion_smoke_summary.json`。

### 4.2 解析运动同轨迹对照

用同一网格和同一 CFD 参数，比较：

```text
y(t)=0.1 sin(1.00530964914873 t)
```

一条运行使用原生 `oscillatingLinearMotion`，另一条运行使用 `ancfFileMotion` 读取同轨迹 CSV。`t=0.0025 s` 的 `Cm/Cd/Cl/Cl(f)/Cl(r)` 最大绝对差为 `0`，最大相对差为 `0`（输出精度范围内完全一致）。这证明在线运动函数没有改变同轨迹下的网格运动和水动力结果。

### 4.3 失配即停

已单独触发并记录：旧 step marker、缺失 ready marker、CSV 载荷修改后摘要不一致、NaN/Inf 运动。Python 协议单元测试和 OpenFOAM 运行时烟测均确认不会回退到旧运动/旧载荷。

## 5. 当前限制

当前 adapter 是单切片刚体运动接口，不是多切片整根立管动网格。`tabulated6DoFMotion` 的表格转换工具保留用于回归和离线检查，但自由耦合路径使用 `ancfFileMotion`。连续多个耦合步、结构端在线预测/校正和动态网格长期质量审计仍需由 `OnePassWeakCoupling` 接入实际 ANCF/EB runner 后完成。
