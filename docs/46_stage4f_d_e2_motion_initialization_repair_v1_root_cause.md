# Stage 46 E2 continuation motion 初始化根因审计

源 checkpoint `step=79, time=1.6075 s, tick=1607500000` 的 SHA-256 为 `e14a0552ec6230328208ca1a4a3aafe3e9fb2154a753226c1d93fbba8aa49243`。Stage 45 首 block 调用 continuation scheduler 时使用 `start_step=40`，把旧阶段编号与源状态混用；OpenFOAM seed 因此报告 motion-ready stale/time-payload mismatch。Stage 46 冻结 source layer=79，seed time/tick=1.6075/1607500000，首个 predicted payload=step 80，并按 block 递增 10 步。旧 Stage 45 case、payload、runtime 和结果未复用。
