# 交给 Codex 的任务文本

请执行 RCWG-BOOT-001 的目标环境导入与验收。

仓库：`https://github.com/zhixuanliu867-ship-it/RCWG`。附件为已经生成的工程 ZIP 或 Git 补丁。开发电脑 Windows + WSL2；模型调用走 API；云端候选 Google Workflows + Cloud Run Jobs + Cloud Storage；本轮 API+基础设施预算按 USD 150 规划，用户给定区间 USD 100–200。

先阅读附件中的 AGENTS.md、PROJECT_STATE.md、docs/START_HERE_zh.md、docs/SPEC_AUDIT.md 和 docs/API_ENV_AMENDMENT.md。检查真实远端与工作区；参考读取时的 main 为 `6337ff75c16ebd014bf9be7210402b8741caad0a`，但不要把它当成永远不变的当前版本。保留已有用户改动，在独立分支导入；参考文件逐字节保留。

运行只读 doctor，登记实际解释器；在 Python 3.12 下运行 unittest、rcwg_boot check、smoke、默认 mock api-probe，并确认 formal gate 返回退出码 2。已有 Docker 时构建候选镜像，使用本地 smoke 入口测试，记录基础镜像 digest、应用镜像 ID 和 Python 补丁版本。网络、软件或权限缺失时给出明确待审批项，不自行改变系统与账号。

逐条检查公开仓库范围；API key、云凭据、隐藏测试、原始模型输出、真实数据和完整未公开研究原稿保持私有。暂不选择开源许可证。保留正式六模型槽位、32 算子、72 模板、960 测试条件实例；当前 BOOT 夹具只用于工程验收。

提交独立 BOOT commit，并在写权限可用时建立 PR，main 留待审查。若 GitHub 写操作失败，返回真实错误和本地差异，不声称已有 PR。不得调用真实模型、创建付费云资源、执行 IAM 变更或配置自动部署；这些属于下一次用户批准的执行。

输出中文验收记录：每条命令、退出状态、解释器版本、成功/失败原因、变更文件、commit/PR（实际存在时）、待解决门禁。给 Work/研究负责人复核，完成本票后停止自动扩展其他工作包。
