# Stage 4C-B 真实三切片统一 restart 报告

## 路径

非均匀条件使用独立 fresh cases 生成连续基线 step 0–2；另一组独立 fresh cases 先恢复 step 0 的统一 checkpoint，再推进 step 1–2。恢复前正式 checkpoint manager 验证 manifest、切片身份、case 相对路径、7 个 CFD 时间对象、motionScale、ANCF checkpoint 和 native runner checkpoint。

## 结果

- continuous steps: `[0, 1, 2]`；restart steps: `[1, 2]`。
- manifest hash equal: `True`；runtime config hash equal: `True`；physics config hash equal: `True`。
- transaction state equal/committed: `True`；checkpoint valid: `True`。
- time errors: `{'1': 0.0, '2': 0.0}` s。
- ANCF state relative errors: `{'step1/q': 0.0, 'step1/qddot': 0.0, 'step1/qdot': 0.0, 'step2/q': 0.0, 'step2/qddot': 0.0, 'step2/qdot': 0.0}`。
- hydrodynamic force relative errors: `{'step1': 0.0, 'step2': 0.0}`。
- max U relative error: `0.0`；max p relative error: `0.0`；max points absolute error: `0.0` m。
- motionScale hashes equal: `True`；all declared non-U/p field hashes equal: `True`。

所有比较阈值均满足：time `1e-12 s`、ANCF `1e-10`、points `1e-12 m`、U/p `1e-10`、hydrodynamic force `1e-8`。详细逐文件结果见 `results/05_stage4c_real_three_slice_tests/three_slice_restart_comparison.json`。

## 限制

本 restart 是短时显式弱耦合证据，不是长时间自由 VIV restart 证明；真实三切片配置是否正式冻结、是否进入后续任务由 Sol 主Agent 决定。
