# NATIVE001 实施决定

N0 / D01：受审 291 个文件逐字节及 Git mode 核对后，从精确提交创建一个独立分支。
root AGENTS 和 PROJECT_STATE 只追加当前票指针；历史规范、模型 ledger 和 pins 不变。
D02：C++17 标准库内核，Linux/POSIX 仅用于安全文件与进程接口；不新增第三方依赖。
JSON/UTF8/SHA256 为版本化本地实现，公开标准测试向量与差分测试验证。
D03：scalar 每行；vectorized 固定有界 batch + mask，两条真实路径；不宣称 SIMD。
top_k 保留完整 sort 与有界 heap；ordinal 是最终 tie。共享数据不可写，view/copy 有真实分配证据。
D04：先冻结 test manifest，再执行测试。旧 reference 不修改；独立朴素 oracle 不复用 native comparator。
D05：独占 run 输出，expected slot 先于 spawn；数据解析/校验/编码均在 native worker。
D06：WSL 未发现现有编译器；GitHub 已有 runner 编译器只用于无凭据离线源码测试，
不调用 GCP Cloud Build。若使用 CI 构建的项目二进制在 WSL 运行，必须先核对精确 source/flags/
artifact SHA，作为项目私有产物使用，不能安装到系统，也不能混称 WSL 本机编译证据。
D07：N3 fake-filesystem/cgroup 状态机不宣称真隔离。当前主机无写入委派，不执行 cgroup 变更。
N4 条件和 100ms/3% 校准按单一 HOST_CHANGE_PLAN 提交；本票正式门禁始终关闭。
