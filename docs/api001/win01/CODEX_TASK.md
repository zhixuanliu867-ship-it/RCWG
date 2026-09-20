# RCWG-API-001 / WIN-01 — Codex Windows原生云访问与个人身份恢复任务

状态：实施决定已批准，Windows适配代码与验收待完成。日期：2026-09-20。
这份文件补充现有 CODEX_TASK、项目绑定提示词与 NET-01；只替换执行host、认证方式和本轮恢复动作，保留研究范围、预算、严格解析、数据隔离与正式门禁。

## 0. 当前基线与流程

仓库 `zhixuanliu867-ship-it/RCWG`，分支 `rcwg/api-001`，PR5保持draft。本次受审 head `e9571b1f9aac872fe050a1d901b1e3318c93e276`，tree `2a9dd81ac2824b4e9c3445ac3bbba915479b7fc0`。PR4已合并，不重导EXEC/API历史补丁。读取最新状态；若head更新，先做增量核对，不重置/覆盖用户变化。

该head离线检查点通过，821方法已在WSL与独立CI完成。新增Windows模式不得沿用旧ACCEPTANCE的hash充当本次最终验收。后续新head不自动获得合并批准，PR5保持draft交独立复核。

用户已明确允许：复用Windows原生已登录gcloud、用其个人账号开展本地pilot，常规实现/测试/提交/推送无需逐项再询问。此授权替换旧“全部云命令必须在WSL”与“LIVE强制runner impersonation”。NET-01原案标 SUPERSEDED_BY_WIN_01，保留历史失败，不照旧修WSL网关。

## 1. 不变的资源与新身份

- Project ID / quota project：rcwg-509116。
- 认证主体：zhixuanliu867@gmail.com，直接用户OAuth。
- 版本化字段建议：auth_mode=GCLOUD_USER，principal_type=USER，principal=上述邮箱；service_account=null。
- Windows身份来自已有SDK登录，不强制WSL重新登录、不复制凭据数据库/refresh token/ADC文件、不把token搬到WSL。
- 不创建runner，不为了旧代码有SA字段而申请IAMCredentials或TokenCreator。本次是否可用由用户已有权限决定。
- 模型/地点/协议/输入输出上限保持当前冻结设置。一次pilot，1美元客户端准入额度，最多3 generateContent +3 countTokens，零自动重试、零自动换模型。
- 计数、生成、OAuth凭据刷新/签发、普通资源读取分别统计。费用预留≠真实账单硬上限。
- API service启用、IAM新增角色、结算绑定、Cloud Run/Workflows/GCS/VM创建均在本票外，缺少时只提交确切变更单给用户。

## 2. 唯一主路线：Windows负责云，Linux负责现有受测计算

用户在 Windows PowerShell / SDK Shell 中操作。按以下分工实施：

```
Windows 原生 SDK / 已登录用户 / 已有 Windows 代理
    ↑↓ 凭据只留Windows进程
Windows受信任HTTPS helper（只支持两类固定模型方法）
    ↑↓ 本机有界stdin/stdout管道，绑定request/hash/manifest；不是公网服务
WSL现有Python 3.12.14 rcwg_api编排/持久预算/严格解析
    → 原run_f1_supervised → artifact → 独立verifier
```

由 Windows 启动器调用 `wsl.exe` 进入指定仓库/发行版；WSL适配器经Windows互操作启动**原生** powershell.exe/pwsh.exe 或已验证的等价helper。先只读确认互操作可用，必要路径由本机探测，不用猜测发行版和SDK安装目录。控制终端可以是Windows，不要求用户进入Linux敲命令。

不把整个EXEC移植到Windows。supervisor依赖Linux进程组，保留98个EXEC runtime pins。也不把Windows成功取得的token交给WSL再由Linux urllib发HTTPS，这仍会留下原网络问题和凭据跨域问题。

helper优先采用现有Windows PowerShell/.NET；发现已有合适的Windows Python也可用，但必须单独记录版本与测试。gcloud内部Python与实验Python不是同一环境，不要求改SDK内置解释器。不得擅自安装软件或改全局执行策略来满足偏好的实现。

## 3. 先做一次新的Windows原生只读预检

新host读取属于本次明确批准的恢复动作，不是对旧WSL失败循环补发；不要再次请求相同批准。

在**实际Windows进程**中读取：OS/PowerShell版本、gcloud命令解析路径、版本、预期账号是否有缓存、有效proxy的type/address/port与认证覆盖项的存在性。只输出允许字段，不dump全套环境/配置/凭据，不打印token或代理密码。验明实际程序为Windows SDK gcloud.cmd或等价Windows入口，不能仅因为可执行文件路径在/mnt/c下就声称Windows。

然后仅发送一次：

```powershell
gcloud projects describe rcwg-509116 --project=rcwg-509116 --account=zhixuanliu867@gmail.com --billing-project=rcwg-509116 --format="json(projectId,projectNumber,lifecycleState)" --quiet --verbosity=warning
```

记录exit_code与脱敏结果。失败后暂停云步骤，给用户一条明确问题及所需动作。普通元数据读取此次默认不自动重试。OAuth缓存存在不证明能刷新，也不证明调用权限。

成功后只读取该项目相关服务（尤其aiplatform）、结算是否启用、可读的配额信息与必需权限。元数据接口读权限失败仅说明该接口不能读，不自动推断predict无权限；项目政策不明时向用户询问，不盲目扩大权限。若要写入服务/IAM/结算配置，列出完整命令、资源、member、role、scope和影响供一次确认。

不要求读取所有组织、全部账号、其他项目或完整IAM policy才准入。不要因用户只有一名成员而推定其为Owner。

## 4. 代码修改清单：两种模式明确并存

现代码仍仅支持服务账号模式。新增版本化用户/Windows分支，保持旧SA分支及旧用例语义，不能删除安全检查来迁就用户模式。

| 当前路径 | 必须完成的修改 |
|---|---|
| rcwg_api/policy.py | 新配置/approval版本，显式auth_mode/principal/transport_host/transport_backend/host与helper散列；USER时service_account=null可合法，旧v1仍按原规则；预算模型仍固定 |
| rcwg_api/auth_binding.py | 新模式固定project/account/quota；USER禁止实际impersonation配置、其他账号/项目、token-file和credential覆盖；proxy/network错误分类精确化 |
| rcwg_api/vertex.py | 保留旧SDK SA transport；新增Windows原生传输配对，使用用户token、x-goog-user-project，不执行impersonation；旧parse_generation/count保持同语义 |
| 建议 rcwg_api/windows_bridge.py + scripts/windows/api001_bridge.ps1 | 本机有界管道、严格协议、Windows认证与HTTPS、固定两方法；实现及部署副本进入源码绑定 |
| rcwg_api/pilot.py | LIVE只允许注册且经验证的精确auth/transport组合；不接受任意token callable或executor替换；持久预算和双生成槽保持；Win传输后仍走原supervisor |
| rcwg_api/live_review.py | 按模式核实argv、principal、headers白名单、bridge receipt/hash/单次派发；USER中不能要求impersonation参数，也不能再拼接None |
| rcwg_api/__main__.py | 提供显式受控模式选择；prepare/live/audit贯通。默认mock、不让已有prepare静默改身份 |
| scripts/accept_api001.py + 新Windows验收入口 | 旧821Linux回归与新host回归分开；最终源码、helper实际副本、配置、版本与hash验证 |
| docs/PROJECT_STATE/ACCEPTANCE | 记录模式变更、NET-01被替换、实际principal，保留旧历史，不把旧821写成Windows全量通过 |

所有接口路径是本次实施目标，尚未声称这些新函数存在。发现实现路径可简化时可调整命名，但必须满足语义与验收矩阵。

## 5. Windows helper 的最低契约

1. 它是受信任的rcwg_api组件，模型不能指定脚本、命令、路径、任意URL或header。只接受固定project/global/model的countTokens/generateContent，URL由白名单枚举构造。
2. stdin封包包含协议版本、manifest_hash、request_id、方法、请求体原始字节/无损编码及SHA、相应预算预留身份。边界检查大小、重复键、UTF-8、方法、ID和hash。不要用PowerShell默认浅层ConvertTo-Json改写深层模型请求；HTTP发送的是已哈希原始UTF-8字节。
3. 固定本机进程argv；通过管道传内容，不把token、提示词、模型内容拼到shell命令。不用Invoke-Expression、eval、任意shell=true或启用FullAccess来解决引用问题。gcloud.cmd使用系统shell执行的必要包装只容纳固定审计过的参数。
4. Windows原生gcloud认证：所有相关命令显式--project、--account，签发命令和资源调用显式--billing-project。GCLOUD_USER时捕获 `gcloud auth print-access-token` stdout，不带--impersonate-service-account。stdout只供helper内存使用，不能转发给外层Codex/WSL/日志。已有缓存可以正常刷新；普通刷新HTTP次数不可观测时为null。
5. 有效认证覆盖检查在Windows内进行。W​​SL环境检查不能替代Windows检查。新模式遇既有impersonation/覆盖不匹配时停止说明，不全局清除，也不悄悄换身份。
6. SDK proxy只约束SDK自身；Windows HTTP helper必须显式采用本轮核对的有效proxy及同等TLS信任。成功运行gcloud不证明其他HTTP库自动读取相同proxy。沿用Windows已有loopback代理，不改WSL gateway，不改监听到0.0.0.0、不加防火墙洞、不关证书验证。认证代理或自定义CA须按实际受控处理，未知配置先停。
7. 原始HTTP响应体无损返回，附status、允许header、response hash、method、request hash、request_id、manifest、实际Windows clock scope。保持响应大小上限/截止时间/禁止重定向/禁止自动重试。模型文本仍只由原B parser处理。
8. LIVE总预算SQLite仍在同一WSL Linux目录，避免放到/mnt/c改变锁/权限语义。父进程持久reserve后才准许helper的模型请求。断管/终止/未知发出状态时保留预留、不补发；provider_receipt=UNKNOWN。能观测的dispatch先记证据，观测不到标unknown，不能补成0。已有请求ID不可重复。
9. 同时测量WSL父进程的bridge端到端耗时和Windows内部HTTP区间，但各自在自己的单调时钟内相减；不同host时间戳不能直接相减。Windows传输耗时/启动/认证与Linux执行计量分开。
10. 不在高权限账号下运行模型返回代码，模型仅返回WorkIR。helper工具不能接受云写命令，部署相关操作不在本适配器内。
11. 包含脚本的源码闭包和Windows实际部署副本都需散列绑定。不能因为helper不在现有.py目录就漏记；不覆盖旧98个EXEC pins。
12. 日志/响应仍为私有证据。Windows临时目录按实际ACL核对，不能把chmod 0600当作WindowsACL证明；管道与文件都要测试中文路径和编码。token不落任何临时文件。

## 6. 新模式必须通过的验收（不要以凑数量结票）

| Gate | 可观察证据 |
|---|---|
| W01 基线保持 | 原821方法、原17测试文件、98runtime pins和27哨兵/6突变保持；真实改动用版本化回归解释 |
| W02 USER身份正确 | 相同project/account/quota接受；其他身份、隐式impersonation、token-file等拒绝；旧SA模式仍测 |
| W03 模式封闭 | 任意callable/错误class/错config/helper hash/错误host receipt不获LIVE准入 |
| W04 Windows原生 | 实际Windows helper PID/版本与原生SDK记录，账号只读核验；无WSL gcloud登录/凭据库读取依赖 |
| W05 代理与TLS | fake网络单元测试和真实Windows只读项目记录；SDK与HTTP helper配置一致；不自动修改全局proxy或证书 |
| W06 请求完整性 | P0/P1真实serializer字节经bridge不变；深层JSON、中文、BOM/错编码、超限、注入路径均检查 |
| W07 预算与重试 | reserve-before-dispatch；并发/重复ID/换目录/bridge死掉不重置；401/403/429/5xx/timeout均无模型重试 |
| W08 秘密隔离 | 人工canary token/代理密码不出现在stdout、stderr、archive、命令行、Git或交付包 |
| W09 失败恢复 | 网络失败、账号刷新失败、helper启动失败/超时/断写明确归因；真实发出不确定不能记0 |
| W10 原闭环 | Windows fake-wire与WSL supervised组合，P0/P1两槽固定；错误模型计划原样失败，不能替换样例 |
| W11 计时证据 | Linux/Windows单调时钟和UTC/link IDs区分；API等待不写入kernel时间；response/manifest/hash绑定 |
| W12 目标平台测试 | WSL Python3.12.14旧+新回归；Windows helper实际离线测试单列；独立CI无云凭据，不能宣称其拥有用户Windows登录 |
| W13 唯一批准 | 只给最终新auth/host/config/source manifest登记既有1美元授权；旧失败历史保留；首发后不能重新prepare重置 |
| W14 LIVE与复核 | 按下节一次pilot，分别记录传输、F1实际执行、答案验证、费用、unknown和审计结论 |

Windows单元测试需有无网络fake模式；mock不能被LIVE入口选中。当暂时无Windows CI时，Linux CI+用户实际Windows证据分别登记，不伪造Windows runner通过。

## 7. 一次LIVE与结束条件

新的主机/身份配置和源码完成目标离线验收、Windows只读可达性/服务/结算及权限前提满足后，重核模型/region/价格，给最终manifest绑定用户现有明确批准。授权预算/次数不变，不需要重复询问“是否用自己的账号、是否global、是否1美元”。本轮更改auth/host已明确允许，实际source/ACCEPTANCE/pricing字段必须据实。

已有日志表明首次真实模型请求仍为0、无prepared manifest、无费用预留。实施前再次读取当前实际状态；若之后已有首发，则不能依据这份旧结论重新开额度，应暂停核对未完成请求。身份变更不能掩盖原模型版本/提示词改变；不得悄悄换模型。

只从最终受测rcwg_api发起最多3次count+3次generate；gcloud/cloud控制台手工生成不计入样本。P1物理阶段用真实逻辑响应。发送失败即保留状态停止，重新尝试须用户新决定。

可报告状态分层：
- API001_TARGET_OFFLINE_PASS：新代码完成WSL与CI验收。
- WINDOWS_USER_TRANSPORT_READY：Windows原生/身份/代理等前提已验，尚非模型调用。
- LIVE_TRANSPORT_OBSERVED：实际provider HTTP/usage/版本与响应已记录。
- LIVE_F1_EXECUTION_COMPLETED：至少一份实际模型计划经原supervisor完整执行；答案PASS/FAIL另列。
- API001_LIVE_F1_ENGINEERING_ACCEPTED：满足原完整LIVE矩阵并通过模式正确的独立审计。
- formal_ready=false / BLOCKED_NOT_FROZEN：持续保持。

如果模型所有输出均静态非法或在支持范围之外，分别交付传输通过与F1闭环未完成；不要再多调用来追求好结果。F1语义FAIL不应被伪装为设施失败。

## 8. 交付与用户协作

本票仍是API-001恢复，不新建Cloud工程、不增加运行矩阵、不投入native计量。允许native设计/测试夹具独立并行，但不称其正式门禁已通过。

交付新REPORT、源码最终SHA/tree/补丁、私有WSL/Windows/CI分开日志、Windows effective host/工具/代理/身份非敏感观察、请求次数/预算/usage/账单状态、LIVE身份链、独立重读与patch proof、NET-01替换登记。PR5保留草稿交复核。真实云写操作如有授权执行按实际清单记数，不能保留“动作0”的旧模板。

需要用户配合时只提出当下具体阻断，例如：“请在Windows SDK Shell完成重新登录”“请确认只启用aiplatform这一项”“该项目缺serviceusage.services.use，请处理”。禁止将未知网络/读权限问题推断成必须新增服务账号或泛化授予Owner/Editor。
