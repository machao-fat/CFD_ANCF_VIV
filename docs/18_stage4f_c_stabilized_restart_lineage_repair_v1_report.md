# Stage 18 Restart Lineage Repair

`STAGE4F_C_RESTART_LINEAGE_REPAIR_V1_GATE: pass`

新增受验证的 scheduler restart source binding，恢复 source committed checkpoint path；扩展 checkpoint validator 拒绝 step>0 的 null/invalid parent。真实 restart4 从 Stage 17 P step1 source checkpoint 开始完成 step2--5。首个 parent 为 `checkpoint_step00000001_f4a64ff11322`，其余 parent 连续。P/R q/qdot/qddot、raw/applied force、stabilizer、CFD U/p/mesh 和 tick 差异均为零。

max CFL 0.1361909198197035，raw |Cd| 1.3825795055944061，applied |Cd| 0.7557429616730951，速度 0.000128894245502183，虚功 3.761510679094993e-16，力转换 0，几何 5.551115123125783e-17 m。compileall、Stage18 4/4、Stage17 8/8、Stage16 2/2、candidate 11/11 和根目录 unittest 842/842 通过。owned process 20/20/0。父与旧证据未改。
