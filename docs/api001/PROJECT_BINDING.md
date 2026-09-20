# API001 项目绑定实现与证据边界

本票在已审 PR #4 head 55a9ac0b8ec062ac7ebe9f7bcf513f84b4b5b278 的相同 tree 上开发。X15 已实核交付清单、801 份私有日志、708 方法、34 个实际案例及 212 个源码文件；PR #4 已按明确批准以 merge commit e826100b42c6a3debd72a9ef6d157d2755e118e6 合并。

用户本次项目绑定补充覆盖旧工作票的默认关停要求：允许一个 global pilot、客户端 1 美元、最多 3 生成及 3 计数；前提仍需分别核验。真实模型只由 rcwg_api 请求，工程操作只走同一 WSL shell 的 gcloud，不调用或改动已配 MCP。尚未具体批准的 IAM/API/计费变更仍需精确清单。

LIVE 绑定 rcwg-509116、登录主体 zhixuanliu867@gmail.com、候选 runner rcwg-api-runner@rcwg-509116.iam.gserviceaccount.com。新增 login_account 字段进入 manifest/hash；认证子进程本身显式传 project/account/impersonation，生产入口核对 transport 与 manifest、token provider 的一致性。MOCK 可用隔离的合成项目，不因此具备 LIVE 授权。

认证检查仅查询环境覆盖是否存在、局部配置和账号元数据，不读取凭据文件。覆盖不匹配立即阻断，不修改全局配置。失败审计仅保留操作、时间、退出码、允许列出的错误代码和 HTTP 状态；原始认证 stdout/stderr 不进入证据。短期凭据仅在内存，签发次数与元数据检查、模型请求、IAM 写操作分列。失败的认证也封存固定两槽、零付费预留和 stop_reason。LIVE 不接受外部 token callable 或执行器替换。

API 源码清单现在覆盖 CI、全部旧测试、脚本、配置和工作规范；目标入口前后核对暂存字节。新增 test source pin 保存已审原测试及交付包 92 项测试的原始字节；98 个 EXEC runtime pin 未改动。四个最初回归先失败后通过，另增加认证/超时/错绑/封存/字节替换的真实回归；新增 21 项，API 单测 113 项。原 708 与必需 92 方法和原字节保持。完整目标入口、supervised mock 与独立 CI 才构成离线验收。

已观察到 WSL gcloud 585.0.0 来自 Windows 挂载 SDK 的 Unix 启动脚本，默认配置目录 /home/zhixuan/.config/gcloud 账号列表为空。用户随后确认已有登录在 Windows；仅本票 WSL 子进程以 CLOUDSDK_CONFIG 指向现有 Windows 配置后，实际 auth list 返回获批账号 ACTIVE。未重新登录或改写全局配置，也未读取凭据文件。后续 runner/API/IAM/计费/配额盘点以私有 INVENTORY.json 为准，不能把现有登录或预授权写成云权限、传输或执行通过。

所有最后结果以私有交付中的 WSL_EVIDENCE.json、CI_EVIDENCE.json、LIVE_EVIDENCE.json、COVERAGE_MATRIX.json 为准。CI 保留旧 EXEC gate，并单独跑完整 API target；只上传去敏离线摘要和测试日志，不上传 fixture/recipe/raw model/approval/budget。正式门禁保持 BLOCKED_NOT_FROZEN、formal_ready=false，F1 reference 资源不等于原生隔离计量。

本机 gcloud 对布尔 False 的实际输出大小写已单独复现并修复；HTTP 日志为 False/false 才允许，True 仍阻断。该次本地误阻断及后续复核均保留原始证据，没有通过清理配置或隐藏失败使验收通过。

本机 billing/quota_project 的 CURRENT_PROJECT 按 CLI 官方定义解析为显式 --project 所指定的本项目；凭据签发再显式携带 --billing-project=rcwg-509116。没有改写该全局设置，其他项目字面值仍阻断。两个回归分别检验本别名/明确配额参数与他项目拒绝。
