# Stage 4E-B2-A-v2.2.1 统一时间步空间收敛

三套网格均使用 `dt=0.0002 s`。coarse runtime/statistics valid=`True/True`，medium=`True/True`，fine=`True/False`。

空间收敛结果：`False`。fine 正式 max CFL=`0.5515460269434856`，因此不生成伪 GCI，也不接受 medium→fine 空间收敛。
