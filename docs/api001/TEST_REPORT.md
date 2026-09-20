# API-001 工程实现与交付测试报告

日期2026-09-19；交付方Linux / Python3.13.5。LIVE请求0，GoogleCloud/IAM策略变更0。

## 已实现

新增rcwg_api：Google Cloud Vertex v1固定模型文本适配器、countTokens输入门禁、P0/P1阶段组装、严格provider解析、3+3请求限制、SQLite持久互斥预算预留、私有request/response留档、公开输入与私有recipe分离、生成前清单、源码与实际数据绑定、原样计划supervised bridge、固定分母结果、只读LIVE复核。全部为标准库，未增加依赖或改变旧代码/原参考规格。

附带目标gate、92必需方法ID、708保留ID、98 runtime源文件pin和默认关闭的MCP候选配置。实际Supervised bridge固定导入55a接口，不提供LIVE reference降级。

## 实际运行

| 检查 | 环境/结果 |
|---|---|
| API新增测试 | Python3.13.5，92/92通过，无skip/xfail；日志api-tests-release.txt |
| 全部本地可重建测试 | 较早EXEC reference基线662项 + 新92 = 754/754通过；不是最新708基线上的800 |
| API复核gate | API001_REVIEW_OFFLINE_PASS；failures=[]；真实模型请求0 |
| P0/P1 mock-wire闭环 | 真实B组装/解析；3次mock计数+3次mock生成；两个plan在显式旧reference执行回调上COMPLETED/PASS |
| 错误模型plan | unit test将实际缺filter的WorkIR交独立reference验证；保留FAIL，不替换正确计划 |
| LIVE默认门禁 | 无批准、缺pin/recipe/源证据/目标报告/凭据时阻断，CI/mock不访问真实服务 |
| MCP TOML | 使用Python tomllib语法检查；默认enabled=false；未安装或连接MCP |

92项覆盖严格JSON/编码/指数溢出，HTTP错误/重定向/凭据脱敏，未知usage与thoughts计费，固定参数/端点，预算并发/重启/重复预留/超限/不退款，P0/P1阶段，公开输入canary，失败固定分母，响应写盘失败仍保留dispatch，private recipe/数据在凭据访问前绑定，mock不能伪装为LIVE，以及归档篡改。

## 尚待目标验收

- 当前55a完整受监督执行器上的原708+新92，WSL3.12.14和独立CI。
- 实际gcloud/服务账号/OAuth及Google模型可调用性、HTTP/usage/modelVersion真实性。
- 所有者1美元、global、精确project/SA的批准；第一个3+3 LIVE pilot及其只读复核。
- 真实账单（未提供则null）。

本次pure-additive补丁只做了可重建reference基线上的干净应用及新增字节/tree核对，没有生成55a+API的最终tree证明。最终目标tree和目标原始日志由Codex交付。不能将本报告的REVIEW通过改名为TARGET或LIVE通过。

## 当前交付状态

API工程实现可导入；`API001_REVIEW_OFFLINE_PASS`。`API001_TARGET_OFFLINE_PASS`与`API001_LIVE_F1_ENGINEERING_ACCEPTED`尚未成立；formal_ready=false。当前新增文件/交付清单和补丁证明见包内PATCH_PROOF.json与SHA256SUMS.txt。
