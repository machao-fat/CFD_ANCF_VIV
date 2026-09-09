# Shiels S5-K9.88 独立单切片自由 FSI 首次有限接入 V1

## 状态

`SHIELS_S5_K9P88_SINGLE_SLICE_FREE_FSI_FIRST_TRIAL_V1 = FAIL_CLOSED`。

失败发生在受控 launcher 的 Bash 解析阶段，尚未创建任何 preCICE participant 或
`pimpleFoam` 子进程。因此它是**测试启动器序列化阻塞**，不是流体、动网格、回滚、
结构积分或耦合收敛的数值结论。依照“一次执行、失败即停止”合同，本轮没有修复后
重跑。

## 冻结合同与准备证据

新测试与先前 `m_d*=10, zeta=0.01, Ur=5.2` SDOF 诊断和 50 m ANCF 模型隔离。
其输入合同为 Shiels 表 2：`Re=100`、`m*=5`、`k*=9.88`、`b*=0`；`D=1 m`、
`U=1 m/s`、`rho=1000 kg/m³`、`nu=0.01 m²/s`、单位展向 `Lz=1 m`，且
`M=2500 kg`、`K=4940 N/m`、`C=0`。

真实初态从合法 OF 0.105 s 原生动态零运动重启复制，包含 `U/p/phi/Uf`、位移场、
`meshPhi`、points 和时间状态；没有使用人工相容 `Uf`。其字段 SHA256 已写入
`runtime/.../contract.json`。与真实 preCICE 零运动路径逐文件重新核对后相同。

初始横向流体总力来自同一 preCICE 零运动 case 的 `cylinderForces`：

| 分量 | 值 |
|---|---:|
| 压力 `Fy0` | `-47.2938883278 N` |
| 黏性 `Fy0` | `+1.328101890468 N` |
| 总 `Fy0`（1 m span） | `-45.965786437332 N` |
| 结构初始状态 | `y0=0`, `v0=0`, `a0=Fy0/M=-0.0183863145749328 m/s²` |

这避免了将 `SDOFRunner.initialize()` 的零载荷加速度错误地当作受流体力初态。

包装层仍调用既有 [sdof_runner.py](../../src/coupling/sdof/sdof_runner.py)；没有另写
被测积分器。parallel-implicit 合同冻结为 OF `0.105→0.155 s`、`dt=0.005 s`、
最多 10 个接受窗口、min/max iterations `2/8`、无加速。每个 trial 的物理 SDOF
状态（含上一接受力和能量累计）设计为 checkpoint/restore；preCICE transport identity
不恢复。

无 CFD 的新包装层单测已经通过：

| 检查 | 结果 |
|---|---|
| 零外力 Newmark 回归 | PASS，`|dy|=1.8703e-8 m` |
| 恒定力解析响应 | PASS，`|dy|=7.5719e-9 m` |
| A 试算 → restore → B 接受 | PASS，B 与直接 B 的最大状态差 `0` |
| 40 顶点二维 payload、1 m 力求和与时间层 | PASS |

独立 OF10 owner-diagnostic ABI 预检查亦通过：`pimpleFoam` SHA256
`c0add92c42e1e1e35100a5492eb398385af03bc68ba817a423efada8a01bfa43`，adapter SHA256
`c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17`；`ldd -r` 无
未解析符号，且未混入 `/opt/openfoam10`。

## 唯一执行与 first blocker

运行目录：`runtime/shiels_s5_k988_single_slice_free_fsi_first_trial_v1_run_001`。
该目录保存了不可变的 `contract.json`、`manifest.json`、`preflight.json` 和失败
`launch.sh`。Windows launcher 返回码为 `2`。

首个错误为：

```text
launch.sh: line 13: unexpected EOF while looking for matching `''
```

根因在测试 launcher 生成的第 5 行：它将 `PYTHONPATH` 生成为

```bash
export PYTHONPATH='<python_deps>':<repository_root>'
```

开头的单引号在 `python_deps` 后已关闭，但末尾又出现孤立单引号。Bash 在执行第 7 行
participant 和第 8 行 `pimpleFoam` 之前停止。因此以下证据确实**不存在**：

- `returns.txt`；
- `participant.stdout/stderr` 和 `structure/structure_summary.json`；
- `fluid.stdout/stderr`、preCICE socket 数据、CFD 时间目录与力/网格结果；
- 接受窗口、trial/restore 记录、Co、连续性、checkMesh 和能量交换记录。

不能将离线 wrapper PASS 或 ABI PASS 升级为自由 FSI 运行 PASS；也不能把这个 shell
错误改称为物理不稳定性。

## 本轮变更与边界

新增的测试专用文件为：

- [sdof_precice_participant.py](../../tools/shiels_s5_k988_single_slice_free_fsi_first_trial_v1/sdof_precice_participant.py)：既有 `SDOFRunner` 的 checkpoint-aware preCICE 包装层；
- [run_first_trial.py](../../tools/shiels_s5_k988_single_slice_free_fsi_first_trial_v1/run_first_trial.py)：独立 case、ABI preflight、一次性 launcher 和审计器。

没有修改 ANCF 核心、三切片力映射、OF10-owned restore、adapter、网格、物性、dt、
PIMPLE 或任何历史 runtime。当前 launcher 缺陷没有在本轮修补。

## 下一步

若人工再次授权，只应进行一次最小 launcher 引号修复审查、重新生成新的独立 runtime，
重新执行接口预检查，再授权一次新的 10 窗口运行；不得复用或覆盖本次失败目录。尚未
得到该授权前，不启动任何自由 FSI、三切片、0.05 s 或长时间 VIV 运行。

```text
NEXT_SINGLE_SLICE_SDOF_FREE_DECAY = COMPLETED_PASS
NEXT_SINGLE_SLICE_FREE_FSI = NOT_AUTHORIZED_PENDING_LAUNCHER_REVIEW
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```
