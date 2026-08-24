# Stage 27 大整数序列化修复失败报告

`STAGE4F_C_INTEGER_SERIALIZATION_REPAIR_V1_GATE: do_not_pass`

首次精度损失已定位为 `_state_tree -> _finite -> float`。Stage 26 三个 mtime 分别产生 -64、+24、-8 ns 误差。Stage 27 改为 Python arbitrary-precision int 直接写 JSON integer，bool、float、Decimal 和无标记 string 均拒绝；NumPy integer 显式转 Python int。

边界 `2^53-1/2^53/2^53+1`、int64 最大值、超过 int64 和真实 mtime 均通过。compileall、Stage27 5/5、Stage26 5/5、Stage25 8/8、根目录 877/877 OK。

唯一全新 P 的 identity 链一致，step 0 已成功生成一个 committed checkpoint，三份 snapshot 的 path/size/hash/mtime 精确匹配。随后 Stage27 证据 reader 使用 Windows 默认 GBK 读取 UTF-8 checkpoint，触发 UnicodeDecodeError。runner 未将该步计入结果数组，但物理 step 0 已 committed，因此 P 不能接受，也不能在同一 runtime 重试。Q/A/B/C 未启动。

owned process 5/5/0，全部 return code=0。最小下一步是在新 attempt 中统一所有 JSON reader 显式 `encoding='utf-8'`，增加非 ASCII 路径 checkpoint 读取测试，再运行全新 P。
