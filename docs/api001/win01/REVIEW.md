# RCWG-API-001 离线交付复核与 Windows 恢复决定

日期：2026-09-20。受审 head `e9571b1f9aac872fe050a1d901b1e3318c93e276`，tree `2a9dd81ac2824b4e9c3445ac3bbba915479b7fc0`。

## 结论

接受该提交的 `API001_TARGET_OFFLINE_PASS` 检查点。LIVE 传输、真实模型计划执行和答案验证仍未开始，整票 `full_api001_accepted=false`；可以进入同一票的 Windows 身份/传输适配与 LIVE 恢复，尚不以整票通过为依据启动付费 CLOUD-001 部署。

这是新的实施决定，基于用户明确选择 Windows 原生 gcloud 与现有个人登录。历史 NET-01 及两次 WSL 失败保留，本轮主路线替换为 WIN-01，不再要求 WSL gcloud 登录或为本地 pilot 先创建服务账号。Windows 控制/认证/HTTPS 与已验收 Linux 执行器分工，现有 Linux 运行语义不搬迁。

## 实际读取和核验

输入归档：`RCWG-API-001_离线交付与LIVE阻断报告.zip`，SHA256 `3d07e4b6df2d12e3be5a17bedb385b7cd6dbdbaafdedb4f79c13d17bcc5a008b`。
ZIP 内文本未被 Files 索引；本次从已挂载原 ZIP 读取 REPORT、NET-01、机器证据和 SOURCE.zip，不用旧 SPEC 报告替代。

| 证据 | 本次实际核对 |
|---|---|
| 外层 SHA256 清单 | 30 个载荷全部匹配 |
| 完整源码 | SOURCE.zip 的 241 个文件匹配 PATCH_PROOF 的清单 |
| WSL/CI 源码 | 241 文件执行门禁映射一致；168 文件 API manifest 映射一致；前后无变化 |
| Git tree | 源码按归档文件模式重建，tree 与远端精确提交一致 |
| 最终补丁 | 独立副本反向重建并以远端 EXEC tree 锚定基线，再正向 --check/--index，最终 tree 一致 |
| WSL 私有日志 | 3,625 个成员逐项 hash 匹配；日志 ZIP 本身 hash 匹配 |
| 云端预检记录 | 12 个成员逐项 hash 匹配；ZIP hash 匹配 |
| CI 日志 | 55 个登记成员逐项 hash 匹配；artifact 和 CI_RAW.log hash 均匹配 |
| 测试身份 | WSL 与 CI 均记录 821 个通过方法，ID 集合一致；无 skip/expected failure |
| 方法数解释 | 708 个既有方法 + 92 个首批 API 方法 + 21 个新增回归 = 821。单独 API 套件为 113；765 个 subcases 不另加为方法 |
| EXEC 和 API mock | 34 案例结果无偏离，5/8 dispatch；P0/P1 supervised mock 均通过；不计真实模型样本 |
| 远端 | PR4 已合并为 e826100b42c6a3debd72a9ef6d157d2755e118e6；PR5 draft/open；对应 CI job success |

远端 CI：run 35481272645 / job 105999420238。实际读取 GitHub job，不仅依赖包内元数据。

## 本次独立复跑的边界

审查环境 Linux / Python 3.13.5。API 专项 `python -m unittest discover -s tests -p 'test_api001*.py' -v` 实跑 113/113，退出码0；BOOT 完整性通过，formal 仍退出码2并 BLOCKED_NOT_FROZEN。

两次全库 unittest 尝试分别触发本次容器工具的60秒与180秒超时，未取得完整退出结果，因此不声称在此环境独立重跑了821项。中间日志保留；超时发生于审查工具，不据此判定用户代码失败。821项结论来自已核对散列、方法ID和源码绑定的 WSL/CI 实际日志。新 Windows 分工与个人身份分支尚未在本机或云端执行。

本地重建 `.git` 只为 tree 和补丁计算，不伪称具有上游完整提交祖先。未运行依赖真实上游 ancestry 和3.12.14的全套发布门禁。

## 阻断诊断

`CLOUD_EVIDENCE.json` 表明 Codex 从 WSL 执行 Windows SDK 目录里的无扩展名 `bin/gcloud`，进程选择 Windows 配置目录。路径在 C 盘不等于进程运行于 Windows。账号缓存可读，但项目查询均遭 SDK proxy 127.0.0.1:10090 connection refused，未获得项目 API HTTP 响应。

`safe_failure()` 将非白名单错误归到 AUTH_FAILED；结合后续去敏 SDK 诊断，应将新的主阻断状态细化为 LIVE_BLOCKED_NETWORK/PROXY_CONNECTION_REFUSED。保留旧字段和时间，不能把代理错误证明成用户无权限或服务账号不存在。

已有代码 `rcwg_api/auth_binding.py` 硬绑定 runner，`policy.validate_approval` 要求非空 service_account，`vertex.GcloudToken` 必定 impersonation，`pilot` 和 `live_review` 也按该模式校验。直接删除一个命令参数或将邮箱塞入服务账号字段不构成正确适配。

`rcwg_exec/supervisor.py` 显式只接收Linux，并依赖os.killpg/SIGTERM/SIGKILL；因此Windows认证可复用，但821项Linux结果不能自动背书整个执行器的Windows移植。

## 决策与权限

本地pilot批准使用 `zhixuanliu867@gmail.com` 自身短期OAuth身份，项目/配额项目均 `rcwg-509116`。不要求先建立 runner，不调用 IAMCredentials impersonation，不增加成员或角色。用户角色与API可用性仍须按实际核实；项目只有一名用户不能证明某项权限、服务启用或结算已满足。

global、冻结模型、一次pilot、1美元工作额度、最多3生成+3计数、零自动重试保留。身份/传输变化使用新版本配置和最终源码证据；未发生首发的旧记录作为历史。将现有预授权绑定到唯一最终manifest，不伪造验收true、不删除预算重新开额度。

新 Windows 项目读取可执行一次，无需重复请求同一网络恢复批准；若仍失败，保存精确脱敏结果并请用户处理。任何IAM/API启用/计费/部署写操作仍按具体变更清单另确认。

本次没有修改远端、Windows设置、代理、账号、IAM或云资源，也未发起真实模型请求。

## 可核查的公开来源

- Google REST用户凭据：https://docs.cloud.google.com/docs/authentication/rest
- gcloud代理优先级：https://docs.cloud.google.com/sdk/docs/proxy-settings
- access token及quota project：https://docs.cloud.google.com/sdk/gcloud/reference/auth/print-access-token
- WSL NAT / localhost：https://learn.microsoft.com/windows/wsl/networking
- PR5：https://github.com/zhixuanliu867-ship-it/RCWG/pull/5

官方资料用于解释认证和网络机制；项目进展以归档与GitHub实测证据为依据。
