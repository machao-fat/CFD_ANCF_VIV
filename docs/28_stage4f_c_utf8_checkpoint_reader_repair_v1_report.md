# Stage 28 UTF-8 checkpoint reader repair v1

首个默认编码入口为 Stage 27 `probe.py` 的 post-commit checkpoint reader。checkpoint 已物理提交后，Windows 默认 GBK 解码 UTF-8 中文路径失败，因此历史事实保持为 physical committed 1、fully audited 0。

Stage 28 冻结 strict UTF-8 合同：JSON/JSONL 显式 UTF-8，拒绝 BOM 和 locale fallback，LF newline，Unicode code point 原样保存，canonical hash 基于 UTF-8 bytes。修复范围仅包括三个默认 reader、严格 UTF-8 helper 和 post-commit accounting。大整数、tau、transaction identity 与 force manifest 语义未改变。

全新 P 使用 `stage28_probe_P_utf8_v1`，dt=0.0025 s，完成 6/6 physical commits 和 6/6 fully audited steps，时间 1.5100--1.5225 s，生成 6 个连续 committed checkpoints。max CFL=0.1363270394859547，max raw |Cd|=2.6846025735776475，velocity consistency=0.00034745809305939605，virtual-work=3.7615106790949934e-16，force conversion=0，geometry error=5.551115123125783e-17 m。

compileall 通过；Stage 28/27/26/25 分别为 5/5、5/5、5/5、8/8；根目录无过滤 unittest 882/882 OK。30 个 owned process 全部关闭、return code 0、residual 0。父 checkpoint SHA-256 保持 `5db86ae104015d51a8268862a1551579d96d0d80d82ddc7f55536371efc0334e`。Q/A/B/C 未启动。

终态：`STAGE4F_C_UTF8_CHECKPOINT_READER_REPAIR_V1_GATE: pass`。下一授权点为独立 Q 或后续数值阶段；本阶段不作该授权。
