# Stage 4F-C force freshness repair v1

Gate：`STAGE4F_C_FULL_SHORT_WINDOW_ATTEMPT3_GATE: pass`。A 为 20/20 步，B 为 5+15/20 步，均覆盖 1.5075 -> 1.5575 s；C 未按范围启动。

根因是 OpenFOAM 当前起始时间目录的 `forces.dat` 在后续 solver 运行中追加，旧审计把消费行绑定到该可变共享文件的 mtime/size。修复在消费时将文件原子复制到 run/step/slice 唯一路径，禁止覆盖；后续审计只读取不可变快照，校验精确行、size、mtime 和 SHA-256。A/B 共生成 120 个三 slice consumed-force snapshots，hash 均有效。

所有冻结数值门槛通过：max CFL 0.1363270394859547，max raw |Cd| 2.6846025735776475，max velocity 0.00034745809305939605，max virtual-work 3.830934865169715e-16，force conversion 0，geometry 8.326672684688674e-17 m。MATLAB correct 无 timeout，MATLAB/OpenFOAM owned residual 均为 0。

根目录预检回归为 844/844 OK；此前的临时目录遍历错误通过跳过 runtime/MATLAB 临时树的测试发现隔离修复，未删除旧证据。
