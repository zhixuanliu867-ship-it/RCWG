# 本轮复核与 SPEC-001B 起始包测试报告

日期：2026-09-19。测试环境：交付方 Linux / CPython 3.13.5。目标用户 WSL / Python 3.12.14 的 A 验收日志已核实；本次新增B代码的目标环境验收由Codex执行。

## A 独立复核

| 项目 | 实测 |
|---|---|
| 4附件清单SHA256 | 全通过 |
| 干净基线应用A最终补丁 | tree e09ee3a93b46192d3e88775fda5e24bade771f4d，与远端6afd484一致 |
| 27受测代码文件hash | 全通过 |
| 20 WSL记录、1 CI日志hash | 全通过 |
| 原A单测 | 131方法通过 |
| 14个Codex回归方法放回原117版本 | 23个失败子用例成功复现 |
| BOOT/SPEC/smoke/mock/public guard | 通过 |
| formal | BLOCKED_NOT_FROZEN / 2 |

## B 起始代码

| 项目 | 实测 |
|---|---|
| ir_structure.py/identity.py新增单元测试 | 63方法通过 |
| 所有回归 | 194=131+63方法通过 |
| 原件数量/哈希 | 33文件；32算子；72模板不变 |
| 编译检查与bash语法 | 通过 |
| 暂存字节 public guard | 通过，仍属于模式/路径检查而非完备安全证明 |
| 完整编译器哨兵入口 | BLOCKED_IMPLEMENTATION_GAP / 2；compiler.py不存在；tested_cases=0 |
| 完整SPEC-001B | IN_PROGRESS，未宣称完成 |
| 正式运行 | formal_ready=false，门禁保留 |

本起始包新增27个完整编译器集成哨兵（JSON用例+独立runner），这27个用例当前尚未在完整编译器上通过。它们也不替代全部32算子、56已登记实现分支、控制/类型/P0-P1/身份集成验收。

新模块仅从本地冻结注册表读公开设计，不调用模型、不读真实任务数据、不产生付费资源。代码中未实现的计量没有填入实测数。

## 交付验证

补丁和文件覆盖集基于已审A内容，原A代码与参考原件保持不变。在新的干净副本中应用补丁、核对Git tree并重跑194项测试，结果以最终补丁复核记录为准。最终复核结果/散列保存在包外 `补丁复核.json` 和ZIP内 `PATCH_VERIFICATION.json`，避免把自身tree递归写回自身造成循环散列。

来源、命令、退出码、受测代码manifest、131/194两套原始输出分别放交付包 `evidence/review`、`evidence/foundation`。未生成或宣称任何真实模型/云/计量实验数据。
