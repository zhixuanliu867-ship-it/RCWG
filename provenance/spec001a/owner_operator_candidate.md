| operator | input_type → output_type | implementations | parameter_fields | contract_status（候选） | 备注/前置条件 |
|---|---|---|---|---|---|
| scan | Table → Stream[Record] | sequential, index_range | source, columns, predicate | VALIDATED_CONTRACT* | 不自动下推新谓词 |
| filter | Stream[Record] → Stream[Record] | vectorized, scalar | predicate | VALIDATED_CONTRACT* | 三值逻辑；false≠unknown |
| project | Table\|Stream → Table\|Stream | column_view, copy | columns | VALIDATED_CONTRACT* | view 存活期计费 |
| join | Table\|Stream,Table\|Stream → Table\|Stream | hash, sort_merge, block_nested | keys, join_type, build_side | VALIDATED_CONTRACT* | null/重复键/外连接语义固定 |
| aggregate | Table\|Stream → Table | hash_group, sorted_group | group_by, aggregates | VALIDATED_CONTRACT* | 空值/浮点容差在任务契约声明 |
| deduplicate | Table\|Stream → Table\|Stream | hash, sort_unique | keys, keep | VALIDATED_CONTRACT* | 保留规则确定；禁止漏读去重 |
| sort | Table\|Stream → Table | in_memory, external_merge | keys | VALIDATED_CONTRACT* | 外排临时文件 I/O 计费 |
| top_k | Table\|Stream → Table | full_sort, streaming_heap | k, keys | VALIDATED_CONTRACT* | 精确 top-k；并列规则明确 |
| set_op | Set,Set → Set | hash, sorted_merge | mode | VALIDATED_CONTRACT* | union/intersection/difference |
| graph_neighbors | Graph,NodeSet → EdgeStream | csr, indexed_adjacency | direction, edge_types | VALIDATED_CONTRACT* | 方向/关系类型/时间过滤不可省 |
| graph_reachability | Graph,NodeSet → NodeSet | bfs, dfs | max_hops, direction | VALIDATED_CONTRACT* | DFS 不得伪称最短跳数 |
| graph_shortest_path | Graph,NodeSet → PathSet | bfs, dijkstra | target, weight_field | VALIDATED_CONTRACT* | BFS 仅等权；Dijkstra 非负权 |
| graph_filter | Graph → GraphView | edge_mask, index_filter | predicate | VALIDATED_CONTRACT* | 只提供视图；扫描/物化有日志 |
| graph_subgraph | Graph,NodeSet → Graph | induced, edge_selected | mode | VALIDATED_CONTRACT* | 两种语义不混用 |
| read_documents | DocumentIndex,IDSet → DocumentStream | batched, per_document | fields, batch_size | VALIDATED_CONTRACT* | 读正文才计费；元数据无隐藏答案 |
| text_retrieve | DocumentIndex → RankedIDSet | bm25, dense_fixed | query, limit | VALIDATED_CONTRACT* | 近似候选无全集召回保证 |
| split_documents | DocumentStream → ChunkStream | section, token_window | size, overlap | VALIDATED_CONTRACT* | 边界与 span 映射保留 |
| gather_context | ChunkStream → ChunkStream | neighbors, section_header | window | VALIDATED_CONTRACT* | 额外上下文计费；禁隐藏定位器 |
| semantic_extract | DocumentStream\|ChunkStream → EvidenceTable | fixed_e0 | field_schema, context_budget | BLOCKED_UNDEFINED | 依赖固定 E0/API 协议冻结（OD 见 §6） |
| evidence_merge | EvidenceTable → EvidenceTable | by_entity, by_document | keys, conflict_policy | VALIDATED_CONTRACT* | 冲突不可取第一条；来源保留 |
| evidence_validate | EvidenceTable,DocumentIndex → EvidenceTable | span_check | strict | VALIDATED_CONTRACT* | 只验证引用与公开规则，不访问 gold |
| materialize | Stream → Table | memory, disk | format | VALIDATED_CONTRACT* | 持久对象按生命周期收费 |
| stream_read | ArtifactRef → Stream | arrow_batches | batch_size | VALIDATED_CONTRACT* | 所有读取走计量代理 |
| broadcast | ArtifactRef → ArtifactRef[] | shared_ref, copy_each | consumers | VALIDATED_CONTRACT* | 零复制不抹去后续读取 |
| release | ArtifactRef → ControlToken | explicit | artifact | VALIDATED_CONTRACT* | 禁释放仍被下游使用的对象 |
| cache | ArtifactRef → ArtifactRef | memory, disk | key_fields | VALIDATED_CONTRACT* | 仅同次运行合法复用；跨运行缓存关闭 |
| map | Stream → Stream | bounded_map | subworkflow, max_concurrency | VALIDATED_CONTRACT* | 有限输入、实例上限、批次日志 |
| branch | Scalar → Choice | predicate_branch | predicate, then, else | VALIDATED_CONTRACT* | 只执行所选分支 |
| loop | State → State | bounded_loop | body, condition, max_iterations | VALIDATED_CONTRACT* | 到上限不是成功 |
| collect | Stream → Table | bounded_collect | limit | VALIDATED_CONTRACT* | 截断需任务允许 |
| emit | Table\|EvidenceTable\|PathSet → Result | json_artifact | output_contract | VALIDATED_CONTRACT* | 结果必须 artifact 化 |
| stats | DatasetRef → Stats | metadata, sample | fields, sample_size | VALIDATED_CONTRACT* | 仅探测轨生成阶段可调用，计入成本 |

> `*` 表示：**在 OD-04（类型 lattice）确认前，这只是候选**；`contract_status` / `implementation_status` 最终由研究负责人裁定。`implementation_status` 对 BOOT 一律为「设计资产、未实现」（对应 SPEC_AUDIT D06），逐行标 `NOT_IMPLEMENTED`。
