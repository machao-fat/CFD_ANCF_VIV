# Stage 4B-v3：真实双切片 CFD–ANCF 短时闭环报告

## 范围与环境

本报告只记录两个独立二维 OpenFOAM 10 slice case 与生产 ANCF wrapper 的短时规定来流弱耦合闭环，不作自由 VIV、锁定区或整根柔性立管验证结论。每批最多两个 OpenFOAM 进程；两个 slice 使用独立 case、独立日志和独立 force 目录。

正式协议版本为 `0.2.1`，golden hash 为：

```text
slice_manifest_sha256 = ffbf9af8cfe8d65d90762fe088c89e4f427c0eb6a010a20741cee788e6437a5d
config_sha256         = 2c8b815b2bf43cd8581e5eeef604a456d7cff8ca77fb0f4ae08978ec28efd9aa
```

实际连续运行目录为 `results/05_multi_slice_integration_tests_v3/precision12_real_run/stage4b_v3_20260810T052617Z_d791f543/`，唯一 `run_id` 为 `stage4b_v3_20260810T052617Z_d791f543`。分段运行目录为 `precision12_segment_run/stage4b_v3_20260810T052637Z_66c0cb22`，重启运行目录为 `precision12_restart_run_retry/stage4b_v3_restart_20260810T052827Z_a13811bf`。

## 可重复命令

连续两步：

```text
python tests/multi_slice_integration/run_real_two_slice_closed_loop.py --output-root results/05_multi_slice_integration_tests_v3/precision12_real_run --case0 results/05_multi_slice_integration_tests_v3/precision12_closed_cases/slice_0000 --case1 results/05_multi_slice_integration_tests_v3/precision12_closed_cases/slice_0001 --library results/05_multi_slice_orchestration_tests/openfoam_smoke/lib/libancfFileMotion.so --start-time 0.05 --dt 0.0025 --steps 2
```

分段首步和 restart 第二步使用同一脚本/适配器，restart 命令为：

```text
python tests/multi_slice_integration/run_real_two_slice_restart.py --output-root results/05_multi_slice_integration_tests_v3/precision12_restart_run_retry --segment-summary results/05_multi_slice_integration_tests_v3/precision12_segment_run/real_two_slice_closed_loop_summary.json --continuous-summary results/05_multi_slice_integration_tests_v3/precision12_real_run/real_two_slice_closed_loop_summary.json --checkpoint results/05_multi_slice_integration_tests_v3/precision12_segment_run/stage4b_v3_20260810T052637Z_66c0cb22/checkpoints/checkpoint_step00000000_1936f4026b62.json --restart-case0 results/05_multi_slice_integration_tests_v3/precision12_restart_cases_retry/slice_0000 --restart-case1 results/05_multi_slice_integration_tests_v3/precision12_restart_cases_retry/slice_0001 --library results/05_multi_slice_orchestration_tests/openfoam_smoke/lib/libancfFileMotion.so --start-time 0.0525 --runner-time-origin 0.05 --dt 0.0025
```

## 连续闭环结果

物理起始时刻 `t0=0.05 s`，`dt=0.0025 s`，完成全局 step 0 和 step 1，对应目标时刻 `0.052500000000000005 s` 和 `0.055 s`。两个 slice 的 OpenFOAM 返回码均为 0，精确目标 force steps 为 `[0,1]`，连续运行最大 CFL 为 `0.1751576945692777`。

每一步两个切片的积分力如下；这里的 `slice_length_m` 已在 A 模块二维力转换中使用一次，调度器没有再次乘 `Δs`：

| step | slice 0 `(Fx,Fy,Fz) N` | slice 1 `(Fx,Fy,Fz) N` |
|---:|---|---|
| 0 | `(8390.934171197605, -444.128654440886, 3.6400279183e-16)` | `(8390.934171197605, -444.128654440886, 3.6400279183e-16)` |
| 1 | `(7284.604917190419, 83.35623517008659, -8.9294044658e-11)` | `(7284.604917190409, 83.35623517008781, -8.9294044658e-11)` |

step 1 的运动 bridge 为 `(step=2,time=0.055)`，来自 step 0 CFD 载荷校正后的 ANCF 状态；不是解析运动回放。两个连续 checkpoint 均已原子提交，最终 hash 审计有效，包含每个 slice 的 `0/motionScale`、`U/p/phi/Uf/meshPhi/polyMesh/points/uniform/time` 和 native `ancf_checkpoint.mat`。

## 分段运行与真实 restart

分段运行先完成 step 0，最大 CFL `0.175022354475834`，生成 committed checkpoint `checkpoint_step00000000_1936f4026b62.json`；随后完全重新加载两个 OpenFOAM 初始时间目录、`0/motionScale`、字段和 ANCF native MAT checkpoint，并以本地 `stepOffset=1` 发布 seed bridge `(step=1,time=0.0525)`。重启完成 step 1，两个进程返回码 `[0,0]`，最大 CFL `0.1751576945692777`，生成 `checkpoint_step00000001_649580a5d5e5.json`。

连续与分段 restart 的比较结果：

- time 误差：`6.938893903907228e-18 s`，阈值 `1e-12 s`；
- ANCF 最大相对误差：`1.0776151789098421e-14`，阈值 `1e-10`；
- points 最大绝对误差：`0 m`，阈值 `1e-10 m`；
- `U` 最大相对误差：`3.4557564973915958e-18`；
- `p` 最大相对误差：`2.6647488600512854e-15`；
- 水动力相对误差：`1.1717128938999274e-14`；
- `motionScale` hash：相等。

静态 `0/motionScale` 文件为 50855 bytes，四个连续/分段/restart slice case 的 SHA-256 均为 `79ad02083d870f2b39fcbc8d0a9369ad8ff487a88832109d609af01355a330e4`。

这些值均满足任务给定阈值。`uniform/time` 数值误差为 `2.8713123877760526e-19`，只是文本时间表示差异，不改变 step/time 语义。

## checkpoint 与日志

连续运行的两个 manifest、分段 manifest 和 restart manifest 均标记 `status=committed`，文件 hash 全部复算通过。`results/05_multi_slice_integration_tests_v3/checkpoint_final_hash_audit.json` 汇总四个有效 committed manifest；详细原始日志、force 文件、formal exchange payload、ready/consumed marker 和 case provenance 保留在各自运行目录。

## 结论边界

本结果证明的是新鲜案例、精确时间屏障、真实 force 输出、生产 ANCF wrapper、两步真实双切片闭环及工程 restart 等价。它不证明整根柔性立管 VIV 已验证，也不提供 VIV 幅值、锁定区或长期物理精度结论。Gate 4A 是否通过由 Sol 主Agent 复核后决定。
