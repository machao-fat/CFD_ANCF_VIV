# Stage 4 多切片 CFD–ANCF 正式接口协议

状态：**Frozen for Gate 4A integration**  
协议版本：`0.2.1`  
冻结日期：2026-08-10  
维护者：Sol 主 Agent

本文是阶段四多切片映射、调度、文件握手和统一 checkpoint 的唯一正式接口定义。`0.1.0` 与两个互不兼容的旧 `0.2.0` 实现不得进入本协议的正式执行路径；如需读取旧证据，只能使用显式命名、默认关闭的 legacy 工具，不得静默迁移。

本协议只支撑“直立顶张式柔性立管二维多切片 CFD–ANCF 显式弱耦合原型”。它不构成整根柔性立管 VIV 物理验证，也不覆盖曲线立管、动态局部坐标、强耦合、机器学习或疲劳寿命。

## 1. 唯一实现来源

以下定义以 `src/coupling/multi_slice_mapping` 中的 `0.2.1` 生产实现为准：

- schema 数据类与字段校验；
- canonical JSON；
- JSON、文件和 payload 的 SHA-256；
- 二维力换算；
- ANCF `H/H^T` 映射；
- ready/consumed marker 校验。

`multi_slice_driver`、`checkpoint` 和后续适配器必须导入或薄封装该实现，不得维护第二套字段、哈希范围或数值换算。

## 2. 坐标系与单位

采用右手全局坐标系：

- 全局 `x`：顺流；
- 全局 `y`：横流；
- 全局 `z`：直立立管参考轴向，参考中心线弧坐标从底端向 `+z` 增加；
- `s_ref_m`：从底端起算的参考弧坐标，单位 m。

`R_GL` 的三列是局部顺流、横流和轴向单位基在全局坐标中的分量：

```text
v_G = R_GL v_L
v_L = R_GL^T v_G
```

Draft 2 的直立立管使用 `R_GL = I`，但该字段不可省略。`R_GL` 必须为有限的 `3×3` 正交右手旋转矩阵，行列式接近 `+1`。

长度单位为 m，时间为 s，速度为 m/s，加速度为 m/s²，OpenFOAM 总力和结构切片积分力为 N，二维单位跨距力为 N/m。

## 3. 静态切片 manifest

顶层字段必须且只能为：

```text
schema_version
case_id
reference_length_m
represented_length_m
R_GL
slices
slice_manifest_sha256
```

每个 `slices` 元素必须且只能为：

```text
slice_id
s_ref_m
slice_length_m
unit_span_m
```

约束：

- `schema_version = "0.2.1"`；
- 至少一个切片；
- `slice_id` 集合必须恰为 `0..N-1`，解析后按 `slice_id` 升序；
- `s_ref_m` 有限、唯一且位于 `[0, reference_length_m]`；
- `slice_length_m > 0`，`unit_span_m > 0`；
- `sum(slice_length_m) = represented_length_m`，采用生产模块中冻结的数值容差；
- `represented_length_m` 可以小于 `reference_length_m`，但必须显式声明；
- manifest 不得嵌入 runtime config，也不包含 `config_sha256`。

## 4. 独立 runtime config

字段必须且只能为：

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

约束：

- `schema_version = "0.2.1"`；
- `dt_s > 0`，`timeout_s > 0`，`start_time_s >= 0`；
- `coupling_iteration = 0`；
- `coupling_scheme = "explicit_weak"`；
- `case_id` 与 manifest 一致；
- `slice_manifest_sha256` 与 manifest 自校验结果一致；
- config 不得嵌入完整 manifest 或静态切片表。

## 5. Canonical JSON 与 SHA-256

JSON 规范化固定为：

```text
encoding       = UTF-8
ensure_ascii   = False
sort_keys      = True
separators     = (",", ":")
allow_nan      = False
```

所有 SHA-256 输出为 64 位小写十六进制字符串。

- `slice_manifest_sha256`：对 manifest 除 `slice_manifest_sha256` 自身以外的全部规定字段计算；
- `config_sha256`：对 config 除 `config_sha256` 自身以外的全部规定字段计算；
- `payload_sha256`：对原子提交完成后的 CSV 原始字节计算；
- checkpoint 文件 hash：对被记录文件的原始字节计算。

禁止递归 hash、嵌套 manifest hash 输入差异和对未知字段的宽松接纳。

冻结的两切片 golden 值为：

```text
slice_manifest_sha256 = ffbf9af8cfe8d65d90762fe088c89e4f427c0eb6a010a20741cee788e6437a5d
config_sha256         = 2c8b815b2bf43cd8581e5eeef604a456d7cff8ca77fb0f4ae08978ec28efd9aa
```

对应 fixture 位于 `tests/multi_slice_mapping/fixtures`。所有消费者必须用生产函数复算，不能只比较硬编码字符串。

## 6. 二维水动力与切片厚度

OpenFOAM `forces` 输出是在实际挤出厚度 `unit_span_m` 上积分得到的总力 `F_OF [N]`：

```text
f_2D = F_OF / unit_span_m                    [N/m]
F_i  = f_2D * slice_length_m                 [N]
F_i  = F_OF * slice_length_m / unit_span_m   [N]
```

要求：

- `unit_span_m` 只除一次；
- `slice_length_m` 只乘一次；
- `H^T` 接收已经积分的 `F_i`，不得再次乘切片长度；
- load payload 同时保留 `F_OF`、`f_2D`、`F_i` 和由 `R_GL` 得到的局部力；
- load 中的几何和 `unit_span_m` 必须与静态 manifest 对应切片一致；
- Draft 2 不映射 CFD 力矩。

## 7. ANCF 运动与载荷映射

ANCF 每节点自由度排列为 `[位置3分量, 斜率3分量]`。切片中心按其 `s_ref_m` 在所属非均匀 Hermite 单元内评价：

```text
r_i = H_i q
v_i = H_i qdot
a_i = H_i qddot
Q   = Σ H_i^T F_i
```

同一 `H_i` 用于位置、速度、加速度和虚位移。切片顺序可以乱序输入，但完整身份集合必须与 manifest 一致；缺失、重复和意外切片均拒绝。

虚功审计定义为：

```text
W_slice       = Σ F_i · δr_i
W_generalized = δq^T Q
error_abs     = |W_slice - W_generalized|
error_rel     = error_abs / max(1, |W_slice|, |W_generalized|)
```

Gate 4A 合成测试阈值为绝对或相对误差不超过 `1e-12`。

## 8. Payload 和 marker

每个切片、每个全局步、每个 payload 恰好一个 UTF-8 CSV 和一行数据。运动和载荷字段沿用 `multi_slice_mapping` 的 `0.2.1` 严格字段表。

共同身份必须包含：

```text
schema_version
case_id
slice_id
s_ref_m
slice_length_m
step
coupling_iteration
time_s
```

ready marker 必须记录 payload 类型、文件名、`row_count=1`、payload hash、config hash 和 manifest hash；consumed marker 还必须记录 consumer。发布顺序固定为：

1. 同目录临时文件写入；
2. flush/fsync；
3. `os.replace` 原子提交 payload；
4. 最后原子发布 ready；
5. 消费者完成校验后原子发布 consumed。

没有有效 ready 时不得读取 payload。step、iteration、slice_id和hash必须精确一致；时间比较使用生产模块冻结的相对容差。任一切片超时、字段错误或hash错误使整个结构步失败，禁止回退到旧载荷。

## 9. 全局时间屏障

每个显式弱耦合步严格执行：

1. ANCF预测全部切片运动；
2. 发布全部运动；
3. 等待全部运动 consumed；
4. 每个OpenFOAM切片仅推进一个目标CFD步；
5. 等待全部载荷 ready；
6. 校验统一身份、时间和hash；
7. 将二维载荷换算为切片积分力并通过 `H^T` 汇总；
8. 生成ANCF staged correction；
9. 准备统一checkpoint；
10. 原子发布全局committed manifest；
11. 幂等地完成内存状态finalize。

任一切片失败时，其他切片不得静默提交，ANCF不得推进到下一步。

## 10. Checkpoint事务语义

全局 `committed` checkpoint manifest 的原子发布是唯一持久化提交点。

结构适配器必须提供等价语义：

- `correct_all`：生成 staged correction；
- `export_staged_checkpoint`：导出该 correction 对应的 `q/qdot/qddot`；
- `finalize_committed`：把已持久化状态应用到内存，必须幂等；
- `discard_staged`：仅可在全局 manifest 发布前调用；
- `load_checkpoint`：从已提交状态恢复。

失败行为：

- manifest发布前失败：不得产生committed manifest，丢弃staged状态，结构不推进，事务为 `FAILED`；
- manifest发布后、内存finalize前失败：保留committed manifest，不得discard，事务为 `RECOVERY_REQUIRED`；
- `RECOVERY_REQUIRED` 必须从该committed checkpoint恢复，禁止为同一step生成第二次提交；
- 不允许出现“状态FAILED、结构未提交，但磁盘存在未处理committed manifest”的矛盾状态。

每个checkpoint必须记录step、time、iteration、两个配置hash、切片身份、上一步切片力、广义力、结构 `q/qdot/qddot`、所有文件的相对路径、字节数和SHA-256。

## 11. OpenFOAM checkpoint文件分类

`motionScale` 冻结为每个case的静态重启文件，通常位于 `0/motionScale`。不得伪造到后续时间目录。

每个切片checkpoint分为：

```text
static_files:
  motionScale

time_files:
  U
  p
  phi
  Uf
  meshPhi
  polyMesh/points
  uniform/time
```

静态和时间文件均需记录相对路径、字节数和SHA-256。restart必须验证切片数量、坐标、长度、`unit_span_m`、两个配置hash、所有文件hash和OpenFOAM时间目录。若真实OpenFOAM restart证明该分类不足，执行任务必须停止并将证据交回Sol，不得自行修改正式协议。

## 12. 错误和超时

当前只允许 `coupling_iteration=0`。超时后不得继续轮询旧数据或读取上一步载荷。NaN/Inf、旧schema、缺失字段、未知字段、重复身份、时间倒退、配置变化、文件篡改和切片进程退出均必须显式失败并保存失败manifest或事务日志。

全局调度器同时最多运行两个重型OpenFOAM进程。出现SIGFPE、checkMesh失败、NaN/Inf、动网格失败或CFL持续超过0.8时必须安全停止短时集成。

## 13. Gate边界

协议和映射通过不等于Gate 4A整体通过。Gate 4A还要求：

- 调度器和checkpoint迁移到本协议；
- golden hash跨模块完全一致；
- pre-commit与post-commit故障测试通过；
- `motionScale`静态checkpoint经过真实restart；
- 生产ANCF wrapper接入；
- 两个真实OpenFOAM切片至少完成两个连续全局弱耦合步；
- 每步具有完整统一checkpoint。

只有Sol主Agent可以修改本文或宣布Gate 4A通过。
