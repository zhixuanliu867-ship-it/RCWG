# N4 当前入口

使用 scripts/accept_native001_n4.py 独立门禁；保留原四个accept入口和Windows12。
审批前只做FakeFS、微型进程异常测试、二进制拒绝测试和原已批准原生回归。
新校准CPU/内存/OOM/后代负载不得直接启动。

最终私有交付中的 N4_OWNER_CHANGE_PLAN.json 是唯一待批准主机计划。
其 approved=false 保留不动；收到明确批准后另存私有 OWNER_APPROVAL_RECEIPT.json，
字段见 plan.receipt_required，绑定文件全SHA256和具体有效时间。此文件当前不存在。
systemd启动/停止/只读协调命令均由该计划给出，sudo由业主交互完成。
首次不满足适用性即终止；服务声明最多1次，不得重新启动同一claim。

运行数据、私有gold、全量日志和receipt只在忽略的runs目录。EXPECTED_MANIFEST保存所有
888槽位；缺日志为UNKNOWN，有计划未启动为NOT_RUN；不缩小分母、不自动补跑。
报告必须把离线通过和真实C01–C10校准分开。旧HOST_CHANGE_PLAN不授权此批。
