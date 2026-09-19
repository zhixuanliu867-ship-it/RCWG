# SPEC-001B 完整验收矩阵

本文件是本票的完成定义。当前交付只通过结构/身份基础层；下列完整项由 Codex 实现并提供真实证据。

| Gate | 必需内容 | 失败归类/证据 |
|---|---|---|
| B00 基线 | 131旧测试；33原件散列；A四类修复 | 禁止旧版本回退 |
| B01 输入 | F1–F6各一合法public示例、tagged union、资源/输出schema、schema/索引来源；至少一非法与隐私反例/族 | INPUT_INVALID，不能算模型错误 |
| B02 结构 | forward ref、自环、data+after混合环、局部重复ID、global48节点、depth2正例/depth3反例 | code+JSON Pointer |
| B03 类型 | Record/Table/Stream/Ref/GraphView；nullable、字段存在、列推导、union、错误输出声明、域/版本不匹配 | TYPE_MISMATCH等 |
| B04 注册表 | 全32算子逐项有端口、参数、类型、前置条件的可执行validator；每种implementation有dispatch测试 | coverage引用真实test IDs；enum计数不算 |
| B05 控制 | map $item、branch两臂返回兼容、loop $state不变式、region empty identity、显式捕获、兄弟隔离、nested map/loop | 不插入新算法、不修改节点原序 |
| B06 资源 | 单节点超配拒绝；顺序节点资源不求和误拒；map全局CPU/实例guard；dynamic上界未知登记义务；loop限制及cap终止 | 静态拒绝与runtime guard分开 |
| B07 生命周期 | 直接/间接view、broadcast aliases、release过早/最后使用、分支/循环生命周期义务 | 仅物理buffer唯一计数；没有运行数据不填峰值 |
| B08 谓词 | 合法AST、未知op、代码字符串、bool当int、缺字段、三值逻辑、div0运行时义务 | 专用类型分析，不eval |
| B09 生成 | P0一次；P1两次mock；七字段逻辑schema；原任务不能被logical覆盖；budget/usage/capability清楚 | request_id与generation/attempt/repeat分开 |
| B10 隐私 | 顶层/嵌套private键、随机canary、provider序列化、日志/异常无正文泄露、归档私有exclusive-write | scanner不冒充完备审计 |
| B11 身份 | 改data/budget/runtime/cache/source/metric/measurement/registry导致comparison变化；改plan不要求候选plan相等；改repeat role改变execution | 无法绑定真实字段时阻止正式冻结 |
| B12 不变性 | coherent rename同等静态结论、key-order canonical一致、list-order保留、原始字节hash不同、输入不变 | 不声明不同程序的hash相同 |
| B13 哨兵 | acceptance/spec001b/compiler_cases.json 27用例通过；不得改预期以适配bug | 仅哨兵通过不等于完整B |
| B14 工程与CI | 全测试、compileall、bash语法、public guard检查实际暂存内容、mock calls=0、formal exit2 | WSL与CI独立 |
| B15 交付 | 补丁clean apply/tree一致、实际覆盖矩阵、源码和日志hash、完整SPEC gap空、EXEC接口卡 | 完整B可接受；运行内核仍NOT_IMPLEMENTED |

## 测试组织

保留 tests/test_spec001b_foundation.py 中63个基础方法。新增 tests/test_spec001b_types.py、test_spec001b_operators.py、test_spec001b_regions.py、test_spec001b_generation.py、test_spec001b_binding.py。方法命名只是建议；最终矩阵写实际 test IDs。
总方法数取实际 unittest 报告，不把parametrized子例另当方法。全部32算子与所有分支有可执行测试覆盖才升VALIDATED_CONTRACT；runtime_kernel_status单独保持NOT_IMPLEMENTED。

建议负向回归包括：删类型检查仍需被测试发现；丢弃事件/expected尝试不能抬高分母；伪造参考context或换cache不能通过比较；图/文档跨域IDs不能静默合并。人工负向实验单列，不作为真实模型错误频率。

## 计量范围

本票连接元数据/状态/身份接口，不生成论文资源测量结果。cgroup只读探针继续是工程观测；完整Linux隔离、容器、服务请求、计量开销校准后续验收。不得用estimated_memory、模型自报token或节点数填正式CPU/RAM指标。
