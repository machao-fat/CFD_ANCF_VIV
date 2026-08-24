# Stage 4F-D E5-B bounded campaign v1 报告

## Gate

`STAGE4F_D_E5_B_BOUNDED_CAMPAIGN_V1_GATE: do_not_pass`

唯一失败根因是 block 0、step 528 的 MATLAB correction 非零返回；同一 runtime 未重试，后续 block 与 E5-C 未启动。

## Source

- path：`D:\研二文件\开题准备\CFD_ANCF_VIV\cases\openfoam\stage4f_d_e5_a_bounded_campaign_v1\block_3\checkpoints\checkpoint_step00000519_bb0117d44300.json`
- checkpoint：`step00000519_bb0117d44300`
- parent：`checkpoint_step00000518_623523f307a5`
- step/time/tick：519 / 2.1575 s / 2157500000
- SHA-256 前后均为 `1a28ffa8e4a46f112add566b9be5f3745cc318029c856db2818d541c6891ce73`
- manifest/config：`fbb6fbb7e65e07f649f6b492f266f89a6356f4f230f320f37317f462f88887b9` / `7f3a31da51a0b962a1316ba3bc4cf0bfdf70bde8b22526a90008d193d56bd3df`

## 失败现场

- 授权范围：step 520–559，4 blocks。
- 实际：block 0，step 520–527 已 committed/audited，共 8 checkpoints。
- step 528：三 slice OpenFOAM 日志均有目标 Time/End、return code 0；随后 MATLAB `correct_00000528` return code 1，failure JSON 明确记录该原因。
- snapshot：27 个现场 raw artifacts；partial 不计入 completion。
- 后续 block：0；E5-C：未启动。
- 失败分类：MATLAB correction/orchestration；不是 CFL、Cd、OpenFOAM FATAL、网格或 force conversion 失败。

## 资源与保护

- source SHA 未改变；Stage 1–65 旧证据未修改。
- owned residual：0；非 owned WSL 基础进程未干预。
- 预算停止：否；本次为硬失败终止。
- Stage 52 partial、Stage 56 block_4 和 Stage 65 runtime/snapshots 未作为新 source 或输入复用。

## 测试

- compileall：通过。
- Stage 66 专项：2 passed，0 failure，0 error。
- Stage 57–65 相关离线回归：9 passed，0 failure，0 error。
- 根目录 preflight：910 collected，909 passed，0 failure，0 error，1 skipped；日志已保存，测试本体为 `OK`。

## 统计边界

本次 partial E5-B 不纳入合法累计统计。频率仍为 `not_evaluable_insufficient_cycles`；正式 Strouhal、stable VIV、lock-in、五/九 slice、长时 VIV和实验验证均未完成。

## 下一授权点

若要继续，只能在明确诊断并修复 MATLAB correction step 528 的根因后，以全新 runtime 重新申请 E5-B；不得在本 runtime 重试，也不得启动 E5-C。
