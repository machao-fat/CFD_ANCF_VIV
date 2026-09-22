# HH06 Nonzero ALE One-Window Qualification Report

## 最终状态

`PASS_HH06_NONZERO_ALE_ONE_WINDOW_QUALIFICATION`

这是 diagnostic-only 单窗口接口/ALE 资格验证，不是 HH06 production 物理结果。

## 运行合同

- Fluid：真实 OpenFOAM 10 `pimpleFoam` / `Fluid_0000`
- Structure：真实 HH06 `Structure_0000`
- worker：qualified SHM1 persistent worker
- worker SHA256：`69f045eb7f4576e5178d10711f0f265d7458282a7a4ecbcb860a913ada45beef`
- coupling：parallel-implicit
- `dt`：0.0002 s
- accepted windows：1/1
- coupling iterations：2，含 1 次真实 rollback
- diagnostic-only transverse offset：`1e-4 m`
- Fluid return code：0
- Structure return code：0

Structure 最终 accepted 记录中的 ANCF 位移为 `(1.2961887225e-7, -3.2123475881e-5, 4.1638714813e-4) m`；发送给二维 preCICE 的 x/y 位移在叠加 diagnostic-only y-offset 后为 `(1.2961887225e-7, 6.7876524119e-5) m`。偏置没有写入 ANCF `q/qdot/qddot`。

## Displacement 数据链

| 阶段 | 证据 |
|---|---|
| initial preCICE read | 200 个 Fluid vertices 均收到 `(0, 1e-4) m` |
| initial field application | `READ_DATA_FIELD_USER_APPLIED`，point/cell displacement hash 改变 |
| trial 1 ALE | max point motion `1.0000000000e-4 m`，max mesh velocity `0.5000000000 m/s` |
| retry preCICE read | relaxation 后 200 个 Fluid vertices 均收到 `(0, 2e-5) m` |
| retry field application | 第二次 `READ_DATA_FIELD_USER_APPLIED`，point/cell displacement hash 再次改变 |
| retry ALE | max point motion `2.0000000000e-5 m`，max mesh velocity `0.1000000000 m/s` |

`Adapter::readCouplingData()` 实际调用 2 次；`Interface::readCouplingData()`、preCICE return 和 `FSI::Displacement::read()` field application 各有 2 次 trace。

## Rollback 审计

checkpoint 与 `CHECKPOINT_READ_AFTER_RESTORE` 的 canonical hashes：

| 状态 | 结果 |
|---|---|
| U | exact |
| p | exact |
| k | exact |
| omega | exact |
| nut | exact |
| phi | exact |
| pointDisplacement | exact |
| cellDisplacement | exact |
| points | exact |
| oldPoints | exact |
| cellVolume | exact |
| faceArea | exact |

首窗口 checkpoint 时 OpenFOAM 尚未执行第一次 mesh motion，`meshPhi` 尚未注册。rollback 后它已由 OpenFOAM 创建，因此不能与“不存在的 field”做字节 hash 比较；修复将其恢复为 checkpoint 的物理等价零值：

- rollback 后 max mesh velocity：0
- rollback 后 mesh Courant：0
- rollback 后 `points == oldPoints`
- retry 前不存在 rejected-trial mesh flux

因此 mesh rollback 按物理状态闭合；attempt 1 中错误的 rollback 后 `0.5 m/s` 虚假 mesh velocity 与 `meshCo=1.6214` 已消失。

## ALE 和网格质量

| 指标 | checkpoint | trial 1 | retry trial |
|---|---:|---:|---:|
| max point motion (m) | 0 | 1.0000000e-4 | 2.0000000e-5 |
| max mesh velocity (m/s) | 0 | 0.5000000 | 0.1000000 |
| mesh Courant max | N/A，field 尚未注册 | 1.6214322762 | 0.3242864551 |
| minimum cell volume (m3) | 7.6873649820e-10 | 7.6873649795e-10 | 7.6873649818e-10 |
| maximum non-orthogonality (deg) | 44.0048641 | 44.0132030 | 44.0055622 |
| maximum skewness | 0.219115313 | 0.219118589 | 0.219115963 |

所有体积均为正。`points`、cell volume、face area 和 `meshPhi` hashes 在两次真实 ALE 中均改变，证明不是 fixed-mesh 假通过。

## Fluid 数值健康

- OpenFOAM reported Courant：mean `0.01601199855`，max `0.4182184878`
- max absolute local continuity error：`7.467839243e-7`
- max absolute global continuity error：`1.689503433e-7`
- observed max `|U|`：trial 1 `0.835073678 m/s`；retry `0.601034632 m/s`
- minimum k：`2.701992533e-10`，保持正值
- omega range：`1.98346` 到 `93792.84755`，有限且未爆炸
- nut range：`2.88081e-15` 到 `2.80317e-4`，有限且非负
- NaN/Inf：0
- FPE crash：0（日志中的 `sigFpe : Enabling...` 只是 OpenFOAM 启用保护，不是异常）
- negative volume：0
- checkpoint error：0
- duplicate worker ID：0
- OpenFOAM/preCICE/participant fatal：0

## PASS 条件逐项

1. Adapter read 调用次数 > 0：PASS（2）
2. `FSI::Displacement::read()` 执行：PASS（2）
3. 收到非零 Displacement：PASS
4. point/cell displacement 非零：PASS
5. points hash 改变：PASS
6. mesh velocity > 0：PASS
7. mesh Courant > 0：PASS
8. meshPhi 随 ALE 更新：PASS
9. rollback 恢复物理场和几何状态：PASS
10. retry 新输入再次驱动 ALE：PASS
11. 无 NaN/Inf/FPE/negative-volume/checkpoint/duplicate-ID：PASS

## 输出与边界

原始 attempt 1 证据位于 `artifacts/attempt1/`；最终 attempt 2 原始日志位于本目录根部。原始生产 case 没有被运行或写入，隔离 case 也没有新增 OpenFOAM 数值时间目录。

本轮到此停止。没有自动进入 50-window、0.2 s FSI 或多切片。

