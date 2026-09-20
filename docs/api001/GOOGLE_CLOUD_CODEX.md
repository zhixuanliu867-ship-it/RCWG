# Codex、MCP 与 Google Cloud：本轮最短可执行路径

核对日期2026-09-19。以下是官方能力事实加RCWG实施选择，来源见SOURCES.md。

## 1. Codex支持什么

当前官方MCP文档明确：同一Codex host上的桌面客户端、CLI和IDE扩展支持STDIO与Streamable HTTP MCP；HTTP可以使用bearer/OAuth。配置是 ~/.codex/config.toml，可信项目可有 .codex/config.toml。Windows宿主、WSL和远程host可能是不同环境，不能假定配置或gcloud凭据自动互通。[S01]

当前插件文档明确：桌面Codex与Codex CLI支持插件；CLI可用/plugins浏览；IDE扩展不支持插件，但仍支持MCP。[S02] 插件和MCP不是同一层：插件可以打包技能/连接器/MCP；安装插件不等于给Google Cloud授权。实际客户端的codex --version、codex mcp list及支持的配置必须由Codex本机核实，报告当前观察值，不凭网页推断用户版本。

建议本轮使用已有WSL Codex会话 + gcloud CLI。MCP是可选运维便利，不是API001的前置依赖，也不需要为MCP租VM。GoogleCloud不会因为你有ChatGPT或Codex订阅就自动获得Google模型费用额度。

## 2. 三个独立身份/账本

- **Codex工程助手**：读写Git仓库、运行测试、在授权范围内调用gcloud/MCP。
- **GCP runner服务身份**：专用服务账号，用于本轮Vertex generateContent/countTokens；短期token由已登录主体对该SA做impersonation。
- **被测生成器**：`gemini-3.1-flash-lite`，只有rcwg_api发起的真实请求进入基准的生成账本。Codex的推理订阅或MCP对话不作为模型样本。

本轮实际工作流计算留在WSL。下一票CLOUD-001才部署容器/Cloud Run/Workflows与私有GCS，避免把API连通性和云调度混在一个验收项。

## 3. 所有者需要确认的最少内容

在Google Cloud控制台顶部项目选择器确认专用于本实验的**Project ID**，不是显示名/项目编号。确认该项目关联的计费账号和可用配额。后续模型文档/控制台可能使用“Gemini Enterprise Agent Platform”名称；本包固定的是v1 aiplatform REST接口。[S04–S08]

选择global模型路由只发送自建开发任务的公开schema、说明和工具卡，不发送真实私人数据或隐藏答案。global不保证固定单一区域处理；有数据驻留要求时停下修订方案，不把Cloud Run区域当模型服务区域。

确认专用runner SA。已有身份可复用经过审查的最小权限；没有则提交明确的bootstrap计划：

1. 项目内所需服务如aiplatform.googleapis.com及iamcredentials.googleapis.com的启用状态。
2. runner SA名字与用途；无长期JSON key。
3. 推理权限 aiplatform.endpoints.predict；必要时使用已审custom role，或在开发项目使用roles/aiplatform.user并记录其权限较宽。配额项目serviceusage.services.use按当前API要求核对。
4. 登录主体仅在**这一个SA**上获得允许impersonation的权限（通常roles/iam.serviceAccountTokenCreator），不在整个项目授予所有服务账号的Token Creator。[S09–S11]

创建账号、启用API、授权IAM都是实际变更；用户批准精确计划后才能做，并从“动作0”改为真实清单。MCP工具描述或prompt规则不能代替服务端IAM。

## 4. 本机工具和认证

在同一个WSL环境检查codex、gcloud、git、uv及现有Python3.12.14。没有gcloud时按Google官方WSL/Linux安装指引准备安装计划；无需重装Python，也不要无授权sudo改系统。必要的网页登录由所有者完成，密码和2FA不交给模型。

gcloud auth login会存储用户登录凭据于本机；它不是无状态命令。将凭据保存在受保护的用户配置区，不放仓库/runs输出，更不要上传。API适配器再通过捕获stdout的gcloud auth print-access-token --impersonate-service-account获取短期access token，token只存在进程内存，不写到请求JSON、CLI输出或日志。[S09]

真实认证可能触发token刷新/IAM Credentials签发调用，这与IAM**策略变更**不同，单列credential_command_invocations。3+3上限指模型服务方法；不要把认证流量伪称完全不存在。

拥有Owner登录的Codex进程理论上可能通过其他命令使用该身份。impersonation参数是本工具选择的身份，不是同一OS用户下的绝对权限沙箱。要让云运维严格最小权限，使用受限的独立登录主体/执行host或明确的凭据文件访问边界；不让agent任意读取高权限refresh凭据。部署阶段另做专用身份。

## 5. 可选：Google提供的gcloud MCP

已核查googleapis/gcloud-mcp仓库：通过本地gcloud CLI执行命令，要求Node>=20和gcloud；源package.json当前标记@google-cloud/gcloud-mcp 0.5.3。仓库明确是preview solution，并非受GoogleCloud服务条款支持的正式产品。[S03]

本包 `configs/api001/codex-gcloud.example.toml` 默认disabled。启用前：

- 核对npm上精确版本的存在、发布方、dist.integrity/包内容，保存观察。仓库版本号不证明npm发布已被本轮下载核验。
- 审查启动命令与现有Codex配置，仅添加命名区段，不覆盖用户文件。
- 绑定项目和受限SA，保持每次工具审批。用项目读取/list/describe开始；写操作另审批。
- `enabled_tools=["run_gcloud_command"]` 只限制工具名称；该工具自身仍可写资源。它不是只读沙箱。服务端IAM才限制能做什么。

可供核查的命令（安装执行本身需用户允许网络/本机工具变更）：

```bash
codex --version
codex mcp list
npm view @google-cloud/gcloud-mcp@0.5.3 version dist.integrity repository --json
```

完成审核后可以通过本机Codex的MCP配置添加命名服务。默认不加入--dangerously-bypass-approvals-and-sandbox，不把approval_policy改为永不询问。操作Google Cloud不要求把该MCP部署成公网HTTP服务。

Google也提供托管远程MCP（例如Cloud Run），认证/能力以具体服务文档为准。Cloud Run MCP不等于任意Workflows/Jobs/计费/IAM全功能入口，不因为看见MCP列表就假定所有部署步骤可自动执行。[S12]

## 6. 首次真实调用操作

先完成CODEX_TASK §0–§2，包括X15、800必需方法目标环境（实际结果按日志）和target ACCEPTANCE.json。再用 §4 prepare 命令生成唯一准备目录。prepare不调用模型。

将approval.template.json复制为新的approval.json（私有文件0600），仅依据真实用户批准填写以下内容：

- approved=true；manifest_sha256保持prepare实际值。
- project_id/service_account与config一致；data_location_approved=true只在用户确认global后设置。
- ceiling_microusd=1000000；owner_note记明确的“本准备manifest下最多3生成+3计数、总工作额度1美元”的批准。
- pr4_delivery_proof_verified=true来自实际本机证据核对。
- offline_api_acceptance_sha256为最终target ACCEPTANCE.json文件SHA256。
- expires_unix不超过当前24h；pricing_rechecked_unix为实际重新核实费率时间（24h内）。

保存修改后，按CODEX_TASK live命令执行一次。没有权限/返回429/失败时停止；保留费用预留与日志。prepare目录、budget、响应不能删除重跑来“争取一次成功”。新增计划必须新的授权，旧分母保留。

只读review脚本可在调用结束后反复执行，不调用Google。真实plan若答案错误，保留FAIL；这不自动构成接口失败。计划全部不能静态通过或不能在当前profile执行，则LIVE传输和F1闭环状态分别报告，不声称已跑通。

## 7. 账单与成本

截至核查日global标准文本输入$0.25/百万、输出含reasoning$1.50/百万。[S05] 单次约12,288输入、16,384输出的牌价约$0.02765；这是条件性估算，不包含未知计数服务收费、其他账单项或实际usage变化。

本包3个生成请求合计最大输出配置32,768，最多3×12,288输入时估算约$0.05837。预算ledger保守预留3×$0.25+3×$0.01=$0.78，授权工作额度$1。这些不能充当平台账单硬限额；实际成本在项目Billing/usage中复核，未获得账单时保留null。保留原本轮150美元工作规划，本次不花完它。

若费率/支持地区/模型版本改变，先修订配置与冻结身份，再重新验收；禁止自动换成其他模型。Cloud Run/Workflows资源和预算在CLOUD001另行学习与开通。
