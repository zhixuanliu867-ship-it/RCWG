# SPEC-001A 独立复核结论

日期：2026-09-19。审查结论：**SPEC001A_REVIEW_ACCEPTED_OFFLINE；可合并 PR #2，进入 SPEC-001B。**
审查范围为仓库与离线协议/计量计算核；不扩展到正式执行器、隔离校准、真实模型/云和论文结果。

## 1. 实际证据核对

- 本轮4个交付文件的SHA256均与所附清单一致：报告、证据JSON、日志ZIP、最终补丁。
- 从原交付ZIP重建tree=408a7968efe9938a49b2a256a54232058d2b99a2；反向应用原A补丁得到已合并BOOT基线tree=6d67ecfd99a1f6b6db317bcea837d866e9f1d1a8。
- 对该干净基线应用Codex最终A补丁，得到tree=e09ee3a93b46192d3e88775fda5e24bade771f4d，与GitHub实时读取head=6afd48490094d716dc65cf84fe822e45216fcac3的tree一致。
- 核对证据JSON指定的27个受测源码文件，逐文件SHA256全部一致。
- 核对20个WSL日志/证据成员（包含历史记录）与另1份CI日志的SHA256；均一致。WSL最终日志记录131项通过，doctor为3.12.14。CI日志也记录3.12.14/131项。
- 连接器实时读取：PR #2 open、merged=false；main仍08b1ecff33ab01098926e3dceba64ab6ab4fa02c；CI run35436480656/job105879895591 completed/success，head与受审提交一致。

## 2. 复验与修复正确性

独立复验使用交付方Linux/Python3.13.5；不与用户WSL/Python3.12.14混写。
受审A代码131项单测全部通过；BOOT_CHECK_PASS、SPEC001A_CORE_PASS、smoke、mock API、public guard通过；formal返回BLOCKED_NOT_FROZEN/2。

进一步将Codex新增14个回归方法放回原117项版本，独立得到14个方法中23个失败子用例；修订版修复后均通过。这支持报告所述的四类修订：
1. JSON指数溢出拒绝；2. 评分非对象/未知字段返回结构化错误；3. 中止运行的elapsed不充当完成时延比；4. public guard检查暂存字节并拦截测试凭据形状/private路径。
这些测试数、子例数分别登记，无重复充数。

## 3. 实际完成范围

完成：F1有限TaskInput/公开组装、离线三值计量计算核、分层归约、候选比较、buffer/字节/标注证据归约、只读cgroup、CI和目标WSL交付。
尚待：完整WorkIR静态编译、全族输入/消息、32算子运行内核、实际事件/身份绑定、语义判真、正式计量/推断、真实API和云。

未发现阻止SPEC-001B离线开发的新增问题。该结论不保证任意未覆盖输入和所有部署环境正确，也不证明凭据从未在其他会话/系统暴露。报告提到的聊天旧Token应由所有者撤销；本次不需要提交任何Token。

## 4. 后续补齐项（不通过隐藏或删测试解决）

- 现有评分核的工程record_id不能替代正式data/plan/runtime/cache/source绑定；SPEC-001B接入身份侧车。
- STRUCTURE_PASS不代表参数/类型/语义完整；本起始包专门保留full_validation=false。
- 相同case_id不足以证明不同面板/参照可比；共同context身份必须一致。
- 源sort示例task_id=F1-demo-002，源task样例为001。各自绑定/派生新夹具，不能为了通过改保护原件。
- cgroup只读数据仍不是受控隔离；正式门禁关闭。

## 5. 可追溯来源

用户本轮：RCWG-SPEC-001A_本机验收与交付报告.md、验收证据.json、验收日志.zip、最终补丁.patch、SHA256SUMS.txt。
实时GitHub读取：PR #2、main ref、head Git commit/tree、CI jobs接口（均只读）。
本地独立复验原始输出见交付包 evidence/review；本轮新增代码测试输出见 evidence/foundation。
