# Stage 4D-B Sol主Agent正式验收

日期：2026-08-11  
决定：`passed_with_scope_limits`

## 1. 验收结论

Stage 4D-B 正式通过，但结论严格限于：充分发展三切片流场物化、真实 OpenFOAM 10–持久 ANCF 显式弱耦合 100 步工程稳定性、耦合功审计、原子 checkpoint 完整性及 5+5 restart 严格等价性。

该结果不构成长时间柔性立管 VIV、锁定区、稳定振幅、模态收敛、切片数收敛或试验验证证据。

## 2. 主Agent独立复核

- 协议版本：`0.2.1`。
- 三切片 manifest hash：`d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3`。
- developed-flow bank identity：`5ed12fb1933d27baca9bc681ef21966341a93219cabd827c2a8225124c5cc8b7`。
- bank 原始文件 SHA-256：`d3d9954290d7d14810e173b7e928d2386022b9e27f0233f9652b38a25864110a`。
- Re80/Re100/Re120 的物理、最终场、力时程和 points hash 重新计算通过。
- 三个物化 case 的 `U/p/phi` 与来源快照在仅重写 `FoamFile.location` 后逐文本一致；没有跨 Re 混用证据。
- 正式运行完成 100/100 个全局步和 300/300 个真实 OpenFOAM 切片执行；300 份日志均包含正常 `End`，排除 OpenFOAM 启动时的 `FOAM_SIGFPE` trapping 提示后，没有 Fatal、SIGFPE、NaN/Inf 或异常终止证据。
- 原始日志重算最大 CFL 为 `0.1725241657902625`。
- ProcessLimiter 的 300 条真实进程记录返回码均为 0；独立区间扫描峰值为 2，没有 permit 泄漏。每个全局步的第三个切片均在前两个进程至少一个释放 permit 后启动。
- 正式运行 MATLAB 启动次数为 1。Windows 启动器 PID 为 `10032`；MATLAB 协议 `initialize` 响应中的 worker PID 为 `12404`。二者含义不同，均保留用于追溯。
- 100 个 committed checkpoint 的 step 为 0–99，时间严格为 `(step+1)×0.0025 s`；2600 个引用对象按真实文件重新计算大小和 SHA-256，错误数为 0。
- 逐步原始力、预测速度和校正速度独立重算能量：`sum(W_CFD)=0.09000936595280201 J`，`sum(W_structure)=0.09033592457897102 J`，`sum(abs(W_CFD))=3.2963482091793406 J`，累计功缺陷为 `-0.0003265586261691226 J`，`E_c=9.906678707660641e-05`。
- 5+5 restart 对 step 0–9 重新比较，time、q、qdot、qddot 和三切片水动力最大绝对误差均为 0；manifest列出的 CFD 对象、motionScale、points、协议/config/physics hash 均一致。

## 3. motionScale审计说明

- 当前 points hash：`04eee7b608ae1bdfc8dee54c66707c707cc8f1bde321e76d93675d5a4b5f1058`。
- 初始确定性生成文件：73,256 bytes，SHA-256 `30c7be5c4faa19a5c311e05585d20dcb0fe0af0b5f1292e8600a4cbb0aba046d`。
- OpenFOAM 首次写回后的生产/checkpoint文件：53,670 bytes，SHA-256 `833fd42be209a83a4b4fd4792dc5377168cd81814a2ba60013b6ce11776cc0a5`。
- 两个文件均包含 10,624 个有限标量，值域 `[0,1]`。restart严格比较采用生产/checkpoint hash，并通过。
- 旧不兼容 hash `79ad02083d870f2b39fcbc8d0a9369ad8ff487a88832109d609af01355a330e4` 未被使用。

## 4. 自动化复核

- Stage 4D-B 专项测试：11/11通过。
- 全项目 Python unittest：234/234通过。
- `python -m compileall -q src tests`：通过。

## 5. 遗留事项和下一阶段边界

1. 将 fresh-case 所需的 `pcorrFinal`、`cellMotionUx` 和 `correctPhi/correctMeshPhi` 形成经过复核的正式模板补丁，不能继续只依赖campaign运行时修补。
2. 后续结果必须同时记录 MATLAB启动器PID和协议worker PID，不能混称为同一个PID。
3. 后续必须继续区分 motionScale 初始生成hash和OpenFOAM规范化写回hash。
4. 0.25 s远短于形成长期VIV统计所需的多个结构/脱涡周期。下一阶段应先进行时间步、结构离散和切片数收敛及分级延时验证，不能直接开展大规模锁定区参数扫描。
5. 当前 `nElem=2`、三切片证据属于原型级离散，不具备高阶模态或整根立管响应的物理收敛资格。

## 6. Gate决定

Stage 4D-B：`passed_with_scope_limits`。

允许进入下一阶段的数值收敛与分级延时验证；不授权宣称完成整根柔性立管VIV、锁定区、稳定振幅或试验验证。
