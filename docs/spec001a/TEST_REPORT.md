# SPEC-001A 实际验收报告

日期：2026-09-19。状态：REVIEWER_OFFLINE_PASS。

## 基线

GitHub main 实际读取为 `08b1ecff33ab01098926e3dceba64ab6ab4fa02c`；其 tree 为 `6d67ecfd99a1f6b6db317bcea837d866e9f1d1a8`。本地依据原 BOOT 包与连接器读取的收尾文档重建，Git tree 精确一致。用于补丁审查的本地 baseline commit 是工作副本提交，不冒充 GitHub 上游提交。补丁按相同文件基线生成。

## 实际运行

执行位置：交付方 Linux / Python **3.13.5**，不代表用户 WSL 或目标 Python 3.12.14。

| 检查 | 结果 |
|---|---|
| unittest discover | **117/117 PASS**；原43项 + 新74项 |
| BOOT check | BOOT_CHECK_PASS；33参考文件、32算子、72模板 |
| BOOT smoke | PASS，固定工程夹具 |
| BOOT api-probe | PASS，mock，真实请求0 |
| BOOT check --formal | BLOCKED_NOT_FROZEN，退出码2（预期） |
| SPEC check | SPEC001A_CORE_PASS |
| F1 TaskInput示例 | 有限profile校验通过 |
| Synthetic metric fixture | 完成三个人工账本条目的归约；全部标ENGINEERING_ONLY |
| public guard | PASS；仅已有模式/路径guard，不构成完整秘密审计 |
| Python compileall | PASS |
| 本机accept脚本bash语法 | PASS；未在交付方伪装运行uv目标3.12.14 |
| 补充JSON Schema审查 | 2个schema元验证、1个F1样例、6个measurement样例通过 |

补充 JSON Schema 检查使用交付环境已安装的 jsonschema，精确版本见 `evidence/spec001a/schema-supplementary.json`；项目仍为标准库核心，未增加第三方运行依赖、未改uv.lock。补充检查不代表完整类型/WorkIR语义验证。

新测试覆盖：严格JSON及布尔/NaN数值边界、输入白名单与隐藏字段反例、单位/scope、预算三值判定、OOM/超时与缺测、manifest分母和重复、候选覆盖、分层权重、物理buffer重叠/别名、重复字节事件、任务证据见证集/限定词与恢复、只读cgroup字段及CPU计数重置。部分测试含固定seed的多组子用例，报告的117是unittest方法数，不把子用例另充总数。

## 代码能力边界

已实现F1 TaskInput有限profile与计量归约核，尚未完成全TaskInput/WorkIR编译器、全部算子执行器、自动事实判真、正式统计推断和全量计量采集器。

`cgroup-probe`仅读已存在目录，不创建cgroup、不修改CPU/RAM限制。其通过夹具测试不等于真实隔离已校准。所有正式准备标志继续false。

## 远端和费用

创建 `rcwg/spec-001a` 的连接器动作实际返回HTTP403。没有创建新远端分支/提交/PR，没有合并或修改main。交付形式为可审查补丁和完整工作树包。

本轮真实模型请求0、云资源创建0、IAM变更0。真实API/容器/GCP/正式Linux计量门禁继续待执行。

## 证据

各命令stdout/stderr、退出码和SHA256在 `evidence/spec001a/`；总记录 `TEST_REPORT.json`。分发归档校验见交付根文件，原BOOT的SHA256SUMS属于历史交付，不用于声称修订工作树是原件。

## 用户目标环境验收

补丁导入后在仓库根目录运行 `bash scripts/accept_spec001a.sh`。脚本使用现有uv、本地缓存和Python3.12.14，保存独立run目录；缺解释器/依赖时明确失败。它不联网安装、不调用模型、不操作云权限。新提交的GitHub CI仍需真实运行后才填写通过。
