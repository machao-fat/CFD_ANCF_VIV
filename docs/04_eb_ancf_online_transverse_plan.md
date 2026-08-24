# 阶段三 EB/ANCF 最小在线横流向 A/B 方案

## 当前状态

两个独立 OpenFOAM 案例已经准备并完成只读审计，但没有启动求解器：

- `cases/openfoam/single_slice_eb_transverse150_prepared`
- `cases/openfoam/single_slice_ancf_transverse150_prepared`

权威审计结果为：

- mesh SHA256：`f56123fa3f8161ba622dab02c34c3afc168f9f1164cbe34f38b84510fb6aa51b`
- 初始 `U` SHA256：`6b9a2673d672befe4ba4aaee7affbd5a89cf446e568aea96eef71aac63a08a41`
- 初始 `p` SHA256：`b1fcf1aa37f6a374ff24a4764fed54afd06659f419ba73726e0f2ead4eb6267f`
- `dynamicMeshDict` SHA256：`456782c93690e9224e3f8959ea8efbeaa42b0d561e11ff2fd17b494e37ad0b95`
- `system` 目录 SHA256：`bfd49e1c645cc8e665bf4ef8f0a7506c0915a9e5f5e03c1a84c5ec589d6f66e0`

EB和ANCF上述五项完全相同。审计JSON位于 `results/04_eb_ancf_physical_comparison/online_transverse_case_audit.json`。

## 共同初始流场

共同源为：

```text
cases/openfoam/fixed_cylinder_study_full30b/medium_dt0p0025，time=30 s
```

源场哈希：

- `U`：`c27297e71b4ebe9ed20debaa9764143dd268bbc67fff130c4b469f59101ed6a9`
- `p`：`f8ac7e58109363a58d4670e16e8dee80e8f0b45954f958038a36b9fc0e4b9413`

复制到目标 `0/` 后只进行了两类必要修改：

1. field header 的 `location` 从 `30` 改为 `0`；
2. `U` 的 cylinder patch 从固定圆柱的 `noSlip` 改回动态ALE所需的：

```text
type  movingWallVelocity;
value uniform (0 0 0);
```

EB和ANCF的 `U/p internalField` 均与源30 s场逐字节哈希一致。旧 SDOF developed/long 案例曾错误保留 `noSlip`，因此旧长算例不能作为有效运动圆柱证据；后续重跑必须采用同样的移动壁修复。

## 结构与耦合配置

| 项目 | 统一数值 |
|---|---:|
| `L/D` | 150/1 |
| 内径 | 0.9 m |
| `E` | 207 GPa |
| 顶张力 | 1.0 MN |
| 单元/切片 | 10/1 |
| `s_ref` | 75 m |
| 重力/浮力 | 两分支均关闭 |
| Rayleigh `alpha/beta` | 0.0194776 1/s / 0 s |
| 一阶目标阻尼比 | 1% |
| CFD和结构时间步 | 0.0025 s |
| 载荷模式 | `transverse_only` |
| 实际结构载荷 | `[0,Fy,0]` |

离线同载荷对照的一阶频率约为 `0.155 Hz`，因此 `dt=0.0025 s` 每周期约2580步，时间离散足够细。在线初始wake本身不对称，不额外伪造横向载荷或位移种子。

## CFD力的单位和物理含义

OpenFOAM求解运动学压力，force function object 使用 `rhoInf=1000 kg/m³` 把压力/黏性积分转换为牛顿。二维网格采用 `1 m` span，因此CSV中的 `force_x_N/force_y_N` 是每个一米厚切片的积分力，协议字段为：

```text
force_representation = integrated_N
unit_span_m = 1
slice_length_m = 1
```

该力作为位于结构 `s=75 m` 的一个一米切片积分载荷进入 `H^T`，不能再乘一次密度、span或切片长度。原始 `Fx/Fy/Fz` 全部保留在审计中，但结构只接收 `Fy`。

## 执行前阻塞项

当前 publisher 仍把 load CSV 的 `s_ref_m` 固定为0。已准备的启动器会主动拒绝启动，直到完成 [s_ref协议修复提案](04_s_ref_protocol_patch_proposal.md)。修复后必须先跑完整Python协议测试。

## 严格顺序

1. 合并并验证 `s_ref_m` 协议修复；
2. 重新运行 `audit_online_transverse_cases.py`，要求全部检查为true；
3. 只运行EB的100步烟测；
4. 审核EB，不合格则停止，不运行ANCF；
5. 从未被修改的ANCF案例运行100步烟测；
6. 比较两个烟测；
7. 两者均通过后，从同一30 s源场重新生成一对全新长算例，不能把已经运行过的烟测目录直接作为正式A/B初场；
8. 长算例仍严格串行，避免与SDOF争抢WSL资源。

烟测启动入口为：

```powershell
python tests\structure_runners\run_prepared_transverse_smoke.py --branch eb
python tests\structure_runners\run_prepared_transverse_smoke.py --branch ancf
```

在协议未修复时，上述命令应以 `REFUSING TO RUN` 退出，这属于预期保护行为。

## 100步烟测验收清单

- [ ] 初始 mesh/U/p 哈希与审计JSON一致；
- [ ] cylinder `U` patch 为 `movingWallVelocity`，不存在 `noSlip`；
- [ ] motion和load的 `s_ref_m` 均为75 m；
- [ ] CFD、运动库和结构步长均为0.0025 s；
- [ ] 完成step 1–100，无缺步、旧marker或超时；
- [ ] 原始CFD力与实际施加结构力分列保存；
- [ ] 每一步 `applied_force_x_N=applied_force_z_N=0`；
- [ ] `applied_force_y_N=force_y_N`；
- [ ] `x/vx/ax` 保持数值零，建议绝对值小于 `1e-14`；
- [ ] 无NaN/Inf、SIGFPE或Newton不收敛；
- [ ] 最大CFL建议小于0.5，超过1立即停止；
- [ ] predictor/corrector、能量、张力和残差字段均有限；
- [ ] 最终时刻网格无负体积；
- [ ] EB通过后才允许运行ANCF。

## 正式在线A/B验收

烟测只验证启动与稳定性。正式物理比较至少应覆盖2–3个一阶结构周期，推荐沿用离线40 s窗口；若计算资源有限，可先做10 s趋势检查，再决定是否延长。

正式A/B要求：

- 峰值横向位移至少大于 `1e-5 m`，否则仍属于接口尺度；
- 最大位移建议保持在 `0.05D` 内，先完成小变形一致性验证；
- EB/ANCF位移RMS和主频差异小于5%；
- 两次独立在线CFD的 `Fy`、相位和平均功率分别报告，不能称为“同一Fy”；
- 若要证明严格同一Fy，只能引用已经通过的离线回放；
- 两个案例必须使用相同统计窗口和初始场哈希；
- 结果只支持“单切片在线结构分支比较”，不支持整根立管或多切片VIV结论。

当前网格域约为上游5D、下游10D、上下各5D，适合本轮最小诊断，但不能替代最终论文所需的计算域敏感性检查。

