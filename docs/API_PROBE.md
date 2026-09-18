# 一次真实API连通性检查（需单独批准）

默认先运行 `python3.12 -m rcwg_boot api-probe`，它使用mock，真实请求数为0。本包实现Gemini原生REST与DashScope兼容接口的单请求探针，当前实测覆盖来自mock传输，真实服务可用性等待账户验收。

## 先登记非密钥配置

记录 provider、账户地域、模型精确ID、当前每百万token输入/输出单价及价格来源、最大输出128token是否受该模型支持、思考开关与数据保留条款。确认只发送代码里固定的公开连通性文本。模型示例名称可用于定位服务，但不能替代控制台可用性与价格核验。

## Gemini

在用户已批准的WSL终端输入；`--model`后放实际核验后的模型ID。`0.20`是本地预算预留，不是报价或真实消费：

```bash
read -rsp 'Gemini API key: ' GEMINI_API_KEY; echo
export GEMINI_API_KEY
python3.12 -m rcwg_boot api-probe \
  --provider gemini \
  --model '<已核验的模型ID>' \
  --allow-paid --reserve-usd 0.20
unset GEMINI_API_KEY
```

## DashScope / 阿里云百炼

在控制台复制本工作空间、地域对应的兼容接口base URL。官方文档2026-09更新后包含工作空间专属域名；区域/key必须匹配。文档某处地域表述不一致时，以当前工作空间控制台提供的端点为准，切勿自行把新加坡端点替换成北京账号端点。

```bash
read -rsp 'DashScope API key: ' DASHSCOPE_API_KEY; echo
export DASHSCOPE_API_KEY
python3.12 -m rcwg_boot api-probe \
  --provider dashscope \
  --model '<已核验的模型ID>' \
  --base-url 'https://<WorkspaceId>.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1' \
  --allow-paid --reserve-usd 0.20
unset DASHSCOPE_API_KEY
```

探针限制到代码中经审核的官方host集合，拒绝HTTP、用户信息、查询参数、异常端口和重定向。账户需要新地域/域名时，先增加审查记录与端点测试；不要放开任意URL访问。

## 输出与失败

输出位于 `runs/api-probe-<id>/report.json`，包含请求与响应hash、模型ID/返回版本、usage、客户端延迟、尝试状态、本地预算预留和实际费用 `null`。它没有执行正式工作流，也没有推断服务器GPU时长。为减小泄露风险，BOOT不保存原始模型返回正文；正式适配工作包再建立私有原始证据归档。

429、HTTP错误、网络超时、JSON失败均产生失败尝试记录，自动重试次数为0。无usage或价格证据时保持实际费用未知。当前HTTP工具的30秒是socket超时，不声称它是严格的整个请求墙钟上限；本轮真实探针由人操作观察。

本地预留SQLite默认在 `~/.local/state/rcwg-boot-001/probes.sqlite3`。不要为继续调用而清空它；先核对服务商账单并申请下一调用任务。密钥输入使用静默read，避免把key直接写进shell命令历史或聊天。API连接权限不会赋予Codex主动发起付费请求的授权。

接口来源：[S7][S8]，见 `docs/SOURCES.md`。
