# Stage 4A 多切片协议候选 Draft 2

状态：候选，供 Sol 主Agent 复核和冻结。本文不替代正式公共协议
`docs/05_multi_slice_contract.md`，也不修改调度器、checkpoint 或公共
`file_exchange` 实现。

## 1. 版本和范围

本候选协议版本为 `schema_version = "0.2.1"`。它统一静态切片表、运行
配置、运动/载荷 payload 以及 ready/consumed marker 的身份和哈希引用。
当前耦合语义是 `coupling_iteration = 0`、`coupling_scheme =
"explicit_weak"`。`0.2.0` 和 `0.1.0` 输入在正式解析路径中明确拒绝；如
未来需要迁移，必须使用显式命名的 legacy migration 入口，不能自动调用。

本候选仅覆盖二维直立立管的多切片 schema、二维力换算、ANCF H/H^T
映射和虚功审计。它不声明已经完成多切片 OpenFOAM 调度、跨进程屏障、
原子 checkpoint 或整根柔性立管 VIV 物理验证。

## 2. 坐标系和单位

采用右手全局笛卡尔坐标系 G：全局 x 为顺流方向，全局 y 为横流方向，
全局 z 为立管参考轴向，参考中心线从底端沿 `+z` 方向递增。切片位置
`s_ref_m` 从底端起算，单位 m。固定局部基矩阵 `R_GL` 的三列依次为
局部顺流、横流、轴向基在全局坐标中的分量。向量转换显式定义为：

```text
F_global = R_GL F_local
F_local  = R_GL^T F_global
```

Draft 2 直立立管默认 `R_GL = I`，但字段不能省略；代码仍使用显式转换
函数并审计旋转矩阵为 3×3 正交、行列式接近 `+1`。

静态表中的 `reference_length_m`、`represented_length_m`、`s_ref_m`、
`slice_length_m` 和 `unit_span_m` 单位均为 m。OpenFOAM 总力和结构切片
积分力单位为 N，二维单位跨距力单位为 N/m；速度为 m/s，加速度为
m/s²，时间为 s。

## 3. 静态 slice manifest

manifest 的字段集合必须恰好为：

```text
schema_version
case_id
reference_length_m
represented_length_m
R_GL
slices
slice_manifest_sha256
```

每个 `slices` 元素的字段集合必须恰好为：

```text
slice_id
s_ref_m
slice_length_m
unit_span_m
```

约束如下：

- `schema_version` 必须为 `0.2.1`；
- `slice_id` 必须恰好是 `0, 1, ..., N-1`，不可重复、不可缺失、不可静默重编号；
- 输入行可以乱序，解析后按 `slice_id` 恢复升序；
- `s_ref_m` 必须有限并处于 `[0, reference_length_m]`，不同切片不得重复；
- `slice_length_m > 0`，`unit_span_m > 0`，且全部有限；
- `sum(slice_length_m)` 必须在明确数值容差内等于 `represented_length_m`；
- `represented_length_m` 不强制等于整根 `reference_length_m`，因此可以显式表示局部区段；
- manifest 不嵌入运行 config，也不包含 `config_sha256`；
- `R_GL` 必须是正交右手旋转矩阵，默认值为单位阵但不能省略。

## 4. 独立运行 config

运行 config 的字段集合必须恰好为：

```text
schema_version
case_id
dt_s
timeout_s
start_time_s
coupling_iteration
coupling_scheme
slice_manifest_sha256
config_sha256
```

其中 `slice_manifest_sha256` 是对静态 manifest 的引用；config 不嵌入
整个 manifest 或任意静态切片列表。当前实现要求：

- `dt_s > 0`、`timeout_s > 0`；
- `start_time_s >= 0`；
- `coupling_iteration = 0`；
- `coupling_scheme = "explicit_weak"`；
- `case_id` 和 `slice_manifest_sha256` 必须分别与 manifest 一致。

## 5. 规范化 JSON 和哈希输入

实现提供统一的 `canonical_json_bytes`、`sha256_json` 和 `sha256_file`。
JSON 规范化规则为：UTF-8 编码、`ensure_ascii=False`、`sort_keys=True`、
`separators=(",", ":")`、`allow_nan=False`。所有浮点值必须有限，NaN/Inf
拒绝。文件哈希直接对原始文件字节逐字节计算 SHA-256，输出 64 位小写
十六进制字符串。

哈希输入字段明确如下：

| 哈希 | 规范化输入 |
|---|---|
| `slice_manifest_sha256` | manifest 的 `schema_version`、`case_id`、`reference_length_m`、`represented_length_m`、`R_GL`、`slices`；排除自身 `slice_manifest_sha256` |
| `config_sha256` | config 的 `schema_version`、`case_id`、`dt_s`、`timeout_s`、`start_time_s`、`coupling_iteration`、`coupling_scheme`、`slice_manifest_sha256`；排除自身 `config_sha256` |
| `payload_sha256` | 已完成原子提交的 CSV 原始字节 |

不存在递归 hash；manifest hash 不含 config，config hash 只含 manifest
hash 字符串。字段顺序变化不改变 JSON hash，数值变化必须改变对应 hash。

## 6. CSV payload 和 marker

运动 payload 每个切片每个耦合步一个 UTF-8 CSV、恰好一行数据；字段沿用
阶段四 Draft 1 的运动字段，包含 schema、case、step/time/iteration、
slice 身份、参考坐标、位移、绝对坐标、速度、加速度和 `status`。必须
满足 `status=complete` 以及：

```text
x_m = x_ref_m + ux_m
y_m = y_ref_m + uy_m
z_m = z_ref_m + uz_m
```

载荷 payload 每个切片每个耦合步一个 UTF-8 CSV、恰好一行数据，字段包含
schema、case、step/time/iteration、slice 身份、`unit_span_m`、
`force_representation`、OpenFOAM 总力、二维单位跨距力、结构切片积分力、
局部力、CFD 时间步和 `status`。必须满足：

```text
force_representation = integrated_slice_force_N
status = complete
```

ready marker 需要保存 payload_kind、payload 文件名、`row_count=1`、
payload SHA-256、config SHA-256 和 manifest SHA-256；consumed marker
另外保存 consumer。marker 必须为 `0.2.1`，身份、step/time/iteration、
manifest hash、config hash 和 payload hash 均需验证。没有 ready marker
时消费者不得读取 payload。

payload、ready 和 consumed JSON 均采用“同卷临时文件写入、flush、fsync、
`os.replace` 原子提交”；ready marker 只能在 payload 原子提交后最后发布。

## 7. 二维力换算和审计

OpenFOAM forces 输出的是实际挤出厚度 `unit_span_m` 上的总力
`F_OF [N]`。转换链为：

```text
f_2D = F_OF / unit_span_m                         [N/m]
F_i  = f_2D * slice_length_m                      [N]
F_i  = F_OF * slice_length_m / unit_span_m        [N]
```

`slice_length_m` 只能乘一次，`unit_span_m` 只能除一次。转换器输出并在
load 中保留三个层次：`F_OF`、`f_2D` 和 `F_i`，另保留 `F_local = R_GL^T
F_i` 用于局部/全局一致性审计。`unit_span_m` 必须和静态 manifest 中同
一 `slice_id` 的值一致；H^T 映射只接受已经积分的 `F_i`，不得再次乘
`slice_length_m`。

## 8. ANCF H/H^T 映射

当前参考实现使用 Hermite 形函数按所属 ANCF 单元和局部坐标评价 `H_i`，
不按最近节点选取。非均匀结构网格、节点重合、单元内部位置以及同一单元
内多个切片均使用各自的 `s_ref_m` 评价。ANCF 每节点自由度排列为
`[位置3分量, 斜率3分量]`。

```text
r_i    = H_i q
v_i    = H_i qdot
a_i    = H_i qddot
δr_i   = H_i δq
Q      = Σ_i H_i^T F_i
```

Draft 2 不映射 CFD 水动力矩。输入切片字典可以乱序，但必须按
`slice_id` 与 manifest 的身份集合严格匹配；缺失、重复或意外切片拒绝。

## 9. 虚功审计

对每个随机扰动 `δq` 验证：

```text
W_slice         = Σ_i F_i · δr_i
W_generalized   = δq^T Q
error_abs       = |W_slice - W_generalized|
error_rel       = error_abs / max(1, |W_slice|, |W_generalized|)
```

审计输出包括两侧虚功、绝对/相对误差、随机种子、切片数、结构自由度数，
以及所有切片的 `slice_id`、`s_ref_m`、`slice_length_m`。本候选实现的
合成测试最大虚功绝对误差和相对误差均为 `6.661338147750939e-15`。

## 10. Golden fixture

固定 fixture 位于：

- `tests/multi_slice_mapping/fixtures/golden_manifest_0.2.1.json`
- `tests/multi_slice_mapping/fixtures/golden_config_0.2.1.json`
- `tests/multi_slice_mapping/fixtures/golden_hashes_0.2.1.json`
- `tests/multi_slice_mapping/generate_golden_fixture.py`

fixture 为两切片、`reference_length_m=10`、`represented_length_m=10`，
切片为 `(s_ref_m, slice_length_m, unit_span_m) = (2.5,5,1)` 和
`(7.5,5,1)`，`R_GL=I`，运行参数为 `dt_s=0.0025`、`timeout_s=30`、
`start_time_s=0`、`coupling_iteration=0`、`explicit_weak`。fixture 哈希
由生产 `SliceManifest`、`RuntimeConfig` 和 `atomic_write_json` 生成，
测试通过同一生产 hash 函数重新验证，不手工伪造 hash。

## 11. 验证结果和边界

本候选的本地映射测试覆盖单/双/五切片、非均匀长度、端部半切片、非单位
挤出厚度、slice_id 乱序、缺失/重复/意外切片、NaN/Inf、step/time/iteration
错误、几何/长度篡改、payload/marker/config/manifest hash 篡改、旧版本
拒绝、局部—全局往返、Δs 单次应用、总力/反对称力和多随机种子虚功。

调度器和 checkpoint 当前仍属于其他授权范围，尚未自动切换到本候选；
因此 Sol 需要在正式冻结前决定跨模块切换窗口、旧数据迁移边界，以及
checkpoint 中 config/manifest hash 的统一接入方式。
