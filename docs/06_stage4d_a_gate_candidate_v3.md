# Stage 4D-A-v3 gate candidate

## Candidate status

本文件是给 Sol 主Agent 的候选审查材料，不是最终 Gate 判定。开发流 bank 的机器可读状态为 `ready_for_sol_review`；没有写入 `passed`，也没有执行 100 步真实三切片耦合。

候选建议：

- 长时间 VIV：**建议进入**，仅指基础 developed-flow bank、Re80 continuation 和 snapshot identity 证据可进入 Sol 审查；
- Stage 4D-A-v3：**建议通过**，前提是 Sol 复核本报告及全部日志、哈希和测试结果。

上述“建议”不包含锁定区、VIV 统计、100 步中等稳定性或真实耦合 restart 结论。

## Frozen identity

- schema version: `0.2.1`;
- manifest hash: `d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3`;
- `rho=1000 kg/m3`, `nu=0.01 m2/s`, `D=1 m`, `dt=0.0025 s`;
- v1/v2 evidence unchanged: true.

## Developed-flow results

| flow | U (m/s) | Re | snapshot/end (s) | startup discard (s) | cycles | f (Hz) | St | mean Cd | Cd RMS | Cl RMS | max CFL | window criteria |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Re80 | 0.8 | 80 | 315.000000 | 19.8244 | 31 | 0.107336 | 0.134171 | 1.393478 | 1.393478 | 0.039662 | 0.164577 | true |
| Re100 | 1.0 | 100 | 188.500000 | 15.0476 | 24 | 0.141500 | 0.141500 | 1.334786 | 1.334787 | 0.091041 | 0.187226 | true |
| Re120 | 1.2 | 120 | 139.500000 | 11.6028 | 22 | 0.178328 | 0.148607 | 1.295091 | 1.295091 | 0.132408 | 0.224987 | true |

Re100/Re120 使用已有 v2 真实 final field 对齐到实际 snapshot，并重算其截断力时程统计；没有把非 snapshot 的统计端点冒充场端点。三者均满足末端两个窗口至少两个周期、平均 Cd 变化不超过3%、Cl fluctuation RMS变化不超过5%、频率变化不超过3%、`0.12<=St<=0.22`。

## ProcessLimiter provenance

v3 派生审计来自只读 v2 运行记录：`max_processes=2`，实测 `peak_active_count=2`，按真实启动/结束区间重算的 `interval_peak_active_count=2`，`permit_leak=false`。三条 fresh smoke 记录均核验 `setFields` log 存在、返回码0、case/log路径匹配；三条 continuation 记录均为 `setFields_called=false`。v2 原始 JSON 未被覆盖。

## Hashes

- Re80 developed-flow: `9b010c5d6d71162779ddf7eb4861521ef494de88776ea5f502e9aa0652a9a7e5`;
- Re100 developed-flow: `2d2fc3edfdbcf12bc461721d3009d90c54801fdd3bd20649bdfc7799f81fd2e5`;
- Re120 developed-flow: `913e788e29c3ebf1361a4fd422dc8835cbb1b6814f81e51c5c609f9467552136`;
- v3 bank: `5ed12fb1933d27baca9bc681ef21966341a93219cabd827c2a8225124c5cc8b7`.

## Explicit non-scope and Sol review actions

尚未完成且本 v3 不执行：100步三切片 CFD–ANCF、真实耦合 restart、checkpoint/能量审计、MATLAB persistent runner 重新验收、长时间 VIV 或锁定区。Sol 应核验：Re80 每个 pimpleFoam log 与最终场；Re100/Re120 v2 source hash 和 snapshot alignment；三工况 force CSV；ProcessLimiter 区间；v3 bank canonical hash；以及新增 v3 单元测试和全项目回归结果。
