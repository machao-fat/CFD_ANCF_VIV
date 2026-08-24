# Stage 4A-v2 多切片映射集成修复报告

## 1. 结论摘要

本任务在授权的 `multi_slice_mapping` 范围内完成了 Stage 4 Draft 2
协议候选，实际实现版本为 `0.2.1`。映射模块不再把旧格式继续标记为
`0.2.0`，静态 manifest 与运行 config 采用统一、相互独立的字段和哈希
范围。调度器、checkpoint、公共 file exchange 和正式公共协议文件均未
修改。

本地映射测试 49/49 通过。最大二维力换算相对误差为 0；最大虚功绝对
误差和相对误差均为 `6.661338147750939e-15`。固定两切片 golden fixture
由生产对象和生产 hash 函数生成，并由测试重新解析和复算。

## 2. 原不一致问题

只读检查显示，原映射模块和 `multi_slice_driver` 都使用 `0.2.0`，但
实际对象不是同一协议：

1. 映射 manifest 原先包含 `reference_length_m`、`represented_length_m`、
   `R_GL`、`config` 等字段；调度器静态 manifest 只包含 schema、case 和
   slices。
2. 映射 `SliceDefinition` 原先没有 `unit_span_m`，调度器 `SliceSpec`
   包含 `unit_span_m`。
3. 两侧对 `config_sha256` 和 `slice_manifest_sha256` 的输入范围不同，
   相同切片表不能产生同一 hash。
4. 原调度器 `build_config()` 将整个旧静态 manifest 嵌入运行 config，
   与 Draft 2 的“config 只引用 manifest hash”定义冲突。
5. checkpoint 代码仍依赖调度器旧 contract/hash 结构，不能由本任务
   越权修改。

因此不能把旧映射/调度器数据同时称为 `0.2.0`，也不能通过兼容性猜测
静默混用。

## 3. 本任务实施内容

### 3.1 统一协议对象

`src/coupling/multi_slice_mapping/mapping.py` 现在提供：

- `SCHEMA_VERSION = "0.2.1"`；
- 带 `unit_span_m` 的 `SliceDefinition`；
- 不嵌入运行 config 的 `SliceManifest`；
- 独立的 `RuntimeConfig`；
- 统一 `canonical_json_bytes`、`sha256_json`、`sha256_file`；
- manifest/config 自身 hash 字段排除后的非递归 hash；
- 0.1.0/0.2.0 明确拒绝；
- 运动、载荷、ready 和 consumed marker 使用 runtime config hash 与
  manifest hash 交叉校验；
- load 记录的 `unit_span_m` 与静态 slice 表交叉校验。

### 3.2 力学映射

二维力换算明确保留 `F_OF [N]`、`f_2D [N/m]` 和结构切片积分力
`F_i [N]` 三层。采用：

```text
f_2D = F_OF / unit_span_m
F_i  = f_2D * slice_length_m
Q    = Σ H_i^T F_i
```

`slice_length_m` 不在 H^T 中再次使用。H 通过 ANCF Hermite 单元和局部
坐标评价，支持非均匀节点、节点重合、单元内部切片和同一单元多切片。
ANCF 每节点排列保持 `[位置3, 斜率3]`，未触碰内力、应变、刚度或 Newton
核心代码。

### 3.3 Golden fixture

fixture 位于 `tests/multi_slice_mapping/fixtures`，固定输入为：

- `case_id = golden_two_slice_v2`；
- `reference_length_m = represented_length_m = 10`；
- `(slice_id, s_ref_m, slice_length_m, unit_span_m)` 为
  `(0, 2.5, 5, 1)`、`(1, 7.5, 5, 1)`；
- `R_GL = I`；
- `dt_s = 0.0025`、`timeout_s = 30`、`start_time_s = 0`；
- `coupling_iteration = 0`、`coupling_scheme = explicit_weak`。

由 `generate_golden_fixture.py` 调用生产构造器和 `atomic_write_json` 生成，
没有在测试中写死独立的伪 hash。

## 4. 测试和定量结果

命令：

```text
python -m unittest discover -s tests/multi_slice_mapping -p "test*.py" -v
python tests/multi_slice_mapping/run_tests.py
python -m compileall -q src tests
```

映射专用测试结果：49 run，49 passed，0 failed。覆盖内容包括双/五切片、
非均匀长度、端部半切片、非单位 `unit_span_m`、Δs 单次应用、manifest/config
顺序无关 hash、数值变更 hash、配置与 manifest 独立、旧 0.2.0 拒绝、缺失
unit span、缺失/重复 slice、NaN/Inf、非正交旋转矩阵、step/time/iteration
错误、payload/marker/config/manifest 篡改、多随机种子虚功和原有映射功能。

结果文件：

`results/05_multi_slice_mapping_tests_v2/mapping_v2_summary.json`

定量指标：

```text
max_force_conversion_relative_error = 0.0
max_virtual_work_absolute_error    = 6.661338147750939e-15
max_virtual_work_relative_error    = 6.661338147750939e-15
```

golden hash：

```text
slice_manifest_sha256 = ffbf9af8cfe8d65d90762fe088c89e4f427c0eb6a010a20741cee788e6437a5d
config_sha256         = 2c8b815b2bf43cd8581e5eeef604a456d7cff8ca77fb0f4ae08978ec28efd9aa
```

## 5. 未解决问题和接口请求

本任务没有、也不能修改 `multi_slice_driver` 和 `checkpoint`。它们仍需由
Sol 或授权的集成任务处理以下事项：

1. 将调度器的旧静态 manifest/config 迁移到 Draft 2 的字段集合和 hash 范围；
2. 决定是否提供独立、显式命名的 legacy migration 入口，以及迁移的时间边界；
3. 让调度器和 checkpoint 共同使用同一个 `slice_manifest_sha256` 和
   `config_sha256` 定义；
4. 复核 checkpoint 的切片文件清单和 `motionScale` 记录是否与正式协议
   版本一致；
5. 创建或冻结 `docs/05_multi_slice_contract.md`，并由 Sol 维护公共接口。

这些问题不影响本任务纯函数映射和协议候选的本地验证，但在调度器切换前
不能宣称跨模块 0.2.1 已正式上线，也不能宣称完成整根柔性立管 VIV 验证。

## 6. 范围核查

本修复仅修改 `src/coupling/multi_slice_mapping` 和
`tests/multi_slice_mapping`，并创建本报告、协议候选、fixture 和 v2
结果目录。没有修改阶段三证据、`docs/05_multi_slice_contract.md`、
`multi_slice_driver`、`checkpoint`、`file_exchange` 或 ANCF/EB 核心。
