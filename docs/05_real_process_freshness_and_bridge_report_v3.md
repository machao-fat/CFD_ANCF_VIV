# Stage 4B-v3：真实进程新鲜度、运动桥时间语义与参数一致性报告

## 结论

本轮修复使用正式 Stage4-Multislice 0.2.1 协议和 `multi_slice_mapping` 的数据类、规范化哈希与载荷验证入口。A/B golden fixture 完全一致：

- `slice_manifest_sha256 = ffbf9af8cfe8d65d90762fe088c89e4f427c0eb6a010a20741cee788e6437a5d`
- `config_sha256 = 2c8b815b2bf43cd8581e5eeef604a456d7cff8ca77fb0f4ae08978ec28efd9aa`

调度器没有保留第二套 0.2.0 manifest/hash 定义；运行时配置哈希由正式 `RuntimeConfig` 按实际起始时刻计算，连续闭环本次为 `469c8cf387f44d92a63b0a465be40830c69338176805d2df54ed93930cab529f`，与 golden fixture 的 `start_time_s=0` 配置区别已在结果中显式记录。

## 根因确认

v2 真实进程证据不能作为有效双切片闭环证据，原因不是 ANCF 映射测试失败，而是进程边界没有证明数据新鲜：旧案例带有历史时间目录、force 输出、日志和 coupling 状态，载荷等待还允许按 `>=` 时间匹配或复用旧文件。另一个独立问题是运动桥把目标时间替换为 `record.time_s-dt`，使桥接时间和统一屏障语义错位。v2 还使用了 CFD `D=1` 与 ANCF `D=0.028` 的不一致物理参数，导致观测到 `CFL=11.633799`，该运行没有有效完成真实闭环步。

## 案例新鲜度

`cases/openfoam/multi_slice_template/generate_case.py` 不再对参考案例执行整目录 `copytree`。参考案例只允许提供：

1. `constant/`；
2. `system/`；
3. 命令明确指定的初始时间目录；
4. 静态 case 级 `0/motionScale`。

生成器在启动前拒绝已有输出目录，并在生成后检查 `postProcessing` 文件、`coupling` 文件、旧 `forces.dat`、旧 ready/consumed marker、日志、checkpoint、processor 目录和目标时间目录。每个案例写入 `case_provenance.json`，记录 `run_id`、来源初始时刻、白名单和初始文件哈希；Python 汇总、OpenFOAM 日志名和运行目录也包含唯一 `run_id`。

模板保留阶段三 `ancfFileMotion` 动网格方法；真实新案例使用 `writePrecision=16`、`timePrecision=12`，避免字段重启文本量化和时间目录名称漂移。`motionScale` 仍只作为 `0/motionScale` 静态文件保存，没有复制到最终时间目录冒充 OpenFOAM 输出。本次四个 case 的 `motionScale` 均为 50855 bytes、SHA-256 `79ad02083d870f2b39fcbc8d0a9369ad8ff487a88832109d609af01355a330e4`，真实 restart 前后相等。

## 运动桥时间语义

未修改生产版 `ancfFileMotion`。在 v3 适配器中，正式 0.2.1 motion payload 之外显式物化兼容的 0.1.0 bridge：

| 事务 | bridge step | bridge time |
|---|---:|---:|
| 初始种子 | `0`（初始案例）或本地 `stepOffset`（重启案例） | `t0` |
| 全局 step 0 | `1` | `t0 + dt` |
| 全局 step 1 | `2` | `t0 + 2dt` |

目标映射始终是全局 `g -> (g+1, target_time)`，不再使用 `record.time_s-dt`。发布 motion 后等待对应 bridge consumed；ack 必须匹配 step、time，以及可用时的 `slice_id/case_id`，并且 ack 的修改时间不得早于当前 ready 发布。OpenFOAM 进程非零退出会立即终止等待；force 只接受当前目标时刻的完整有限行，并要求文件由本进程产生、尺寸/mtime/hash 相对于上一步发生变化。每个 force 只消费一次，事务结束后再次审计文件 hash。

## 参数一致性

真实闭环统一使用：CFD `D=1 m`、`U=1 m/s`、`rho=1000 kg/m3`、`nu=0.01 m2/s`、单位展向 `1 m`，因此 `Re=100`；ANCF 使用 `L=10 m`、外径 `1 m`、内径 `0.9 m`、`E=2.07e11 Pa`、顶张力 `1e7 N`、`nElem=2`。两个切片为 `(s_ref,length)=(2.5,5.0)` 和 `(7.5,5.0) m`，长度和为 10 m，`dt=0.0025 s`。

推导量为截面积 `0.14922565104551513 m2`、`EA=3.0889709766421635e10 N`、`T/EA=3.2373240394995245e-4`、单位长度质量 `1171.4213607072938 kg/m`、CFD/ANCF 直径比 `1.0`。这些值和有限性检查记录在 `results/05_multi_slice_integration_tests_v3/parameter_consistency.json`。

## 初始状态

初始 `q/qdot/qddot` 全部有限，初始 `q_ref` 通过正式 `H` 插值获得两个切片的参考位置：

- slice 0: `(0, 0, 2.500808938338371) m`；
- slice 1: `(0, 0, 7.502426815015113) m`。

初始 motion seed 的横流/流向增量均为零，审计公差 `1e-12 m`；CFD 的 `z` 方向保持固定二维切片设定。真实运行前使用稳定的预热快照，预热最大 CFL 约 `0.17489696`，实际闭环最大 CFL 为 `0.1751576945692777`，均低于限制。

## 原子 checkpoint 与 restart

调度器使用 staged correction → staged ANCF JSON/native MAT → CFD 文件收集 → hash 校验 → committed manifest 原子发布 → `finalize_committed` 的顺序。manifest 发布前任一错误都会丢弃 staged correction 且不产生 committed manifest；manifest 发布后 finalize 错误进入 `RECOVERY_REQUIRED`，保留已发布 manifest，恢复必须从该 manifest 加载且不会重复提交同一步。`finalize_committed` 对同一 token 幂等。

每个真实 slice manifest 都验证静态 `0/motionScale` 和时间目录内 `U/p/phi/Uf/meshPhi/polyMesh/points/uniform/time` 的字节数和 SHA-256；四个最终审计 manifest 全部 `status=committed` 且 hash 有效。restart 从 step 0 checkpoint 继续 step 1，未读取 pending/prepared/temp 状态。

## 自动化测试

执行结果：mapping 49/49、driver 7/7、restart 4/4、integration 13/13、全量 `tests` 123/123，`python -m compileall -q src tests` 通过。integration 包含 A→B golden manifest/config 和 marker 交叉接受、hash/字段篡改拒绝、真实新鲜度、桥接步时刻和初始 seed 测试；driver/restart 包含全部 staged/pre-commit/post-commit/recovery 注入。

## 交接与边界

未修改正式协议、`multi_slice_mapping`、阶段三 runner 核心、`ancfFileMotion` 生产源码、阶段三结果或 v2 结果。真实证据仅覆盖当前短时两切片弱耦合原型和工程 restart 等价；不作整根立管 VIV、锁定区或物理精度结论。Sol 仍需检查允许目录差异、最终 manifest 和日志，并决定 Gate 4A。
