# 阶段三修复与补算记录

本文件记录本轮“复核—修复—补算”的实际顺序。结论只引用已生成的 CSV/JSON/日志，不把旧报告中的状态文字当作新证据。

## 已执行

1. 审计阶段二欠项、阶段三旧报告、旧 5.55% 在线力差异及旧 EB/ANCF CSV。
2. 发现并修复严格 A/B 案例缺少标准 `FoamFile` 头导致动网格未真正选择的问题；同时补齐 `consumedFile` 初始种子确认，避免 step 0/step 1 死锁。
3. 实现预测速度功、校正速度功和耦合缺陷分开累计；加入结构储能、阻尼耗散、映射广义力范数、逐步残差和张力字段。
4. ANCF/EB runner 增加初始/最终/相对残差、参考张力、总张力范围、动态增量、压缩风险和位置索引；MATLAB 契约测试已通过。
5. 严格同初场 A/B 运行 401 步到 `t=1 s`，得到逐步等价证据。
6. 建立使用发展固定流场的 Re=100、`m*=10`、`zeta=0.01`、Ur=5.2 SDOF 筛查，并启动按结构周期延长的长窗口。

## 当前停止边界

Ur=5.2 的 10 s 筛查只有约 0.96 个结构周期，不能作为锁定准入。长窗口若出现无界响应、网格质量/CFL 越界或能量无来源增长，停止该工况并保留日志；在此之前不并发启动其他 OpenFOAM 工况。Ur=6.0、4.0、7.1、8.0 只有在 Ur=5.2 的基础诊断可信后才进入运行。

## 未完成且不得伪称完成

- A/B 严格案例的中途 CFD restart 前后误差尚未写入自动化结果；旧长回放 restart 只证明文件握手可续传。
- SDOF 仍需至少 10 个稳定结构周期、五个 Ur 工况和 dt/2 比较。
- 新字段生成的 EB/ANCF 长时间同工况比较尚未完成；旧高张力结果位移接近数值噪声，不能作为物理比较。
- 旧 1000 步能量 CSV 缺少显式储能/阻尼字段，已重新计算但标记为 `explicit_stored_energy=false`，不作能量准入证据。

## 运行产物

- `results/04_identical_motion_equivalence/identical_motion_equivalence.json`
- `results/04_energy_audit/energy_audit_summary.json`
- `results/04_sdof_viv_campaign/sdof_campaign_summary.json`
## Latest execution status (2026-08-04)

Strict native/file equivalence passed after repairing the dynamicMeshDict header and consumed-file initialization. The same-initial-flow SDOF dt/2 screen and the Ur=5.2 long run were completed only as diagnostics: the long run was stopped at 18 s before statistical stabilization, and the dt/2 window contains less than one structural cycle. The EB/ANCF physical-amplitude comparison remains blocked by near-zero response; the reduced-stiffness attempt failed safely on CFL/SIGFPE. These are recorded as not accepted, not as missing positive evidence.
