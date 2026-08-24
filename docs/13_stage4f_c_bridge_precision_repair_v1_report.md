# Stage 4F-C Bridge Precision Repair v1 报告

唯一终态：`STAGE4F_C_BRIDGE_PRECISION_REPAIR_V1_GATE: pass`；`D2_STEP0_TIME_IDENTITY_STATUS: accepted`；Stage 4F-C 数值接受仍被 repair2 与 D1 冻结数值失败阻断。

修复机制是独立时间身份合同：以 1 ns 为基准转换为整数 `time_tick`，同时写规范十进制 `time_s`；global step、case、slice、run identity 全部强校验，消费比较为精确相等，不使用相对浮点容差。旧 `1.50813` marker 被离线测试准确拒绝。OpenFOAM bridge 使用 `max_digits10` 保证旧兼容 consumed marker 的二进制浮点往返。

真实 D2 仅运行 step 0，三 slice 串行完成 `1.5075 -> 1.508125 s` 并生成一个 unified committed checkpoint。max CFL=`0.03407957089255886`，max |Cd|=`9.691461127590776`，虚功相对误差=`0`，力转换误差=`0`，最大几何中心误差=`5.551115123125783e-17`。日志无 FATAL/NaN/Inf/负体积。

compileall、专项 4 项和根目录 unittest 815 项均通过。owned 进程 5 启动/5 关闭/0 残留；运行时及临时目录在 D 盘，C 盘项目 artifact=0。父 checkpoint 与父 32 文件保护组合 hash 前后未变；原始组合值为 `9e51091ce3b62dc379769db6ff8ea0a7afe47950bb60b92615b2990ea9e2ee01`。

本阶段不进入 A/B/C 全窗口、五/九切片、长时 VIV、锁定区或实验验证；Stage 4E physical validation claim 未完成。下一授权点仅能是基于新合同的独立数值稳定性方案评审，不能自动续跑。
