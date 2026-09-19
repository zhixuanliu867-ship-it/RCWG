# RCWG

## RCWG-BOOT-001 · 仓库与环境交付包

**当前状态：工程包已生成；等待用户 WSL2、Python 3.12、容器及云端验收。**

开发端采用 Windows + WSL2；模型推理采用 API；本轮推荐 Google Cloud Workflows + Cloud Run Jobs + Cloud Storage。BOOT 核心工具仅依赖 Python 标准库，默认使用 mock，目标解释器为 Python 3.12。目标系统中的补丁版本、镜像 digest 和云项目在验收后登记。

从 `docs/START_HERE_zh.md` 开始。第一步只运行只读环境检查：

```bash
python3 scripts/doctor.py runs/wsl-doctor.json
```

获得批准并准备好目标解释器后，在仓库根目录运行：

```bash
python3.12 -m unittest discover -s tests -v
python3.12 -m rcwg_boot check
python3.12 -m rcwg_boot smoke
python3.12 -m rcwg_boot api-probe
```

最后一条命令默认 mock，真实模型请求数为 0。`check --formal` 应退出码 2，状态 `BLOCKED_NOT_FROZEN`。

### 目录

| 路径 | 作用 |
|---|---|
| `AGENTS.md` / `PROJECT_STATE.md` | Codex 约束、验收状态与交接入口 |
| `rcwg_boot/` / `tests/` | 只读诊断、完整性检查、固定冒烟夹具、手工 API 探针和单元测试 |
| `specs/reference_v1_0/` | 原始机器规格，25 个文件逐字节保留 |
| `prompts/v1_1/` | 最新表达版提示词，8 个文件逐字节保留 |
| `provenance/SOURCE_INVENTORY.json` | 两份源归档及每个成员文件的 SHA256；覆盖范围明确 |
| `configs/boot.json` | BOOT 默认约束、预算分配和待验收项 |
| `infra/gcp/` | 单次 mock 工作流 YAML、Job 模板、清理步骤 |
| `docs/` | 操作卡、成本、环境变更、规格差异、Codex 指令、验收记录 |

### 研究配置的延续

原有正式设计保留 6 个生成模型槽位、32 个算子、72 个模板、960 个冻结测试条件实例及其运行矩阵。`specs/reference_v1_0/configs/campaign.json` 保存原始数目；本轮不会把这些改成小规模研究方案。

BOOT 的固定 top-k 夹具用于检查执行、验证、散列和归档。它不实现 WorkIR 执行器，不生成正式实验成绩。完整 C++/Arrow 算子、控制区域、独立验收与资源计量继续按原工作包建设。

API 更改登记于 `docs/API_ENV_AMENDMENT.md`。云工作流负责外层提交和归档；正式 WorkIR 内部调度继续由统一执行器负责。远端模型 GPU/CPU/显存字段保留 `null` 和不可观测标记。

### 隐私与发布

密钥、账号凭据、真实运行结果、隐藏测试和完整研究原稿保存在私有位置。本仓库保留机器规格、提示词草案及教学样例；推送前由研究负责人审核公开范围。暂不自动授予开源许可证。

### SPEC-001B：完整静态契约与离线验收

`rcwg_spec.compiler.validate_workflow(task, plan)` 校验全族公开输入、32 算子／56 实现的参数与类型、控制区域和资源／生命周期义务。`IR_VALIDATED` 表示静态契约通过；执行内核仍为 `NOT_IMPLEMENTED`，正式门禁仍关闭。

在已有 WSL 环境使用固定解释器，所有输出路径必须是新的：

```bash
bash scripts/accept_spec001b.sh
uv run --offline --frozen --python 3.12.14 python -m rcwg_spec validate-public-task specs/spec001b/examples/public_F6.json
uv run --offline --frozen --python 3.12.14 python -m rcwg_spec validate-workflow \
  --task specs/reference_v1_0/examples/task_input.json \
  --plan specs/reference_v1_0/examples/workflow_topk.json \
  --output runs/spec001b-manual/typed-report.json
```

完整验收脚本检查固定的真实测试 ID 集合、每个实现分支的合法／非法／dispatch 测试、未改动的 27 个哨兵、六项隔离源码突变、受测字节与暂存树一致，以及原件与正式门禁。通过状态为 `SPEC001B_OFFLINE_GATES_PASS`；最终交付还需独立 CI、补丁 clean apply/tree 和交付文件证明。单独 `rcwg_spec check` 保留 SPEC-001A 的历史 profile；完整 B 以新脚本为准。

P0/P1 组装与私有归档接口见 `docs/spec001b/GENERATION_AND_BINDING.md`；实际契约规则见 `OPERATOR_CONTRACT_NOTES.md`。EXEC-001 对接入口见 `docs/spec001b/EXEC-001_INTERFACE.md`。`runs/` 日志和原始响应保持私有；六族示例均为 `BOOT_ONLY` 工程夹具。
