# Stage 4F-C repair2 closeout

## 终态

本轮为允许的冻结失败终态。ApplicationService 修复探针通过，但 A 分支在第 2 步触发硬门槛，B/C 未启动。不得将本结果称为稳定 VIV、涡脱落统计、锁定区或物理验证。

## 运行

- A：完成 3/20 步，时间 `1.5075 -> 1.515 s`；计划终点 `1.5575 s`。
- 首个失败：A step 2，slice 0/2 的 `|Cd|` 为 `10.877564567245084` / `11.003110867115256`，超过冻结上限 10；预测-提交速度差最大 `0.01873367971574207`，超过 `0.01`。
- 三个 slice 日志均有独立 `End`、return code=0、无 fatal、无 NaN/Inf、无负体积。
- max CFL=`0.1363270394859547`；max 虚功相对误差=`2.361122965019162e-16`；max 力转换误差=`0.0`。

## 环境与进程

repair2 使用 `bin\win64\MATLAB.exe` 的独立 D 盘环境探针，payload、版本、许可证和路径检查全部通过；探针 PID 已关闭，残留 0，C 盘 artifact 0。数值 A 共启动 6 个 MATLAB 和 9 个 OpenFOAM WSL launcher，15/15 关闭，残留 0。旧 MathWorksServiceHost 未被清理。

## 身份

父 checkpoint SHA-256 为 `5db86ae104015d51a8268862a1551579d96d0d80ddc7f55536371efc0334e`；父保护集组合 SHA-256 前后均为 `9e51091ce3b62dc379769db6ff8ea0a7afe47950bb60b92615b2990ea9e2ee01`。固定点 MAT `fixed_point_state.mat` 的 SHA-256 为 `6d6d4ff3ee5e30c32538848c4980b50440a85c3be2cd9e1cac23be8561aa9ed8`，与父 checkpoint 内 runner MAT 及 repair2 checkpoint 分开记录。

## 测试

`compileall` 通过；ApplicationService 专项 3/0/0；repair2 专项 38/0/0；根目录无过滤 unittest 698/0/0。

## 风险与下一授权点

当前首要未解决问题是冻结动力门槛在 A step 2 失败，以及 OpenFOAM registry 对已结束 launcher 未保留完整 command/cwd 字段。不得通过放宽阈值、重用 partial case、修改物理合同或跳过 A 完整通过来进入 B/C。下一步需要 Sol 新授权后针对 A 的动力/几何一致性根因进行独立 repair；本轮不建议进入五切片、九切片、长时 VIV、锁定区或试验验证。
