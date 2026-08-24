# Stage 4D-A 充分发展初始流场报告

三套独立 fresh fixed-cylinder case 均使用 OpenFOAM 10 `pimpleFoam`、`rho=1000`、`nu=0.01`、`D=1`、`dt=0.0025`、laminar 和 `setFields` 启动扰动；没有把其他速度工况的最终场复制到当前工况。每套运行从 20 s 开始，按 5 s 延长至实际 60 s 上限。

| flow | U (m/s) | Re | 丢弃启动 (s) | 主频 (Hz) | St | mean Cd | Cd RMS | Cl RMS | 两窗口 Cd / Cl RMS / f 相对差 | 周期数 | max CFL | 判据 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|
| Re80 | 0.8 | 80 | 19.8244 | 0.100181 | 0.125226 | 1.37783 | 1.37783 | 0.0104000 | 0.2989% / 20.44% / 0.0850% | 4.053 | 0.16458 | blocked |
| Re100 | 1.0 | 100 | 15.0476 | 0.139811 | 0.139811 | 1.29821 | 1.29822 | 0.0355931 | 0.8078% / 80.67% / 1.074% | 5.975 | 0.18723 | blocked |
| Re120 | 1.2 | 120 | 11.6028 | 0.180799 | 0.150666 | 1.27490 | 1.27491 | 0.0949730 | 1.670% / 57.61% / 1.732% | 8.342 | 0.22499 | blocked |

三套 case 均满足 `Mesh OK`、pimpleFoam 正常结束、CFL `<0.8`、无 NaN/Inf；`St` 均落在 `0.12–0.22`。但 `Cl RMS` 末端窗口差异超过 5%，且四个分块的升力振幅持续单调增长，因此不能称为充分发展。按协议，60 s 仍不满足稳定判据即停止并报告 `blocked`，不得把这些场用作 VIV 物理初始场。

身份与字段审计：

- Re80 developed-flow hash：`438b60a9af07deb7a19c20436c131d3e6c7352a0e7b43e5bd0967bbddeb5c5b0`
- Re100 developed-flow hash：`d72b55b64c7a56a1d5dc9eedcc11a72f3b9dcbcbc83ab5def1ffffa5789bdfb8`
- Re120 developed-flow hash：`80c738c5f6f74c5a07710c5232436bd3ed8d3072441445b77df3eebbbaf059ce`
- `developed_flow_bank.json` 的总状态为 `blocked`。
- 三套最终 `U/p/phi/uniform/time` 字段和完整合并 force CSV 均已保存；hash 重算测试通过，篡改字段测试被拒绝。

一次早期 Re100 模板失败和一次统计器失败均保留在 `cases/openfoam/stage4d_developed_flow/re100_failed_*`，没有删除历史证据。
