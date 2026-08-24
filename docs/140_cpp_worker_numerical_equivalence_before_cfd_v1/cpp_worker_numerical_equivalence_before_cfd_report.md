# MATLAB/C++ 数值等价审计

- Gate: `STAGE4F_D_CPP_WORKER_NUMERICAL_EQUIVALENCE_BEFORE_CFD_V1_GATE: do_not_pass`
- MATLAB 黄金：step 559 seed，导出 target step 560-599，共 40/40 条；身份、tick、checkpoint、payload hash 校验通过。
- 数值合同：MATLAB/C++ 双算均使用 Gauss=5、max_newton=50、dt=0.00125 s。正式 C++ confirm 的 Gauss=3/max_newton=40 合同保持不变，未被本次静默修改。
- 严格双算：0/40；首个严格失败 step：560。
- 工程容差双算：40/40；最大误差见 `dual_audit`。
- 结论：现有 C++ 路径与 MATLAB LAPACK/数值路径仍存在可累积差异，不能宣称严格数值等价；未放宽 Gate。
- 故障注入：全部 fail-closed；C++ worker startup=1，owned residual=0。
- 授权 MATLAB 导出：4 次，均只执行 exporter；双算/验证阶段启动：MATLAB=0，OpenFOAM=0，WSL=0，CFD=0；未启动任何 confirm。
- 旧证据和旧 runtime：只读保护，未修改、未复用。

保持 `C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`。在严格数值 Gate 通过前，禁止 OpenFOAM、WSL、CFD、Stage75、E5-B/E5-C 和新的 confirm。
