# RCWG-API-001：首次模型 API 接入决策

日期：2026-09-19。状态：IMPLEMENTED_OFFLINE；目标 WSL/CI 和真实服务验收分别待办。
依赖受审 EXEC head `55a9ac0b8ec062ac7ebe9f7bcf513f84b4b5b278`，tree `7763db9b757488e393fb4b4d8552c2daeafcecde`。

## 1. 本票目标与角色

把一个真实提供商的模型返回文本接入既有 P0/P1、B 编译器和 F1 supervised runner。输入为自建公开开发任务；G 生成器使用 API；执行仍在用户 WSL 受监督的 Python reference worker 中；recipe/gold 只传独立 verifier。正式模型矩阵、72 模板、960 实例、三项主要比较均保持原定义。

API001 工程配置只选一个服务，不代表六模型主矩阵冻结，不用于论文模型排名。本票不实现 E0/E1 语义 API 或跨云调度。MCP 是 Codex 的运维接口；被测模型的请求必须由 `rcwg_api` 发起、计数和留档，不能让 Codex/MCP代替被测模型写答案。

## 2. 已确定配置

| 字段 | 本票值 |
|---|---|
| 提供商/端点 | Google Cloud，Vertex REST v1，`aiplatform.googleapis.com` |
| 模型 | `gemini-3.1-flash-lite`，GA；实际 modelVersion/responseId 每次保存 |
| 地区 | `global`；这是模型服务路由，不是未来 Cloud Run 的 us-central1；数据位置由所有者批准 |
| 认证 | 现有受限 runner service account 的短期 OAuth token；gcloud impersonation；不用长期 JSON key |
| 尝试 | 同一 F1 开发任务，P0 一次、P1 一次，各执行一次；试次不声称 seed 可复现 |
| 物理请求 | 最多 3 次 generateContent + 3 次 countTokens；认证命令另记 |
| 输出预算 | P0 16,384；P1 逻辑 4,096 + 物理 12,288；沿用 B 总输出上限 |
| 输入门禁 | 对发送的 contents + systemInstruction 做 countTokens，返回估计不超过 12,288 |
| 输出方式 | application/json，candidateCount=1，temperature=1.0，thinkingLevel=MINIMAL，includeThoughts=false |
| 外部工具/缓存 | 不声明 tools、grounding、code execution、URL context 或显式缓存；提供商隐式 cache 的字段保留 |
| 重试与替代 | transport retry=0，generation retry=0，无自动修复、换模型或扩大预算 |
| 支持执行范围 | 公开声明 F1 root chain 与 5 算子/8 reference 分支；有效低效选择照常保留 |

MINIMAL 不等于推理 token 必为 0。P1 是两个独立请求，第二阶段把已解析逻辑契约作为公开输入，不伪造多轮模型消息或 thought signature。官方文档见 SOURCES.md。

## 3. 价格和准入

2026-09-19 核对标准 global 文本牌价：输入 $0.25/百万 token；输出（含 reasoning）$1.50/百万。代码保存该快照，调用前必须在 24 小时内再次核实。费率发生变化时，修订配置和测试，不用旧价直接授权。

本票总授权工作额度 $1。每次 generateContent 预留 $0.25，每次 countTokens 预留 $0.01，最多共预留 $0.78。SQLite 在发送前持久化并事务互斥；超时、错误或磁盘故障不退还预留，不重试。重复 request_id 拒绝；切换输出目录不能重置同一 preparation 的账本。

这些是客户端准入与保守缓冲，并非 Google Cloud 账单硬封顶。countTokens 的实际账单费用保持未知，没有将其写成已核实免费。usage 中所有非 prompt token 以输出单价估计，未扣隐式缓存折扣；缺失字段为 null。估计费用、预留、账单实际费用分列。实际云账单和项目级预算告警应由所有者另外核对。

## 4. 两种冻结时点

**生成之前**：冻结两个 expected generation slot、协议/阶段、task hash、私有 verifier recipe hash、公开数据内容 hash、配置/源代码与预算。此时未知未来模型响应与 plan，不能使用 EXEC 离线 mock 中“先知道 response hash”的清单作为前提。

**模型计划解析之后、worker 启动之前**：以模型真实 plan 建立 EXEC 的 execution manifest。每个 plan-generation attempt、物理 HTTP request、execution repeat 使用各自 ID。失败的 slot 不消失；P1 逻辑失败不发送物理请求。

B 的 `build_request` 只提供字节可追溯的公开消息。外层独立生成 Vertex wire body 和实际请求账本；不会把 B serializer 的 mock 元数据当真实请求数。原始 provider JSON、抽出的 model text 和解析后 canonical plan 分开归档。执行入口收到的 plan 与解析结果一致。

## 5. 失败和停机

401/403/429/5xx、网络不确定、超长响应、拒绝/截断、非法 JSON、P1 逻辑违约、模型版本漂移、usage 必需字段缺失或实际观察超预留，停止本次固定 pilot；后续已登记 slot 标为 NOT_ATTEMPTED，已发生的请求、预留与原始响应保留。再次尝试需一个新准备目录和新的所有者批准，不隐瞒为原尝试的“修复”。

模型计划静态非法仍保留 PLAN_INVALID；静态合法但未支持的执行方式是设施 gap；计算完成但答案错误是 COMPLETED + verifier FAIL。语义错误不触发自动重写。通信/归档故障的 reservation 保留不确定性，不能把“没有完整 HTTP 回执”当成没有派发。

`urllib` 的 timeout 是网络操作超时参数，不作为已验证的请求总硬截止。模型上下文/输出上限和本地请求数量是本票费用限制手段。断电/KeyboardInterrupt 可留下未封存目录；独立验收应标 incomplete，不自动恢复或重发。

## 6. 计量与验收层级

生成侧登记 countTokens 估计、实际 usageMetadata（candidates/thoughts/cached/total）、请求/响应 ID、请求配置和字节 hash、UTC 时间、client latency、保守牌价估计。远端 CPU/GPU/RAM 均 null + NOT_OBSERVABLE。

执行侧继续原 F1 reference 的过程账本；生成延迟不能并入 kernel wall。worker 内 `real_model_requests=0` 表示该 worker 未调用模型；外层 provider 请求账本另计。隔离 RAM/预算内成功仍未知；不产出正式 Success@Budget=1。

- `API001_REVIEW_OFFLINE_PASS`：交付方 3.13.5 下新模块及 reference 连接测试；不能授权 LIVE。
- `API001_TARGET_OFFLINE_PASS`：目标 3.12.14，原完整 EXEC gate、保留 708 方法、API 回归与 supervised mock-wire 闭环通过。
- `API001_LIVE_RECORDED`：真实请求已记录，尚不是验收。
- `API001_LIVE_TRANSPORT_VERIFIED`：独立核查真实 P0/P1 三次生成/计数及身份/usage；模型结果可以失败。
- `API001_LIVE_F1_ENGINEERING_ACCEPTED`：上述通过并至少一个真实计划到达已封存 COMPLETED 的 F1 执行；答案 PASS/FAIL 独立显示。

formal_ready 始终 false。所有者签字和可信适配器 provenance 与哈希共同构成工程证据；哈希本身不证明网络请求真实性。
