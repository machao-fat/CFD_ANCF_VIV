# 数学模型：二维 CFD 切片、ANCF、线性梁与守恒耦合

## 1. 坐标与建模层次

采用固定右手全局坐标系：未变形立管参考中心线沿 `z` 轴由底端指向顶端；来流方向为 `x`（in-line, IL）；`y` 为 cross-flow (CF)，满足 `e_x × e_y = e_z`。参考弧长为 `s in [0,L]`。

主线把整根立管替换为位于参考位置 `s_i` 的 `N_cfd` 个独立二维切片。每个切片在固定全局 `x-y` 平面内计算圆柱绕流，只接受圆心的 IL/CF 平移和速度。ANCF 内部仍保留三维中心线和轴向伸长，以产生构型相关内力和张力；二维 CFD 不直接解析轴向流动或切片旋转。

这种固定切片假设适用于直立、共线来流且局部斜率尚未大到破坏二维截面近似的工况。若 `max |dr_perp/ds|` 过大，ANCF 结构结果仍可计算，但二维流场近似本身成为主误差源，结果应标记为“模型外推”，而不是宣称获得真实三维水动力。

## 2. 二维不可压缩流体模型

### 2.1 ALE/动网格形式

对切片 `i` 的流体域 `Omega_f^i(t)`，采用不可压缩 Navier–Stokes 或 URANS：

$$
\nabla\cdot\mathbf{u}=0,
$$

$$
\rho_f\left[
\frac{\partial\mathbf{u}}{\partial t}\bigg|_{\boldsymbol\chi}
+(\mathbf{u}-\mathbf{w}_m)\cdot\nabla\mathbf{u}
\right]
=-\nabla p+\nabla\cdot\left[2\mu_{\mathrm{eff}}\mathbf{D}(\mathbf{u})\right],
$$

其中

$$
\mathbf{D}(\mathbf{u})=\frac12(\nabla\mathbf{u}+\nabla\mathbf{u}^{T}),
\qquad
\mu_{\mathrm{eff}}=\mu+\mu_t.
$$

`w_m` 是流体网格速度；层流验证时 `mu_t=0`，生产算例可采用 SST `k-omega` 的 URANS 闭合。OpenFOAM 的 PIMPLE 用于压力—速度耦合。二维切片可用单层挤出网格和 `empty`/等效二维边界；所有从 OpenFOAM 得到的总力必须除以实际挤出厚度 `b_i`，转为单位轴向长度的线载荷。

### 2.2 圆柱运动边界

切片圆心为

$$
\mathbf{x}_{c,i}(t)=
\begin{bmatrix}x_i(t)&y_i(t)\end{bmatrix}^{T},
$$

圆柱边界 `Gamma_c^i(t)` 上满足无滑移：

$$
\mathbf{u}(\mathbf{x},t)=\dot{\mathbf{x}}_{c,i}(t)
+\omega_{c,i}\,\mathbf{e}_z\times(\mathbf{x}-\mathbf{x}_{c,i}).
$$

主线设置 `omega_c,i = 0`。对于圆截面，中心转角不改变几何；如果未来需要非圆截面或扭转水动力，必须扩展接口，不能把转角隐含在平移中。

入口采用 `u=U_i e_x`，其中 `U_i=U(s_i)`；出口给定参考压力并对速度使用合适的出流条件；侧边界应通过域尺寸敏感性验证。阶梯流中，下部暴露段的切片使用相同非零 `U_i`，静水段可不设置 CFD 切片，或设置 `U_i=0` 的切片用于捕捉由结构运动诱导的流体力；两种处理必须做敏感性比较。

### 2.3 壁面合力

流体对结构的二维单位长度合力定义为

$$
\boldsymbol\ell_i(t)=
\frac{1}{b_i}
\int_{\Gamma_c^i(t)}
\boldsymbol\sigma_f\mathbf{n}_{f\rightarrow s}\,d\Gamma,
\qquad
\boldsymbol\sigma_f=-p\mathbf{I}+2\mu_{\mathrm{eff}}\mathbf{D}(\mathbf{u}),
$$

其中 `n_{f->s}` 的定义使 `ell_i` 为流体作用在结构上的力。OpenFOAM `forces` 的原始符号必须用静止圆柱正阻力算例核对，符号只允许在 CFD 适配器中翻转一次。

沿轴向求积后，切片的共轭集中力为

$$
\mathbf{f}_i(t)=w_i\,\mathbf{R}_{xy}^{T}\boldsymbol\ell_i(t),
$$

`w_i` 是轴向求积长度，`R_xy` 把全局三维向量投影到/恢复自切片 IL/CF 分量。端点使用半权或由 Voronoi/高斯求积区间确定，不允许仅凭切片数隐含权重。

## 3. ANCF 结构模型

### 3.1 元素运动学

主线优先采用三维、梯度亏缺的 ANCF Euler–Bernoulli 型梁/缆索单元。最终自由度排列必须在检查课题组程序后冻结。一个常用的两节点形式为

$$
\mathbf{q}_e=
\begin{bmatrix}
\mathbf{r}_1^T & \mathbf{r}_{1,s}^T &
\mathbf{r}_2^T & \mathbf{r}_{2,s}^T
\end{bmatrix}^{T},
\qquad
\mathbf{r}(s,t)=\mathbf{S}(s)\mathbf{q}_e(t),
$$

其中 `r_a` 是节点绝对位置，`r_a,s` 是节点中心线斜率，均在全局坐标系中表达。该线性插值关系使切片运动算子可以直接由形函数构造；几何非线性来自应变和曲率，而不是来自 `r=S q` 本身。[Shabana（1997）](https://doi.org/10.1023/A:1009740800463)和 [Shabana、Yakoub（2001）](https://doi.org/10.1115/1.1410100)给出 ANCF 基础与三维梁理论。

### 3.2 质量、应变能和内力

忽略截面转动惯量或按所选单元一致加入后，典型一致质量矩阵为

$$
\mathbf{M}_e=\int_{0}^{L_e}\rho_s A\,\mathbf{S}^{T}\mathbf{S}\,ds,
$$

在常密度和固定参考域下为常矩阵。

以 Green–Lagrange 轴向应变和中心线曲率为例：

$$
\varepsilon=\frac12\left(\mathbf{r}_{,s}^{T}\mathbf{r}_{,s}-1\right),
$$

$$
\kappa=
\frac{\|\mathbf{r}_{,s}\times\mathbf{r}_{,ss}\|}
{\|\mathbf{r}_{,s}\|^3}.
$$

对各向同性细长梁，简化应变能可写为

$$
U_e(\mathbf{q}_e)=
\frac12\int_0^{L_e}
\left(EA\varepsilon^2+EI\kappa^2\right)ds.
$$

广义内力及切线刚度为

$$
\mathbf{Q}_{\mathrm{int},e}=\frac{\partial U_e}{\partial\mathbf{q}_e},
\qquad
\mathbf{K}_{T,e}=\frac{\partial\mathbf{Q}_{\mathrm{int},e}}
{\partial\mathbf{q}_e}.
$$

若课题组程序采用 Biot 应变、Timoshenko/连续体梁、曲率约束插值或其他锁定缓解形式，应以程序实际公式替换本节，并通过单元测试说明差异。[Zhang 等（2021）](https://doi.org/10.1016/j.apm.2021.09.027)讨论了 ANCF 缆索曲率和计算效率；[Obrezkov 等（2022）](https://doi.org/10.1007/s11071-022-07518-z)说明锁定处理是实现层面的必要检查。

### 3.3 系统方程

装配后结构方程为

$$
\mathbf{M}\ddot{\mathbf{q}}
+\mathbf{C}(\mathbf{q},\dot{\mathbf{q}})\dot{\mathbf{q}}
+\mathbf{Q}_{\mathrm{int}}(\mathbf{q})
+\mathbf{G}^{T}(\mathbf{q})\boldsymbol\lambda
=\mathbf{Q}_{h}(t)+\mathbf{Q}_{g}+\mathbf{Q}_{b},
$$

$$
\boldsymbol\Phi(\mathbf{q},t)=\mathbf{0}.
$$

`Phi` 为边界/运动学约束，`lambda` 为拉格朗日乘子；也可通过自由度消元施加边界。`Q_h` 为水动力广义载荷，`Q_g` 为重力/浮力，`Q_b` 为端部张力或端部装置载荷。阻尼模型必须与线性梁对照保持等效，优先用可解释的结构阻尼比标定，而不是任意 Rayleigh 系数。

可从轴向应变或截面力恢复瞬时轴力 `T(s,t)`。至少输出 `mean(T)`、`std(T)` 和 `min(T)`；若出现 `T_min <= 0`，应检查梁单元是否允许压缩/屈曲，以及二维切片假设是否仍适用。

## 4. 线性 Euler–Bernoulli 梁对照

对 IL 或 CF 位移 `w(s,t)`，小斜率、预设轴力形式为

$$
m(s)\ddot w+c(s)\dot w
+\frac{\partial^2}{\partial s^2}
\left(EI(s)\frac{\partial^2 w}{\partial s^2}\right)
-\frac{\partial}{\partial s}
\left(T_0(s)\frac{\partial w}{\partial s}\right)
=f_h(s,t).
$$

离散后为

$$
\mathbf{M}_L\ddot{\mathbf{d}}
+\mathbf{C}_L\dot{\mathbf{d}}
+\left[\mathbf{K}_b+\mathbf{K}_g(T_0)\right]\mathbf{d}
=\mathbf{F}_h.
$$

`T_0(s)` 可以是常数或由静力平衡给出的空间分布，但在基线模型中不随振动构型和时间更新；IL 与 CF 在线性层面可独立求解。线性梁的 Euler–Bernoulli 截面假设与“几何线性”是两件事：本课题对照项特指小斜率、预设轴力的线性几何模型。若另加入 von Kármán 或共回转梁，它应作为补充对照，不能与线性梁标签混用。

线性模型适用的必要条件是中心线斜率小、轴向伸长与横向位移的二次项可忽略、轴力波动对响应影响小。低张力本身不是失效判据，但会降低横向刚度并更容易产生大位移、构型变化和轴向—横向耦合。[Kim 等（2021）](https://doi.org/10.1016/j.oceaneng.2021.109508)的非线性时域模型显示 VIV 诱导的张力波动会影响响应稳定性；因此本课题要测量这些量，而不是先验宣称所有低张力工况都必须使用 ANCF。

## 5. 结构到切片的运动传递

令结构自由度为 `q_s`，切片平移自由度按 `[x_1,y_1,...,x_N,y_N]^T` 排列。对切片 `i` 所在元素：

$$
\mathbf{x}_{f,i}=
\mathbf{R}_{xy}\mathbf{S}_i\mathbf{A}_i\mathbf{q}_s,
$$

其中 `A_i` 为元素装配/抽取矩阵，`S_i=S(s_i)`。堆叠后得到

$$
\boxed{\mathbf{x}_f=\mathbf{H}\mathbf{q}_s},
\qquad
\boxed{\dot{\mathbf{x}}_f=\mathbf{H}\dot{\mathbf{q}}_s}
$$

当切片位置固定在参考弧长且截面只平移时，`H` 为常矩阵。线性梁和 ANCF 各自构造 `H`，但切片位置、输出顺序和坐标投影一致。

对圆柱边界网格，切片中心平移再由刚体运动分配到所有壁面点；流体内部网格的 Laplace/RBF 变形属于 CFD 网格运动，不进入结构—切片守恒算子的定义。

## 6. 切片载荷到结构广义自由度的守恒传递

### 6.1 离散虚功关系

流体切片合力向量 `F_f` 必须已包含壁面积分、挤出厚度归一化和轴向求积权重。任意结构虚位移 `delta q_s` 引起

$$
\delta\mathbf{x}_f=\mathbf{H}\delta\mathbf{q}_s.
$$

要求流体与结构界面虚功相等：

$$
\delta W_f=\delta\mathbf{x}_f^T\mathbf{F}_f
=\delta\mathbf{q}_s^T\mathbf{F}_s=\delta W_s.
$$

代入运动映射得到

$$
\delta\mathbf{q}_s^T\mathbf{H}^T\mathbf{F}_f
=\delta\mathbf{q}_s^T\mathbf{F}_s,
$$

因此

$$
\boxed{\mathbf{F}_s=\mathbf{H}^{T}\mathbf{F}_f}.
$$

同理，瞬时功率满足

$$
\dot{\mathbf{q}}_s^T\mathbf{F}_s
=\dot{\mathbf{x}}_f^T\mathbf{F}_f.
$$

这只是空间传递的功率一致性；如果流体和结构的时间戳、插值或耦合迭代不一致，时间离散仍可能产生人工能量。理论依据见 [Farhat 等（1998）](https://doi.org/10.1016/S0045-7825(97)00216-8)、[de Boer 等（2008）](https://doi.org/10.1016/j.cma.2008.05.001)和 [Lombardi、Parolini、Quarteroni（2013）](https://doi.org/10.1016/j.cma.2012.12.019)。

### 6.2 连续/积分形式

若不把载荷预先集中到切片，则结构广义载荷可写为

$$
\mathbf{Q}_{h}
=\sum_{i=1}^{N_{cfd}}
w_i\,\mathbf{A}_i^T\mathbf{S}_i^T\mathbf{R}_{xy}^T
\left[
\frac{1}{b_i}
\int_{\Gamma_c^i}\boldsymbol\sigma_f\mathbf{n}\,d\Gamma
\right].
$$

此式就是 `H^T F_f` 的积分版本。任何 spline/RBF/最近点插值都可以用于构造 `H`，但载荷回传必须使用与运动映射相容的离散伴随/转置，而不是另拟一套插值。

### 6.3 必须自动化的守恒测试

1. **常位移复现**：结构做全局刚体平移时，所有切片位移相同。
2. **线性场复现**：形函数阶次允许时，线性中心线位移被准确映射。
3. **合力检查**：`sum(F_slice)` 与结构等效节点合力一致。
4. **力矩检查**：关于同一原点的切片力矩与结构广义力恢复力矩一致；仅有平移自由度时说明可检验的分量。
5. **随机虚功检查**：对随机 `delta q`，

   $$
   e_W=\frac{|(H\delta q)^T F_f-\delta q^T(H^T F_f)|}
   {\max(|(H\delta q)^T F_f|,|\delta q^T H^T F_f|,F_{ref}L_{ref})}
   $$

   应接近机器精度；建议单元测试阈值 `1e-12`（双精度、纯矩阵测试）。
6. **运行时功率检查**：真实耦合步记录

   $$
   e_P=\frac{|\dot q^T F_s-\dot x_f^T F_f|}
   {\max(|\dot q^T F_s|,|\dot x_f^T F_f|,P_{floor})},
   $$

   目标 `e_P < 1e-8`；若受文件截断精度影响，应提高输出精度而不是放宽到百分比量级。

## 7. 耦合时间推进

### 7.1 串行交错基线

设耦合时刻为 `t_n`，结构为主时钟：

1. 结构预测 `q_{n+1}^{(0)}, qdot_{n+1}^{(0)}`；
2. 用 `x_f^{(k)}=H q_{n+1}^{(k)}` 更新各切片圆柱边界和动网格；
3. 每个 CFD 切片从 `t_n` 推进到 `t_{n+1}`，必要时做流体子步；
4. 积分壁面应力，形成同一时间戳的 `F_f^{(k)}`；
5. 用 `F_s^{(k)}=H^T F_f^{(k)}` 组装结构广义载荷；
6. 结构求解到 `t_{n+1}`，得到 `q_{n+1}^{(k+1)}`；
7. 若采用松耦合，接受结果；若采用强耦合，检查位移和力残差，使用 Aitken 松弛并返回步骤 2；
8. 写出能量、守恒、CFD 残差和结构非线性迭代信息，再提交时间步。

### 7.2 收敛与时间戳

强耦合残差可定义为

$$
r_x^{(k)}=\frac{\|x_f^{(k+1)}-x_f^{(k)}\|_2}
{\max(\|x_f^{(k+1)}\|_2,D)},
\qquad
r_F^{(k)}=\frac{\|F_f^{(k+1)}-F_f^{(k)}\|_2}
{\max(\|F_f^{(k+1)}\|_2,F_{ref})}.
$$

代表性生产工况建议两者均小于 `1e-4`，但最终阈值必须通过时间步敏感性确定。所有文件必须区分 `time_n`、`time_np1` 和 `coupling_iteration`；禁止把 `t_n` 的位移与 `t_{n+1}` 的载荷标为同一状态而不记录算法含义。

松耦合计算量低，适合最初调试；在低质量比、低张力或大位移下，附加质量效应和相位误差可能使其不稳定。至少选一个高张力和一个低张力工况比较松/强耦合，以确认结构模型差异不是耦合算法伪差。[Farhat、van der Zee 和 Geuzaine（2006）](https://doi.org/10.1016/j.cma.2004.11.031)给出了松耦合时间精度设计的重要参考。

## 8. 验证层级与输出量

### 8.1 代码验证

- CFD：静止圆柱、规定正弦运动圆柱，做网格、域尺寸和时间步收敛；
- 线性梁：静力挠度、固有频率、简谐响应；
- ANCF：刚体转动零应变、悬臂大挠度、初始直梁固有频率、能量漂移；
- 映射：第 6.3 节全部测试；
- 耦合：零流速不应产生净水动力，规定平移应满足符号和功率检查。

### 8.2 试验验证指标

- `A_rms(s)/D`：IL/CF 位移 RMS 包络；
- `kappa_rms(s) D` 或原始曲率时序；
- 平均 IL 偏移 `mean(x(s))/D`；
- 主频与谱峰；
- 主模态与模态权重；
- 上下端平均/波动张力；
- 计算成本：每物理秒的 wall-clock、每步耦合迭代数、内存和切片并行效率。

### 8.3 ANCF/线性梁差异指标

对指标 `g` 定义

$$
E_g=\frac{\|g_{ANCF}-g_{EB}\|_2}
{\max(\|g_{ANCF}\|_2,g_{floor})}.
$$

适用性边界应综合 `E_A`、`E_kappa`、频率差、模态差与张力波动，而不是只比较某一个最大位移点。统计窗口必须在两模型中相同，并报告初始过渡段剔除规则。

## 9. 符号表

| 符号 | 含义 | 单位 |
|---|---|---|
| `L, D` | 立管长度、外径 | m |
| `s` | 参考弧长 | m |
| `u, p` | 流体速度、压力 | m/s, Pa |
| `w_m` | 流体网格速度 | m/s |
| `rho_f, mu, mu_t` | 流体密度、动力黏度、湍流黏度 | kg/m3, Pa·s |
| `q_s, q_e` | 结构系统/单元绝对节点坐标 | 按分量为 m 或无量纲斜率 |
| `r, r_,s` | 中心线位置、中心线斜率 | m, 1 |
| `M, C, K_T` | 质量、阻尼、切线刚度矩阵 | 一致 SI |
| `E, A, I` | 弹性模量、面积、截面二次矩 | Pa, m2, m4 |
| `epsilon, kappa` | 轴向应变、曲率 | 1, 1/m |
| `T_0, T(s,t)` | 线性梁预设轴力、ANCF 恢复轴力 | N |
| `H` | 结构自由度到切片平移的运动映射 | 按自由度量纲确定 |
| `F_f, F_s` | 切片共轭力、结构广义力 | N / 一致广义单位 |
| `b_i, w_i` | CFD 挤出厚度、轴向求积长度 | m |

## 10. 尚待 ANCF 源码确认的数学选择

在看到课题组程序前，不能冻结以下内容：梯度亏缺还是全参数 ANCF、Euler–Bernoulli 还是 Timoshenko、Green–Lagrange 还是 Biot 应变、曲率表达、锁定缓解、约束施加、阻尼和时间积分器。阶段二第一个结构任务是把实际程序公式与本文件逐项对照；若不一致，更新本文件和接口版本，而不是在适配器中偷偷换算。
