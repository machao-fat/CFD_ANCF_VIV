# Stage 68 MATLAB worker 探针与 step 528 隔离重放报告

Gate：`do_not_pass`。自动 MATLAB 进程返回 0，R2021b/win64/license=1 且所有临时目录位于 D 盘；唯一隔离重放返回 0，并产生全新、有限且身份审计完整的 correction MAT 文件。

但 ApplicationService 证据不合格：payload 的 `application_service=true` 是探针脚本自写值，不是服务探针响应；MATLAB logfile 同时出现关机阶段 EditorDataService/Connector 异常。因此不能宣称 ApplicationService 已验证健康，也不能将 Stage 66 历史 return code 1 归因为网络。根因保持 `unknown_insufficient_evidence`。

进程：MATLAB 2 次启动/2 次关闭/residual 0；OpenFOAM、WSL、CFD 启动均为 0。Stage 65 source SHA 保持不变，Stage 66/67 未写入。E5-B 不接受，E5-C 未启动。下一步只能在新授权下设计真正可验证的 ApplicationService API 探针；不得直接重跑 E5-B。
