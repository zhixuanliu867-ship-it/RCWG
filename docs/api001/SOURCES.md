# 官方来源与核对范围

核对日：2026-09-19。以下支持公开产品事实；RCWG数量、预算、停止条件和工程范围属于本轮实施决定。价格/能力可能变化，LIVE前再核实。

| ID | 官方来源 | 本轮使用内容 |
|---|---|---|
| S01 | https://developers.openai.com/codex/mcp （当前重定向 https://learn.chatgpt.com/docs/extend/mcp?surface=cli） | MCP客户面、STDIO/HTTP/OAuth、host config、工具审批 |
| S02 | https://developers.openai.com/codex/plugins （当前重定向 https://learn.chatgpt.com/docs/plugins） | CLI/桌面插件支持、IDE无插件、/plugins |
| S03 | https://github.com/googleapis/gcloud-mcp/blob/main/README.md 与 packages/gcloud-mcp/package.json | Node/gcloud前提、权限、preview状态、源码版本0.5.3（npm分发未下载核验） |
| S04 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-flash-lite | 模型ID、global、token/JSON/countTokens/thinking能力 |
| S05 | https://cloud.google.com/vertex-ai/generative-ai/pricing | 标准global文本0.25/1.50美元每百万，输出包含reasoning |
| S06 | https://cloud.google.com/blog/products/ai-machine-learning/gemini-3-1-flash-lite-is-now-generally-available | GA发布日期2026-05-07 |
| S07 | https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/inference | v1 generateContent字段、usage与系统消息 |
| S08 | https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/count-tokens 与 https://docs.cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1/projects.locations.publishers.models/countTokens | Vertex countTokens的contents/systemInstruction，不使用Developer API另一种wrapper |
| S09 | https://docs.cloud.google.com/sdk/docs/authenticate | gcloud登录、服务账号impersonation、短期token与TokenCreator作用对象 |
| S10 | https://docs.cloud.google.com/vertex-ai/generative-ai/docs/access-control | 预测所需权限与roles/aiplatform.user |
| S11 | https://docs.cloud.google.com/iam/docs/best-practices-for-using-service-accounts | 服务账号/凭据最小权限，避免广泛高权限 |
| S12 | https://docs.cloud.google.com/run/docs/use-cloud-run-mcp | 托管Cloud Run MCP、端点与鉴权；不推定Workflows/Jobs全覆盖 |

Google页面正使用Gemini Enterprise Agent Platform的新名称；本包实际配置仍固定aiplatform.googleapis.com/v1，逐次保存服务响应。网页事实不构成用户账户已开通服务或模型可调用的证据。

## PR4审查来源

https://github.com/zhixuanliu867-ship-it/RCWG/pull/4 ，精确head55a9ac0b8ec062ac7ebe9f7bcf513f84b4b5b278；Git tree7763db9b757488e393fb4b4d8552c2daeafcecde。
GitHub Actions run35448121656，job105910497864，artifact10585831284，artifact SHA256 8b5c327845377ba3aa658a30232c8ca7ce517798f0bfa1d4cb540f1296b4a491。
本轮通过GitHub连接器读取并下载CI；未获得用户本机C:最终WSL/补丁ZIP。docs/api001/EXEC_REVIEW.md和交付包独立证据列出可核查边界。
