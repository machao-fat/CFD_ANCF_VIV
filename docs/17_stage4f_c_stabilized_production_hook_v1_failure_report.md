# Stage 17 稳定化生产接口与最小技术探针失败报告

## Gate

`STAGE4F_C_STABILIZED_PRODUCTION_HOOK_V1_GATE: do_not_pass`

连续 P 分支从父 checkpoint 完成 6 步，时间为 1.5075--1.5225 s。raw/applied force 双路径、冻结 alpha=0.1 稳定化、integer tick、三 slice 串行事务和数值审计均通过。P 的最大 CFL 为 0.1363270394859547，最大 raw |Cd| 为 2.6846025735776475，最大 applied |Cd| 为 0.7557429616730951，速度一致性误差为 0.00034745809305939605，虚功相对误差为 3.761510679094993e-16，力转换误差为 0，几何误差为 5.551115123125783e-17 m。

R 分支 first2 完成后，restart attempt2 从 step 1 checkpoint 执行 step 2--5，四步 CFD 数值和 P 逐项一致：q/qdot/qddot、raw/applied force、stabilizer state、CFD U/p/mesh field hash 和 integer tick 的差异均为 0。冻结 checkpoint gate 仍失败：attempt2 的 step 2 checkpoint `parent_checkpoint_id` 为 `null`，没有绑定 source checkpoint。首个失败 transaction 为 step 2、1.515 s 的 unified checkpoint identity。

该失败属于 restart checkpoint lineage，不是 CFD 数值、mapping、ANCF、动态网格或力转换失败。按硬门槛，未运行更多 CFD、未执行新的 restart attempt，保留 `branch_R_restart4_attempt2` 和 attempt1 全部证据。

专项测试与 compileall 通过；根目录 unittest 实际输出 `Ran 842 tests ... OK`。owned process 启动 60、关闭 60、残留 0。父 checkpoint、父 32 文件保护集及旧证据 hash 未变。

下一步仅可在独立目录修复 restart loader/harness，使 `_committed_checkpoint_path` 与 source checkpoint identity 一致，并补充 parent-child lineage 测试；通过离线和专项测试后，申请重新执行一次独立 2+4 restart probe。不得进入 A/B/C 全窗口、五/九切片、长时 VIV、锁定区或实验验证。
