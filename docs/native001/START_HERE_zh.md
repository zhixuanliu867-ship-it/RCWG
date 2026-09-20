# 当前票：RCWG-NATIVE-001

从已审 CLOUD head 9739bf229843a333f29ce6f166e52e7e12fdd8db 承接，PR #6 尚未合并。
本票使用 rcwg/native-001，草稿 PR 以 rcwg/cloud-001 为 stacked base；不合并任何 PR。
先读 SCOPE.json、INTERFACE.md、DECISIONS.md。N1/N2/N3 连续开发并分项验收，无阶段人工审批。
WSL 仓库 /home/zhixuan/projects/RCWG；所有 WSL 验收使用
`uv run --offline --frozen --python 3.12.14 python ...`。
每次使用全新 runs 子目录，拒绝 symlink，不覆写或删除旧证据。
新源码只在 native001/、rcwg_native/、specs/native001/ 和新增测试/脚本；历史规范与 pins 保留。
新增模型/count/GCP Cloud Build/Job/Workflow/IAM/安装/cgroup 写入授权均为零。
缺少编译器与主机委派不阻塞源码、状态机与独立测试设计；剩余事项统一交付 HOST_CHANGE_PLAN。
