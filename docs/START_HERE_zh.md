# RCWG-BOOT-001 · Windows / WSL2 操作卡

## 1. 当前先做什么

先取得本机只读检查报告。此步骤只需要 WSL 中已有的 `python3`，不访问模型 API、不连接云账号、不安装软件，也不要求本地 GPU。检查脚本兼容常见 Python 3.8+；BOOT 正式开发目标仍为 Python 3.12。

在 Windows 解压工程 ZIP，找到包含 `README.md`、`scripts/`、`rcwg_boot/` 的 `RCWG-BOOT-001` 文件夹。使用资源管理器进入该文件夹，右键“在终端中打开”，在 PowerShell 输入：

```powershell
wsl
```

进入 WSL 后运行：

```bash
pwd
python3 --version
python3 scripts/doctor.py runs/wsl-doctor.json
```

预期终端出现 `COLLECTED`。退出 WSL 后，可在刚才解压的 Windows 文件夹中找到 `runs/wsl-doctor.json` 并发回。报告收集 OS/WSL、解释器、CPU 数量/亲和数、RAM、cgroup 字段以及工具可用性；不收集主机名、IP、用户名和 API key。文件采用独占创建；已有同名报告时换成 `runs/wsl-doctor-02.json`。

`python3: command not found` 时先返回该错误；由下一次目标环境任务明确批准安装，不连续尝试 sudo 脚本。`can't open file` 表示当前不在工程根目录，先核对 `pwd` 与 `ls scripts`。

本次临时在 Windows 解压目录运行诊断即可。正式开发建议把 Git 工作副本放在 WSL Linux 文件系统，例如 `~/projects/RCWG`；代码、虚拟环境与运行文件统一在这个副本中。

## 2. 将工程加入 GitHub：交给 Codex 的路线

在能够访问该 GitHub 仓库的 Codex 会话中，附上工程 ZIP 或补丁，粘贴 `docs/CODEX_HANDOFF.md` 的任务文本。当前 ChatGPT GitHub 集成读操作成功，创建分支和 Issue 返回 403；这不会阻止你使用自己的 Git/Codex 授权导入。

Codex 必须先检查真实远端状态、工作区改动与公开范围，再导入独立分支；完成检查后建立 PR，保留 main 待审。软件安装、云服务开通、IAM 变更和付费 API 调用分别确认。

## 3. 手工导入补丁（已有 Git 时）

以下命令在 WSL 中执行。把 `BOOT_PATCH` 改成下载补丁的真实 WSL 路径；路径必须指向 `.patch` 文件。已经有仓库时直接进入已有仓库，跳过 clone，保留未提交改动。

```bash
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/zhixuanliu867-ship-it/RCWG.git
cd RCWG
git status --short
git log -1 --oneline

# 示例占位符：先替换为自己的实际路径。
BOOT_PATCH='/mnt/c/Users/你的Windows用户名/Downloads/RCWG-BOOT-001.patch'
git switch -c rcwg/boot-001
git apply --check "$BOOT_PATCH"
git apply --index "$BOOT_PATCH"
```

若 `git apply --check` 失败，保存错误并由 Codex 对比当前版本进行合并。不要用强制覆盖、reset 或清空仓库来“修复”。分支已经存在时，核对分支内容后使用新的唯一分支名。

本包的代码没有 pip 运行依赖。已有 Python 3.12 时直接验收：

```bash
python3.12 -m unittest discover -s tests -v
python3.12 -m rcwg_boot check
python3.12 -m rcwg_boot smoke
python3.12 -m rcwg_boot api-probe
python3.12 -m rcwg_boot check --formal
# 最后一条预期返回 BLOCKED_NOT_FROZEN，退出码为 2。
python3 scripts/check_public_tree.py
git diff --cached --stat
```

Python 3.12 缺失时先完成环境报告。若你批准在用户目录安装 uv/解释器，按官方 uv 安装指引完成后运行 `uv python install 3.12`、`uv sync --frozen`，并把上述 `python3.12` 替换成 `uv run --frozen python`。这属于目标环境安装步骤，默认诊断不会执行它。

研究负责人确认待公开的规格、提示词和样例后，再执行提交与推送：

```bash
git commit -m 'BOOT-001: repository and API/cloud environment scaffold'
git push -u origin rcwg/boot-001
```

若 `git commit` 提示未配置作者，使用你自己的 Git 姓名与邮箱配置；若 push 无权限，使用你的 GitHub 授权流程。凭据不应发到对话、写入代码或添加到提交中。

## 4. 预期验收结果

单元测试通过；`check` 返回 `BOOT_CHECK_PASS`，校验 33 个参考文件、32 个算子卡与 72 个模板；`smoke` 返回 `PASS` 并在 `runs/boot-.../report.json` 生成固定夹具结果；默认 `api-probe` 真实请求数为 0。正式门禁保留 `BLOCKED_NOT_FROZEN`。

当前交付方测试运行在 Linux / Python 3.13.5，目标 WSL/Python 3.12 尚待你验证。Docker 构建、真实云端执行、真实 API 调用分开登记；某一层通过不替代其余层。

## 5. 云端与 API 什么时候开始

完成本机和仓库验收后，再按 `docs/GCP_RUNBOOK.md` 处理 Google 项目、账单、身份权限和一次 mock 云执行，首次云端验收预算建议 USD 5 以内。API 探针步骤见 `docs/API_PROBE.md`，先核实提供商、具体模型、地域、价格和账户权限。

本次只需先返回 `runs/wsl-doctor.json`。项目 ID、云区域、模型与账单配置在下一门禁集中登记，API key 留在你自己的机器或云密钥管理中。
