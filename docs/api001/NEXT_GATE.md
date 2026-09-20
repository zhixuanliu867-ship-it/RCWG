# API001 → CLOUD001 / NATIVE-METROLOGY 接口卡

本票提供 rcwg_api prepare/live/audit、scripts/accept_api001.py 及 scripts/review_api001_live.py。原 F1 supervisor 和独立 verifier 的 98 runtime pin 继承已审 EXEC，不重写正式资源测量。

继续 API001：先消除 WSL 登录环境差异，保持固定 project/login/runner；只读核实候选 SA、最小 impersonation 范围、aiplatform/iamcredentials 服务、serviceusage 与计费/配额。无法核实的项目标 UNKNOWN，不按假设创建或授权。需写入时，一次提交确切资源/member/role/scope/命令与费用的变更单。未有实际首发，不把 unit 中 synthetic LIVE 标签计入真实账本。

技术条件齐备且最终目标/CI源码一致后，只准备一个 manifest。依据用户补充登记审批来源、真实 X15、实际 ACCEPTANCE SHA、核价时间与登记起最多24h有效期，不声称用户手工编辑或签名。首次发送后保留 prepared 目录与 SQLite，不改名重置；任何失败按既定规则停止。review 只读，分别报告 transport、F1 completed、答案验证、费用预留/usage/账单和 formal。

CLOUD001：以通过的 API/F1 私有证据为输入，再明确 Cloud Run/Workflows/GCS 项目资源、部署身份、付费额度及接口。当前无部署/公开存储/IAM变更授权；需要容器可用性和云端实际验收，不能拿 WSL/CI 代替。

NATIVE-METROLOGY：保持 Python reference 独立对照，准备 C++20/Arrow 实际内核、统一 Linux worker、进程树/cgroup v2 隔离与校准；完整 WorkIR DAG/regions 和其余算子另补。真实 worker CPU/整体峰值内存/I/O/数据搬运与远端 API 费用分账。未经校准不开放 Success@Budget/EfficientSuccess 正式结果；formal_ready=false。
