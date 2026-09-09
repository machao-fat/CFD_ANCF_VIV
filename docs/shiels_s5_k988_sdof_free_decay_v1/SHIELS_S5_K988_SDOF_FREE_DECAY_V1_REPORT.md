# Shiels S5-K9.88 独立 SDOF 自由衰减验证 V1

## 结论

`SHIELS_S5_K9P88_SDOF_FREE_DECAY_V1 = PASS`。本次仅验证项目既有
`SDOFRunner` 对一个无阻尼、无外力的标量质量—弹簧系统的 Newmark 平均加速度
时间积分。它**不**是 50 m ANCF 立管验证，也不构成自由 FSI、涡激振动或三切片
耦合通过的结论。

本次只启动一个本机 Python SDOF 进程；未启动 C++ ANCF worker、MATLAB、WSL、
OpenFOAM、preCICE、CFD、自由 FSI 或三切片耦合。

## 独立文献合同

来源参数按任务指定的 Shiels et al. (2001) 第 7 页表 2 记录，而不是改写既有的
`m_d*=10, zeta=0.01, Ur=5.2` 项目诊断合同。定义为

\[
m^*=m'/(0.5\rho D^2),\qquad k^*=k'/(0.5\rho U^2).
\]

| 项目 | 冻结值 |
|---|---:|
| `Re`, `m*_Shiels`, `k*_Shiels`, `b*_Shiels` | 100, 5, 9.88, 0 |
| `D`, `U`, `rho`, `nu` | 1 m, 1 m/s, 1000 kg/m³, 0.01 m²/s |
| 单位展向 `Lz` | 1 m |
| `m'`, `k'`, `c'` | 2500 kg/m, 4940 N/m², 0 N·s/m² |
| 标量 `M`, `K`, `C` | 2500 kg, 4940 N/m, 0 N·s/m |
| 方程 | `M y¨ + C y˙ + K y = Fy`，且 `Fy=0` |
| 初值 | `y(0)=0.01 m`, `v(0)=0`, `a(0)=-0.01976 m/s²` |
| 无附加项 | 不含流体附加质量或排水质量 |
| 解析 `omega_n`, `fn`, `Tn` | 1.4057026713 rad/s, 0.2237245286 Hz, 4.4697825761 s |
| 计算 | `dt=0.005 s`，4470 步，`t_end=22.35 s`（约 5.00025 个 `Tn`） |

文献中的未来自由 FSI 指标 `A/D=0.57`、`fD/U=0.198`、`CL` 振幅 1.35 和平均
`CD=2.23` 仅保存在输入合同中；本次零外力自由衰减不以它们为目标。

## 被测实现与边界

实际被测的是既有 [sdof_runner.py](../../src/coupling/sdof/sdof_runner.py) 中的
`SDOFRunner`，其实现为 Newmark 平均加速度 `beta=0.25, gamma=0.5`。该实现原有的
质量比采用 `rho*pi*D²/4`，运行器仅在其公开输入边界进行等价换算：
`mass_ratio=2500/(1000*pi/4)`、`Ur=1/(fn*D)`，并在启动前断言所得 `M=2500` kg、
`K=4940` N/m、`C=0`。

现有 C++ 核心 [ancf_kernel.cpp](../../src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp)
已作只读审计。它是带 ANCF 几何、质量积分、非线性内部力与 slice force 映射的
多自由度梁；没有无改动地指定标量 `M/K/C` 的公开接口。将其强行调参并不能验证
任务指定的精确 SDOF 方程，故没有将它当作本次被测对象，也没有改动该核心。

解析参考仅为

\[
y=0.01\cos(\omega_n t),\quad
v=-0.01\omega_n\sin(\omega_n t),\quad
a=-0.01\omega_n^2\cos(\omega_n t).
\]

## 预声明判据

以下容差在数值循环前写入不可复用的 `contract.json`。平均加速度法对该线性无阻尼
系统保持离散能量，其主要解析偏差预期是二阶相位色散；未添加阻尼、未改动质量或刚度。

| 指标 | 判据 |
|---|---:|
| 位移、速度、加速度最大相对误差 | ≤ `1.5e-4` 各自满量程 |
| 零交叉频率相对误差 | ≤ `1.0e-5` |
| 五周期累计相位漂移 | ≤ `1.5e-4` rad |
| 最大相对机械能漂移 | ≤ `1.0e-10` |
| 非有限状态 | 不允许 |

## 一次受控运行结果

运行身份：`runtime/shiels_s5_k988_sdof_free_decay_v1_run_001`；运行时的 Git HEAD 是
`0872834888e5a07fb7d0cc07a4279599351ddff7`。`SDOFRunner` SHA256 为
`bb8726595ea10758042fe67c5e65216af538a999c6759b45792d2540c008775f`；本次运行器
SHA256 为 `6bc6a0809facb9f1966dc751719b7498713d10cdd6081f89d5521614ca5fac78`。
C++ ANCF 源码仅审计，SHA256 为
`1a3fc668b1e2800c12eec6aa0494e040266cd5f116805d6166288947938f5f03`。

| 度量 | 实测 | 判定 |
|---|---:|---|
| 最大 `|y-y_ref|` | `1.2293067926e-6 m` (`1.2293067926e-4` 相对) | PASS |
| 最大 `|v-v_ref|` | `1.8180527801e-6 m/s` (`1.2933409157e-4` 相对) | PASS |
| 最大 `|a-a_ref|` | `2.4291102222e-6 m/s²` (`1.2293067926e-4` 相对) | PASS |
| 零交叉频率 | `0.2237236076 Hz`；相对误差 `4.1167928142e-6` | PASS |
| 五周期相位漂移 | `+1.2933423017e-4 rad`（数值相位滞后） | PASS |
| 初始 / 最终机械能 | `0.24700000000000003 / 0.2470000000000005 J` | PASS |
| 最大相对能量漂移 | `6.8546158403e-15` | PASS |
| 终态 | `y=0.0099999902163 m`, `v=-1.9663421266e-5 m/s`, `a=-0.0197599806675 m/s²` | 有限 |

![解析解与数值解对照](../../runtime/shiels_s5_k988_sdof_free_decay_v1_run_001/free_decay_comparison.png)

完整数值轨迹与机器可读判据位于运行目录：`contract.json` SHA256
`bed72e32b90c524b0434bafa3284ee8e9df2562cf4044daed2774afd7ef9959f`，`metrics.json`
SHA256 `8d7aa3f1e2d809a487ddf9b1e28312af41b503dd60db6d3231c8a748145fe3a0`，
`trajectory.csv` SHA256 `3b9c172f1df55e67eddbffd11351906ca9a92cc4f2b5ba8b85fb4010e7ce1cd0`。

## 解释与后续边界

结果符合无阻尼线性振子采用 Newmark 平均加速度法的预期：能量在浮点舍入量级内守恒，
而五周期后出现很小的离散频率偏低/相位滞后。它验证的是项目既有 SDOF 积分实现的
指定参数合同，不会自动证明受约束 ANCF 广义 `M/C/K`、50 m 立管、流体力单位或任何
自由耦合稳定性。

历史 FAIL、`NOT_EVALUABLE` 和所有 CFD/耦合 runtime 均未修改。

```
NEXT_SINGLE_SLICE_SDOF_FREE_DECAY = COMPLETED_PASS
NEXT_SINGLE_SLICE_FREE_FSI = NOT_AUTHORIZED
NEXT_IMPLICIT_0P05S = NOT_AUTHORIZED
NEXT_LONG_VIV = NOT_AUTHORIZED
```
