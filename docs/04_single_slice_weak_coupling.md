# 单切片一遍式 Dirichlet–Neumann 弱耦合

## 1. 时间步顺序

每个交换步 `n -> n+1` 的约定为：

1. 结构端已有 `q_n, v_n, a_n` 以及上一时刻载荷；
2. ANCF 或 EB 端根据上一时刻状态生成 `t_{n+1}` 预测运动；
3. 运动 CSV 完整写入并原子提交 `motion_ready`；
4. OpenFOAM 读取并确认 step/time，使用预测运动移动网格，从 `t_n` 推进到 `t_{n+1}`；
5. 对圆柱壁积分压力力和黏性力，并转换成共享的单切片代表总力；
6. 完整写入载荷 CSV，校验后原子提交 `load_ready`；
7. 结构端严格检查载荷 step/time/摘要，然后用 `F_{n+1}` 做一次校正；
8. 不进行内迭代，记录预测—校正位移、速度、力变化和 `F·v`。

Python 侧的 `src/coupling/online_file_coupling/weak_coupling.py` 提供上述顺序的注入式 orchestration：运动构造器负责调用 ANCF 或 EB，CFD runner 只在载荷 ready 后返回，结构校正器接收已验证的单切片载荷。这样不会在协议层复制结构力学，也能保证两个结构分支使用同一 CFD 交换语义。

## 2. 量和单位

`slice_loads.csv` 中的力是已经积分的 `N`，不是 `N/m`。`H^T` 负责从代表切片总力到结构广义力的守恒传递；不能再用“切片力乘长度后均布”的替代。瞬时功率为：

```text
P(t) = F_x v_x + F_y v_y + F_z v_z
```

后续长时间结果还必须提供周期累计流体功、结构动能、EB 弯曲能、ANCF 轴向应变能、阻尼耗散、压力/黏性力分量、CFL、网格质量和重启点。

## 3. 已实现的握手和审计字段

已实现：

- `publish_ready`：验证完整 CSV，计算 SHA-256，原子写 JSON marker；
- `read_ready_snapshot` / `wait_for_ready`：检查 marker、step/time、行数、文件摘要，拒绝旧或被修改的 payload；
- `OnePassWeakCoupling.exchange_step`：固定预测—CFD—载荷—校正顺序；
- `WeakCouplingStep`：记录总力、预测位移残差、预测速度残差、力变化和瞬时功率。

测试 `tests/online_motion_adapter/test_weak_coupling_driver.py` 已验证事件顺序和审计量计算。OpenFOAM 真实单步运行已验证运动文件可以驱动网格并输出压力/黏性力。

## 4. 当前完成度和未通过项

当前已完成的是“协议真实执行 + OpenFOAM 单步在线运动烟测 + 解析同轨迹一致性”。尚未把 MATLAB ANCF 与 EB 校正器作为两个连续运行的结构进程接到同一 CFD runner，因此：

- 尚未给出连续自由 VIV 的振幅/频率/相位/功率结论；
- 尚未给出弱耦合长期稳定性结论；
- 尚未进入多切片或整根立管验证；
- 尚未在此阶段宣称自由 VIV 已满足锁定趋势验收。

若接入后出现无界振幅、无来源能量增长、网格质量恶化或预测—校正残差持续增大，应先减小交换步长、加固定松弛或切换 Aitken 强耦合，不得把数值失稳解释为 VIV 物理。

## 5. 流场启动条件

固定结构基准已由阶段二报告提供，当前单步 smoke 不承担脱涡统计启动。真正自由耦合前需先固定结构运行至可量化启动条件，例如 `Cd` 滑动平均变化低于预设阈值、`Cl` 振幅和主频在连续若干脱涡周期内稳定，然后才允许结构运动预测开始。启动阈值、窗口和持续时间必须写入结果元数据，不能用固定“5 个时间步”替代。
