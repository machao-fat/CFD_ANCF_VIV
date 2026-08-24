# 用户会话 Runner v1

该 runner 由用户在 Windows Console 会话中启动。Codex 仅通过 D 盘 inbox/status/completed/failed 文件投递合同和读取审计；当前阶段只支持 probe_only，不启动 correction、OpenFOAM、WSL 或 CFD。

启动：在项目根目录运行 `powershell -ExecutionPolicy Bypass -File .\tools\user_session_runner_v1\start_user_session_runner.ps1`。脚本检查 USERNAME=Administrator、SESSIONNAME=Console、SessionId=1、D 盘路径并拒绝重复 runner；只启动 runner Python 进程并进入 IDLE_WAITING_FOR_CONTRACT。

状态：运行 `powershell -ExecutionPolicy Bypass -File .\tools\user_session_runner_v1\get_runner_status.ps1`。probe：运行 `powershell -ExecutionPolicy Bypass -File .\tools\user_session_runner_v1\write_probe_only_contract.ps1`，结果用 `read_last_result.ps1` 查看。停止：运行 `stop_user_session_runner.ps1`。

合同是 UTF-8 canonical JSON 和 SHA-256，强制 release=2021b、win64、license=1、D 盘 TEMP/TMP/TMPDIR/PREFDIR 及 no_cfd/no_correction/no_openfoam/no_wsl/no_retry=true。非零返回、缺字段、路径或身份不一致均 fail-closed；MathWorksServiceHost 只记录，不因进程存在直接判定 ApplicationService 通过。

Windows 重启或注销后旧合同不会自动恢复。可选任务计划程序配置为用户登录时、Administrator、仅当用户登录时运行；操作启动 PowerShell，参数为 `-ExecutionPolicy Bypass -File "D:\研二文件\开题准备\CFD_ANCF_VIV\tools\user_session_runner_v1\start_user_session_runner.ps1"`，起始于项目根目录。不要选择无论用户是否登录都运行，不要使用 Session 0 服务模式。默认不自动创建计划任务。

状态包括 STARTING、IDLE_WAITING_FOR_CONTRACT、CONTRACT_REJECTED、PREFLIGHT_RUNNING、MATLAB_PROBE_RUNNING、MATLAB_PROBE_FAILED、MATLAB_READY、FAILED_TERMINAL、CLEANUP_COMPLETE、STOPPED，变化写入 UTF-8 JSONL。通过本阶段不代表 E5-B、频率、Strouhal、稳定 VIV、锁定区或实验验证完成。
