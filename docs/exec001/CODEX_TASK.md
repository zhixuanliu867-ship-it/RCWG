# RCWG-EXEC-001 — Codex 开工任务

## 0. 已作出的审查决定与合并授权

用户已经授权研究/工程常规决定。本轮已独立核查 SPEC-001B：提交 `a1f65120ef0b2b8e1fb6f1c31224244d6f7ee16b`（tree `5b1b7cd587bbb3df54952ea24eb6841767a1e0bd`）可作为静态协议阶段验收基线。A 的已审提交是 `6afd48490094d716dc65cf84fe822e45216fcac3`。允许按此精确内容先合并 #2，再将 #3 ready 并合并。本条就是该两项审查内容的合并批准，**不再等待一条重复的用户确认**。

开始时实时读取 PR状态、head、CI，fetch本地仓库确认。只在 head 匹配上述SHA、对应CI成功、无未审变化/冲突时执行。采用 merge commit 保留先后关系，不用force/reset/clean、squash或管理员绕过门禁。参考命令（条件检查通过后）：

```bash
gh pr merge 2 --repo zhixuanliu867-ship-it/RCWG --merge --match-head-commit 6afd48490094d716dc65cf84fe822e45216fcac3
gh pr ready 3 --repo zhixuanliu867-ship-it/RCWG
# 重新核查当前 #3 head / mergeability / checks；必要时等该次独立CI结果。
gh pr merge 3 --repo zhixuanliu867-ship-it/RCWG --merge --match-head-commit a1f65120ef0b2b8e1fb6f1c31224244d6f7ee16b
```

这轮 ChatGPT 集成实际调用合并 #2 得到 HTTP403，未改远端。使用用户已有、已授权的本机 Git/GitHub CLI 登录；不要请求将 Token 明文发到聊天、日志或文件。若该通道确实无写权限，保留状态并基于已审 B 开始 stacked 开发，单独记 BASELINE_MERGE_PENDING；不要让参考实现停在重复等确认的循环。最终整票合并前仍要补齐基线。若 head 超出本次已审内容，则停下涉及该差异的合并并报告，不能把本授权扩大到任意新提交。

## 1. 导入与首个验收

读取 AGENTS.md、docs/spec001b/EXEC-001_INTERFACE.md、本包 DECISIONS.md/ACCEPTANCE.md。
从已含已审 B 的 main 建 `rcwg/exec-001`；若权限阻断则从上述 B SHA建同名独立分支并登记其stacked基线。补丁相对已审 B，仅新增 reference代码/测试/工作规范和追加状态段；不重复应用A/B补丁。先 `git apply --check`，通过后apply；已有同名修改要比对，不能覆盖用户工作。

暂存新增代码以绑定受测字节，运行：

```bash
bash scripts/accept_exec001_reference.sh
```

该脚本沿用 uv offline/frozen Python3.12.14，无安装/真实API/云。目标是旧585 + 新77 = 662测试全部通过。原始B完整入口 `scripts/accept_spec001b.py` 和原27哨兵、六突变也在3.12.14复跑；不得取消解释器约束伪造通过。当前包交付方为3.13.5，其reference证据不代替用户3.12.14或CI。

## 2. 三个实现提交

**E1 — 实际runner与监督器。** 保留本包已工作的 scan/filter/top-k/project/emit、独立verifier和profile错误归因。每次run独立子进程，父进程冻结expected、监督真实deadline与清理。使用可信input注册；kernel执行只读typed WorkIR/注册句柄。不启用Docker/GCP，不写未授权cgroup；RAM保持未知。记录实际源读取、队列/ready/运行/结束与异常；新worker源码必须纳入散列。允许整理内部代码，只要原测试和完整行为仍保持。

**E2 — artifact/事件持久化和生成集成。** 引入durable journal和封存/重读验证；任何跨context/plan/data/artifact混绑都拒绝。独立verifier与runner计算/资源分账。P0/P1使用B的真实mock组装与解析模块，通过已有compiler后执行F1；不将固定plan从旁路直接替换模型返回值。静态失败、设施gap、wrong output、timeout、cancel、worker crash各留对应attempt与原因。关闭真实请求，formal=false。

**E3 — 完整验收与交付。** 按ACCEPTANCE X00-X15实施；收集真实WSL/CI、命令、退出码、日志、源sha、受测tree、profile覆盖矩阵。保留585+77个原方法及其测试字节/已有负例；新增worker/crash/manifest/metadata/timeout/generation反例先复现再修。另设`accept_exec001.py`完整门禁，REFERENCE_CORE脚本继续只描述原子检查点，不改名假装所有设施完成。

## 3. 研究/范围约束

本票目标明确为 F1 reference engineering closure，native C++20/Arrow、公平效率、独立cgroup计量与云部署各待对应门禁；不要用这一Python实现替换正式研究路线。不要一口气把32个算子都改成简化Python stub。不允许eval、任意shell或依据模型URI读宿主文件。新真实来源仅开发合成数据；隐藏gold不进入请求。原33参考文件、72模板、6模型槽、主矩阵和三项主要比较都保持。

本包select_topk两条路径必须保持真实选择；不能将streaming_heap替换为sorted[:k]，也不能把full_sort改成堆来让内存图更好看。prototype filter:vectorized是显式bounded-batch mask Python reference，不伪称SIMD。row/frame/object计数与物理内存/复制字节必须分列。

## 4. 成功交回的文件

最终可读报告；DELIVERY_EVIDENCE.json；独立 WSL_EVIDENCE/CI_EVIDENCE 与私有原始日志；FINAL.patch；SHA256SUMS；PATCH_PROOF；实际runtime profile/dispatch/obligation/testID覆盖矩阵；固定expected案例清单；真实correct/incorrect/timeout/crash结果摘要；NEXT_GATE.md（API小规模接入与native/计量待办，分别列实际依赖）。

最终状态 `EXEC001_F1_ENGINEERING_ACCEPTED` 仅在X00-X15满足时使用；权限阻断流程和未完成技术项分列。runtime_coverage=5 operators/8 reference branches，完整WorkIR runtime未支持项真实保留，formal=false。交回后由独立审查再决定API-001与计量校准进入条件。
