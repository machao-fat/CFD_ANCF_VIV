# 载荷协议 `s_ref_m` 最小修复提案（已应用）

## 应用状态（2026-08-06）

本提案已实施：publisher 现在强制要求 `--s-ref-m`，continuous driver 显式传入唯一结构切片坐标，load contract 和 ready marker 同时按 `slice_id` 校验 `s_ref_m`。不再保留静默 `0.0` 默认值；单切片 runner 要求恰好一个 `s_ref_m`。新增了75 m发布/读取、错误坐标、marker后篡改和按slice_id多切片校验测试。

## 问题

`tests/continuous_handshake/publish_load_from_forces.py` 当前把载荷 CSV 的 `s_ref_m` 固定为 `0.0`。结构 runner 的旧单切片位置通常为 `0.5 m`，本轮 EB/ANCF 在线对照位置为 `75 m`。载荷校验目前只核对 `slice_id`，因此错误元数据不会触发停止，实际 `H^T` 映射仍使用结构内部坐标。这不影响旧单切片的实际映射点，却破坏了严格协议可追溯性。

本轮没有直接修改 publisher、protocol 或正在被其他任务使用的耦合主循环。准备好的在线启动器会检测该问题并拒绝启动 CFD。

## 最小无冲突修改

### 1. Publisher 接收明确的切片坐标

在 `publish_load_from_forces.py` 增加：

```python
parser.add_argument("--s-ref-m", type=float, required=True)
```

载荷行改为：

```python
"s_ref_m": args.s_ref_m,
```

发布 marker 时改为：

```python
publish_ready(
    load_csv,
    load_ready,
    kind="load",
    expected_s_ref_m=[args.s_ref_m],
)
```

建议使用 `required=True`，避免默认 `0.0` 再次静默掩盖结构坐标错误。

### 2. Continuous driver 传入结构坐标

在启动 publisher 的参数中增加：

```python
"--s-ref-m", str(float(config["s_ref_m"][0])),
```

当前 continuous driver 只允许一个切片，因此这里必须同时断言：

```python
if len(config["s_ref_m"]) != 1:
    raise ValueError("continuous single-slice driver requires one s_ref_m")
```

### 3. Load contract 真正校验坐标

让 `validate_load_csv` 接收可选的 `expected_s_ref_m`，按 `slice_id` 核对每一行坐标。不能只核对行数或排序。例如：

```python
expected_s_ref = list(expected_s_ref_m)
for row in rows:
    sid = int(float(row["slice_id"]))
    actual = float(row["s_ref_m"])
    expected = expected_s_ref[sid]
    if abs(actual - expected) > 1e-10 * max(1.0, abs(expected)):
        raise ContractError("load s_ref_m does not match the structure case")
```

`protocol._validate_payload` 在 `kind == "load"` 时把同一个 `expected_s_ref_m` 继续传给 `validate_load_csv`。

## 必须新增的测试

1. `s_ref=75` 的载荷能发布并读取；
2. payload 为 `s_ref=0`、结构预期为 `75` 时失败；
3. marker 正确但 payload 坐标被改写时失败；
4. 多切片测试按 `slice_id` 而不是CSV偶然行序核对坐标；
5. continuous driver 确认 publisher 命令包含唯一结构 `s_ref_m`；
6. 原有 step/time/digest/NaN/Inf 测试继续通过。

## 合并顺序

等 restart/coupling audit 对 `continuous_fsi_driver.py` 的修改稳定后，再一次性合并以上三个小改动，运行全套Python协议测试。不要只改 publisher 而不改 consumer 校验；也不要为了兼容旧错误数据保留静默默认值。
