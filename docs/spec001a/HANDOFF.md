# SPEC-001A 导入与 SPEC-001B 开工卡

## 当前决策

本轮协议、算子语义澄清和计量补充已由研究协作者根据用户授权决定。无需再次逐条确认设计。正常流程是：应用检查点代码→目标环境验收→提交PR→推进完整静态验证器。

核心保持RCWG原32算子、72模板、6模型槽、P0/P1与原正式矩阵；云/API费用和IAM保持独立批准。下一票实现不能为了“全通过”静默忽略未知类型、scope或resource字段。

## 手动导入（继续使用已跑通的Git方式）

以下命令在现有RCWG仓库根目录运行。先设置PATCH为下载文件在WSL中的实际路径。`git status --short`应为空；若有未提交更改，先保留并处理，不使用reset/clean或覆盖。

```bash
PATCH="/请替换为补丁的实际路径/RCWG-SPEC-001A.patch"
test -f "$PATCH"
git status --short
git switch main
git pull --ff-only
git switch -c rcwg/spec-001a
git apply --check "$PATCH"
git apply "$PATCH"
bash scripts/accept_spec001a.sh
```

补丁基线是main `08b1ecff33ab01098926e3dceba64ab6ab4fa02c`。若main已进展，先让`git apply --check`检查，不强行覆盖。成功验收会输出`OWNER_SPEC001A_ACCEPTANCE_PASS`及run目录，单测预期117项。

审查本次变更，再仅添加下列路径（runs保持私有，不入库）：

```bash
git diff --stat
git add .github/workflows/ci.yml AGENTS.md PROJECT_STATE.md configs/boot.json   rcwg_spec tests/test_spec001a.py scripts/accept_spec001a.sh   specs/spec001a docs/spec001a provenance/spec001a evidence/spec001a
git diff --cached --name-only
git commit -m "RCWG-SPEC-001A: approve metrology contracts and add offline scoring core"
git push -u origin rcwg/spec-001a
```

在GitHub建立该分支至main的PR，将以下摘要填入描述：目标Python版本、117项测试结果、BOOT/SPEC check、formal退出码2、实际run目录及脱敏日志hash、真实API请求0、云/IAM动作0。CI完成后合并，随后进入SPEC-001B。此前本地state已保留历史；新增真实状态采用带日期追加。

## 可直接交给工程实现助手的 SPEC-001B 指令

你正在 `zhixuanliu867-ship-it/RCWG`。读取AGENTS.md、PROJECT_STATE.md以及docs/spec001a/SPEC-001_DECISIONS.md、METROLOGY-001.md、CLAIMS_AND_FALSIFICATION.md；这些设计已获当前授权，不再以逐条批准阻塞实施。

从包含SPEC-001A且验收通过的main创建独立分支rcwg/spec-001b。保持specs/reference_v1_0与prompts/v1_1逐字节不变；新增规范与兼容层放独立版本目录。已有117项测试必须继续通过。代码语言/依赖保持与项目一致；需新增依赖时建立真实锁文件并记录新增原因。

交付完整静态验证器：

1. 以现有TaskInput F1 profile为开始，扩展正式任务族所需输入/输出契约，实现公开字段组装、P0/P1消息阶段接口与私有gold隔离；样例标明来源和工程scope。
2. WorkIR JSON/schema、唯一节点、数据/控制引用、区域bindings/yield、受控map/branch/loop、任务ID、算子实现与端口、参数、类型代数、静态资源上限。数据相关前置条件登记为运行时义务；compiler保留生成者的算法与调度选择。
3. Table/Stream/Ref/GraphView按批准的类型规则检查；转换必须显式且计量。所有32项建立契约覆盖矩阵；设计资产和实际kernel状态继续分开。未实现特性返回IMPLEMENTATION_GAP，不将设施缺口当作模型错误。
4. 规范化与原始计划hash分列；不得在主协议中偷偷修复JSON、选择更好算法或自动重试生成。错误提供稳定code、stage和字段位置，原始响应私有留档。
5. 扩展reference/measurement/event schemas绑定data/plan/budget/runtime/cache与source IDs，冻结expected manifest。OTel仅镜像权威账本；未实现采集项保留清楚状态。
6. 新测试映射每条规则：原top-k与sort示例、类型/引用/作用域正反例、有界控制体、资源限制、候选覆盖、gold canary、重命名不变性、规范化确定性。完整校验器不得“仅enum有32项”就声称已支持32算子。

完成后交付补丁/PR、实际测试日志、剩余实现缺口以及EXEC-001接入接口。本阶段仅本地mock；不部署云、不发真实模型请求、不修改IAM、不解除正式门禁。常规工程修订直接实现并登记。涉及正式科学问题、主矩阵或费用/权限的实质变更单列，不用未核实的通过状态代替决定。

## 下一计算闭环

SPEC-001B后启动EXEC-001：读取真实WorkIR，按声明的scan→filter→top_k→project→emit执行F1；top_k的full_sort与streaming_heap共享语义契约，输出独立验证，资源/事件接入本轮账本。随后API-001做首次真实模型接入，CLOUD-001承接延期的目标容器/GCP验收。
