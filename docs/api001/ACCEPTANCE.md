# API-001 完整验收矩阵

状态分离：review / target-offline / live。常规实现和研究定义已批准，不需逐条重新确认。账号、数据位置、IAM及费用授权仍绑定具体范围。

| Gate | 操作与证据 | 通过标准 |
|---|---|---|
| A00 | PR4 精确 head/CI/私有 X15 证明 | 55a9ac0…、708、34、clean apply 与 212 文件实际字节；缺项保留待核验 |
| A01 | 原阶段回归 | `scripts/accept_exec001.py` 成功；原708 method ID保留；27哨兵与6突变继续过 |
| A02 | API固定测试 | required_api_test_ids.json 中92项保留；新增项独立登记；无skip/xfail |
| A03 | 公开消息与私有数据边界 | recipe/gold canary不进入任何 wire contents/systemInstruction；task/schema/源版本可追踪 |
| A04 | 请求策略 | 固定project/global/model/v1；3 generation+3 count；P0/P1阶段和输入/输出上限；零工具/零自动重试 |
| A05 | 预算准入 | SQLite重启/并发/重复请求/错误/磁盘故障；先预留后发送；不能靠换输出名重置 |
| A06 | 服务响应 | HTTP错误、截断、拒绝、多个candidate、非文本工具、invalid JSON、usage缺失/漂移均保存正确状态 |
| A07 | 身份绑定 | generation slots在请求前冻结；recipe/data/code绑定；execution manifest在worker前绑定实际plan |
| A08 | 真实执行桥接 | mock Vertex wire → B strict parser/compiler → `run_f1_supervised` → private artifact/verifier；不替换模型plan |
| A09 | 失败账本 | 固定分母，不重试/不补造成功；响应归档失败仍记录已派发；未封存记录无法获得live通过 |
| A10 | 安全与凭据 | TLS校验/拒跳转/固定域名/短期SA token；token不入代码、控制台输出、Git和常规日志；public guard |
| A11 | 精确目标环境 | Python3.12.14 WSL + 独立CI；源码前后/暂存/提交证据；CI只mock无真实凭据 |
| A12 | 首次真实调用授权 | project/service-account/location/price复核/1美元/6请求/24h批准，绑定manifest和目标离线报告SHA |
| A13 | 一次LIVE pilot | 原始HTTP与modelVersion/responseId/usage、P0/P1真实结果和封存日志；不可用mock代替 |
| A14 | 独立只读LIVE复核 | `review_api001_live.py`，model失败不抹除；资金实际账单未知保持null；formal始终关闭 |
| A15 | 最终交付 | 分开的WSL/CI/LIVE私有日志、报告、机器证据、patch/clean-tree证明、SHA256与下一票接口 |

A00–A11通过且A12具备才可发起LIVE。A13遇到权限/地区/格式等错误时停止并交付真实失败证据；不得把A15写为整票通过，也不得为凑“成功”突破本次批准的请求上限。

交付方本次仅独立读取EXEC的GitHub/CI材料，用户C:盘的最终WSL/补丁证明未附在当前会话。因此A00的私有证明由本机复核补齐。此项是具体证据检查，不能通过改状态字符串解决。
