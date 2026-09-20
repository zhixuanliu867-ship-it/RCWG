# RCWG-EXEC-001 本轮独立复核

日期2026-09-19。结论：**已有GitHub/CI材料支持进入API-001工程开发；本机私有X15证明尚未在本次会话取得，必须由Codex在真实调用/合并前实核。**没有把C:盘链接当成当前已上传文件。

## 1. 已核实的远端状态

PR2已合并：05064b27d3f14642b90bdccdbd11fd409ad005a1。
PR3已合并：47ea9703f8adfa5b5778aee5eaff3be802858efb。
PR4当前draft/open；head55a9ac0b8ec062ac7ebe9f7bcf513f84b4b5b278，tree7763db9b757488e393fb4b4d8552c2daeafcecde，base47ea9703…。

GitHub Actions run35448121656/job105910497864在该head为completed/success；通过连接器下载artifact10585831284（149930字节），重新计算SHA256与GitHub提供的8b5c327845377ba3aa658a30232c8ca7ce517798f0bfa1d4cb540f1296b4a491一致。

## 2. 实際证据检查

CI ACCEPTANCE.json记录环境GITHUB_CI、Python3.12.14、708个通过方法，无skip/xfail，27原哨兵和六项突变原入口通过。X00–X14为PASS；X15明确写EXTERNAL_DELIVERY_PROOF_REQUIRED；full_exec001_accepted仍false。

34个预先声明运行case的结果与期望一致，5算子/8实现分支的runtime coverage通过。34是包含错误计划/取消/超时等在内的工程场景，并非34个模型答案全部正确。

CI记录212个受测文件的运行前/后散列映射完全一致，并绑定tree7763…；无staged/source mismatch。下载的artifact中47个已登记日志文件已逐一重新哈希且全匹配。清单另有754个成员未包含在该artifact（例如完整actual-campaign目录）；没有宣称它们已再次逐字节验证。

## 3. 审查代码与边界

实际读取了PR patch、supervisor.py、campaign.py、accept_exec001.py和NEXT_GATE.md。supervisor对每次执行创建子进程、显式最小环境、父进程deadline和进程组清理；recipe只留验证侧；结果重新封存/读取；完成时延与未完成elapsed分开，隔离RAM和budget保持unknown。campaign对离线mock响应建立固定分母；此清单不能直接用于事先未知真实response的API生成。

当前API实现因此新增独立的请求前generation manifest，模型plan解析之后再交EXEC建立执行manifest。生产桥接保持使用同一个run_f1_supervised。

## 4. 本次没有获得的内容

本机交付报告、最终ZIP/patch/WSL原始日志只给了C:/...链接，没有作为本次附件出现。对话检索只找到旧SPEC报告，不能作为本轮EXEC替代。当前CI摘要和实际可下载日志充分支持技术推进，但不能单独证明完整X15或再次独立复跑用户WSL。

本次容器无GitHub直连，无法克隆55a完整工作树；没有独立本地跑708或34-case supervisor gate。API离线开发使用已上传的较早EXEC reference闭环（662项）的重建副本；92新测试和显式reference适配分别实际执行，完整target gate交Codex。没有把较早reference实现称为55a。

## 5. 决策

允许开始API工程；精确PR4的合并批准与本机X15实际核对绑定，见CODEX_TASK §0。只有数据/源码/日志/补丁证据真正齐备才设置pr4_delivery_proof_verified。未知项不改为PASS。当前formal仍关闭；本轮真实模型/GCP/IAM策略动作0。
