# SPEC-001B 可执行算子契约补充

本文件记录已批准范围内的具体静态解释。32 算子、56 实现、原 WorkIR AST 形式和保护原件均未改动。`operators.DISPATCH` 指向实际契约函数，分支覆盖引用 `operator_test_mapping.json` 中的真实 unittest 方法。运行内核仍为 `NOT_IMPLEMENTED`。

- 行字段从输入 schema 推导，Table、Stream、EvidenceTable 的只读 overload 保留各自表示。显式流转换由 stream_read、materialize、collect 完成。Nullable 排序键必须声明 `nulls=first|last`。
- 聚合 `count` 输出 Int64；有分组键时，每个生成的分组至少含一行，所以非空类型字段的 sum/min/max/mean 保持非 nullable。无分组键的全局聚合可能为空，或字段本身 nullable 时可能全部为空，结果保留 Nullable；mean 的数值类型为 Float64。运行时另查溢出和空值策略。
- join 仅在碰撞字段加 `left.`、`right.` 前缀；outer join 推导另一侧 Nullable，semi/anti 保持左表字段。已有显式文档 ID 映射随对应字段传递；join 更名映射字段，project/scan 删除未保留映射，aggregate 只保留分组键映射。映射的文档 revision 与图/表的存储身份分列，不能把图节点 ID 自动解释为文档 ID。分支合并和循环不变式必须保留相同映射能力。
- scan 的 index_range 从公开 range/sorted 索引声明中按声明顺序解析首个索引，登记其 ID 和运行时可用性义务。它不接受只有 hash 或不相关索引种类的来源。
- `evidence_merge.conflict_policy=declared_priority` 时，`priority_rule` 使用非空排序键数组 `[{field,direction,nulls?}]`，字段和 nullable 规则与 sort 一致；其他策略不能附带此参数。冲突和 provenance 判真属于实际执行。
- cache 的 `key_fields` 指已声明行/边 schema 的字段，适用明确支持的 Table、Stream、EvidenceTable、Record、Graph 等具有字段 schema 的受管对象。无字段集合对象没有新增的隐式 `item`、路径或身份键命名空间。缓存始终还需绑定同次运行、完整内容和 schema 身份；不能凭几个字段开启跨运行复用。
- JSON 没有独立日期字面量。在比较或 `in` 中，已知 Date/Timestamp 字段为另一侧字面量提供类型上下文：Date 接受严格 `YYYY-MM-DD`；Timestamp 接受含秒、可选 1–6 位微秒及显式 `Z` 或 `±HH:MM` 偏移的 ISO 8601 字符串。按日历和时钟范围校验，并登记 `TEMPORAL_LITERAL_INTERPRETATION`。此规则不改变 AST，不插入转换节点，不把 Utf8 字段、数字或模糊时区文本转换成时间。
- emit 核对公开输出契约的九种 tag（ordered_records、records、evidence、paths、node_set、id_set、scalar、record、set）与实际表示、字段、元素类型、域和 revision。类型通过不证明答案或证据正确，独立 verifier 义务始终保留。
- view、共享广播、惰性读取和内存缓存报告符号别名；copy_each 与实际物化复制报告新对象。符号依赖不是已经分配的物理 buffer，更不能据此填写峰值内存。

实际测试见 `tests/test_spec001b_operators.py`、`tests/test_spec001b_predicates.py`，完整编译和跨节点/区域组合由集成测试及全验收门禁另行验证。
