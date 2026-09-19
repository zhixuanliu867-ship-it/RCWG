# 来源和实施状态

本票不重新调研模型/价格。用户当前验收文件与GitHub实际提交构成A复核依据。旧规格按provenance中的原件散列定位；新术语和端口细节明确登记为B实施决定。

- PR2: https://github.com/zhixuanliu867-ship-it/RCWG/pull/2
- reviewed commit: https://github.com/zhixuanliu867-ship-it/RCWG/commit/6afd48490094d716dc65cf84fe822e45216fcac3
- CI: https://github.com/zhixuanliu867-ship-it/RCWG/actions/runs/35436480656
- formal design document v1.1 §6.4: region最多嵌套两层、bindings/nodes/yield、有限AST、全局实例4096；当前B显式选择$bound词法语法。
- Python3.12 JSON官方文档：https://docs.python.org/3.12/library/json.html 。重复键/非有限数的默认处理需要显式收紧；本包严格解析与测试为实际依据。
- JSON Schema官方文档：https://json-schema.org/understanding-json-schema/reference 。类型/字段/schema检查不替代本项目的算子统一、依赖和资源语义检查。

版本说明：原TaskInput/WorkIR研究协议仍1.0；新增B工作清单为0.1。工作清单含设计状态，不声称已实现32个可执行契约。正式门禁与经济成本不变。
