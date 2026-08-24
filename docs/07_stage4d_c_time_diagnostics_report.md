# Stage 4D-C-A-v2 时间语义、Newmark色散与载荷回放诊断报告

## 1. 结论边界

本报告完成离线诊断，不重新验收 Stage 4D-C-A，也不启动新的真实 OpenFOAM campaign。诊断只使用：

- Stage 4D-B 粗步真实运行；
- Stage 4D-C 已有的 `dt=0.00125 s, nElem=2` 细步真实运行；
- 既有 ANCF MATLAB 核心的独立载荷回放；
- 无阻尼 Newmark 平均加速度法的解析交叉验证。

本任务未调用 `pimpleFoam`、`checkMesh` 或 `setFields`，未修改正式 ANCF 核心、persistent worker、OpenFOAM case 或既有 Stage 4D 证据。Stage 4D-C-A 是否继续、采用何种真实 CFD 时间步或初始化路线，保留给 Sol 主Agent。

## 2. 身份和输入复核

| 项目 | 值 |
|---|---|
| 协议 | `0.2.1` |
| 三切片 manifest SHA-256 | `d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3` |
| 粗步 | `0.0025 s`, 100步, 0.25 s |
| 细步 | `0.00125 s`, 200步, 0.25 s |
| 结构主频 | 约 28 Hz |
| 线性第一频率 | `27.50934575579332 Hz` |
| 阻尼 | `rayleigh_alpha=0`, `rayleigh_beta=0` |
| worker静态载荷 | 初始化时为零；预载路线仅在独立 MATLAB 回放中使用 |

Sol review 已确认原始粗细步状态时间标签没有固定半步或整步错误。

## 3. 状态时间语义审计

worker 响应的语义为：初始化状态是 `t_0=0`、`step=global_step=-1`；对全局步 `k`，`predict` 和 `correct` 返回目标时间 `t_{k+1}` 的 staged 状态，同时 `step=global_step=k-1`、`staged_step=k`；原子提交后的 `finalize_commit` 返回 committed 状态，`step=global_step=k`、`staged_step=-1`、`time_s=t_{k+1}`。

| run | action counts | q运动学最大残差 | qdot运动学最大残差 | checkpoint与correct q |
|---|---|---:|---:|---:|
| 粗步 `dt=0.0025` | initialize 1, predict 100, correct 100, save 200, finalize 100, get_state 300 | `3.3881317890172014e-21` m | `8.131516293641283e-19` m/s | `0` |
| 细步 `dt=0.00125` | initialize 1, predict 200, correct 200, save 400, finalize 200, get_state 600 | `5.082197683525802e-21` m | `9.215718466126788e-19` m/s | `0` |

两组运行的运动学关系均满足数值精度：

\[
q_{n+1}-q_n=\frac{\Delta t}{2}(\dot q_n+\dot q_{n+1}),
\quad
\dot q_{n+1}-\dot q_n=\frac{\Delta t}{2}(\ddot q_n+\ddot q_{n+1}).
\]

最大响应 RMS 运动学残差分别为：粗步 `4.348123022732958e-22` m、`7.48149835382732e-20` m/s；细步 `4.328745342771151e-22` m、`6.504376952838757e-20` m/s。重复 command id 为零，所有审计状态有限。`save_checkpoint`、`finalize_commit` 和 committed `get_state` 的 q 最大差均为 0。结论：本次粗细步差异不是由已审计的半步/整步状态标签错误造成。

## 4. 动态度量重算

完整 q 的 NRMSE `6.770210797600959e-7` 不作为动态收敛指标。回放和既有状态均先减去 `ancf_initialize` 返回的静力构型，再用 `ancf_constraints` 自动识别自由自由度。自由自由度为 13 个，未硬编码为 Gate 证据。

| 指标 | 粗细步未时移结果 |
|---|---:|
| 动态自由 q NRMSE | `0.21381745482039785` |
| 横向位置动态 NRMSE | `0.21371380527698353` |
| 横向斜率动态 NRMSE | `0.21433742837922934` |
| 动态 qdot NRMSE | `0.382180493965994` |
| 动态 qddot NRMSE | `0.8328240785036045` |
| 质量加权误差 `e_M` | `0.2137350255480487` |
| 前三阶模态位移 NRMSE | `0.21366482739039624` |
| 前三阶模态速度 NRMSE | `0.3701001814048047` |
| 前三阶模态加速度 NRMSE | `0.4288458445227603` |

三个切片中心的动态位移 NRMSE 为 `0.2167541`、`0.2137138`、`0.2109427`；速度 NRMSE 为 `0.3934004`、`0.3684346`、`0.3939430`。这些均为未进行时间移动的结果。

互相关最佳时移仅作为诊断：三个切片均得到约 `-0.0025 s` 的搜索边界候选，NRMSE 分别为 `0.71264`、`0.21419`、`0.66174`；未用于任何推荐或Gate判断。

## 5. Newmark 数值色散

使用

\[
\tilde\omega=\frac{2}{\Delta t}\tan^{-1}\left(\frac{\omega\Delta t}{2}\right)
\]

进行无阻尼单自由度解析审计。第一模态结果如下：

| dt (s) | 每周期步数 | 数值频率 (Hz) | 频率比 | 0.25 s相位误差 (rad) | 位移 NRMSE |
|---:|---:|---:|---:|---:|---:|
| 0.0025 | 14.5405 | 27.0928945 | 0.9848615 | -0.6541602 | 0.3820977 |
| 0.00125 | 29.0810 | 27.4030752 | 0.9961369 | -0.1669294 | 0.0985238 |
| 0.000625 | 58.1621 | 27.4826391 | 0.9990292 | -0.0419508 | 0.0247757 |
| 0.0003125 | 116.3241 | 27.5026603 | 0.9997570 | -0.0105014 | 0.0062027 |

第一模态相邻误差阶约为 `1.96`、`1.99`、`2.00`，符合平均加速度法的二阶相位误差量级。第二个给定频率 `109.26854598696481 Hz` 在粗步时每周期仅 `3.6607` 步，数值频率降为 `90.3021 Hz`，相位误差为 `-29.7923 rad`；即使 `dt=0.0003125 s`，0.25 s 相位误差仍为 `-0.6539 rad`。这说明高频结构分量会显著放大粗步与细步的未时移差异。

## 6. 结构载荷回放

回放载荷来自细步真实运行的 `integrated_slice_forces_N`，来源 run 为：

`stage4d_c_time_dt00125_nelem2_20260811T063528Z_b309b67168`

来源 `convergence_run_summary.json` SHA-256 为 `4ec87bfead80e93525528dabd6cb43b89e77d803d540ef12d8ac1d97a192b396`。共 200 个原始细步采样，回放输入另加 `t=0` 的初始积分力，共 201 个时间点。原采样点严格保持原值，新增点采用分段线性插值；无滤波、无平滑、无时间相位平移。

### 6.1 release 路线

release 路线保持零静态水动力预载，以完整回放积分力作为动态外载。推荐诊断阈值为位移 NRMSE、切片速度 NRMSE、主要模态速度 NRMSE、主要模态加速度 NRMSE、位移峰值变化和速度 RMS 变化分别不超过 `5%`、`5%`、`5%`、`10%`、`5%`、`5%`。

| 相邻对 | 位移 NRMSE | 切片速度 NRMSE | 模态速度 NRMSE | 模态加速度 NRMSE | 结果 |
|---|---:|---:|---:|---:|---|
| 0.0025 / 0.00125 | 0.09792 | 0.17777 | 0.16787 | 0.18103 | 不满足 |
| 0.00125 / 0.000625 | 0.02226 | 0.07168 | 0.03728 | 0.04555 | 不满足 |
| 0.000625 / 0.0003125 | 0.00874 | 0.07126 | 0.01405 | 0.01830 | 不满足 |

第二、第三对的位移和主要模态指标已下降，但切片速度 NRMSE 仍超过 5%；因此 `recommended_release_real_dt_pair = none`。

### 6.2 preload 路线

preload 路线只在离线 MATLAB 中将初始三切片积分力作为 `static.external_slice_force_N`，再以 `F(t)-F(0)` 作为增量载荷。没有把完整 `F(t)` 与 base load 重复施加，也没有接入正式 persistent worker。

| 相邻对 | 位移 NRMSE | 切片速度 NRMSE | 模态速度 NRMSE | 模态加速度 NRMSE | 结果 |
|---|---:|---:|---:|---:|---|
| 0.0025 / 0.00125 | 0.04840 | 3.42833 | 1.02857 | 1.03245 | 不满足 |
| 0.00125 / 0.000625 | 0.00367 | 0.54687 | 0.07085 | 0.32963 | 不满足 |
| 0.000625 / 0.0003125 | 0.00337 | 0.60747 | 0.04438 | 0.16494 | 不满足 |

preload 路线的位移 NRMSE 较低，但速度和加速度仍不满足推荐阈值，且其结构参考构型已经改变。因此 `recommended_preload_real_dt_pair = none`。

## 7. 阻尼边界

本诊断没有加入任何阻尼。当前零阻尼会保留高频启动振铃和相位误差，不能通过任意 Rayleigh 系数人为改善时间步指标。若后续有实验或文献给出目标阻尼比 `ζ_a, ζ_b` 及两个目标圆频率 `ω_a,ω_b`，才可按

\[
\begin{bmatrix}1/\omega_a&\omega_a\\1/\omega_b&\omega_b\end{bmatrix}
\begin{bmatrix}\alpha\\\beta\end{bmatrix}
=2\begin{bmatrix}\zeta_a\\\zeta_b\end{bmatrix}
\]

反算 Rayleigh 系数。阻尼会同时改变启动瞬态、相位、平均构型附近响应、功输入和高频模态幅值，必须由 Sol 单独批准并建立新物理基准。

## 8. 自动化验证

- `python -m compileall -q src tests`：通过。
- `python -m unittest discover -s tests/stage4d_time_diagnostics -p "test*.py"`：7/7 通过。
- `python -m unittest discover -s tests -p "test*.py"`：247/247 通过，0 失败，运行约 77.7 s。

诊断期间曾出现 5 项 MATLAB 回放启动参数/输入结构错误（诊断路径未加入、输入缺少嵌套 force、N×9 载荷形状、缺少 dt 列表及 mass_matrix 字段路径）；均在正式回放成功前修正，未产生 OpenFOAM 运行，也未修改只读核心。建议 Sol 复核这些 transient 日志以及最终 `ancf_replay_raw.json`。

## 9. 推荐输出

本次离线诊断不产生可直接进入真实 CFD 的相邻时间步对：

- `recommended_release_real_dt_pair = none`
- `recommended_preload_real_dt_pair = none`

诊断支持的原因判断是：状态时间语义和 Newmark 运动学实现一致；粗细步差异与 27.5 Hz 主模态的二阶数值相位色散、以及更高频分量的严重色散相符。下一步应由 Sol 在“更细真实 CFD release 路线”和“先正式设计 preload 接口并重建基准”之间作出选择。
