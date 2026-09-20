# 下一步业主动作（当前不执行）

N0–N3 的开发和验收不再需要分阶段确认。剩余的实际隔离与计量校准属于 N4，
详见 HOST_CHANGE_PLAN.json；该单初始 approved=false，没有在本票执行。

最小主机前提是一次有明确退出上限的 systemd transient service：只在它自己的子树下委派
cpu/memory/io，保留现有系统 Python、WSL 网络、Docker、用户服务与所有云账号设置。
本地现有用户委派只有 cpu/memory/pids，所以当前不能把 io.stat 预算计量宣称为就绪。
系统编译器安装没有纳入必需项：已验明的 CI 二进制可在 WSL 执行。

变更单中的第一条命令只检查这种临时委派能否提供所需 controller，结束即回收 service。
它不会创建测量 run 组、不会执行 OOM 负载，也不会授权随后未冻结的校准批次。
真正 N4 校准开始前，先按下一阶段接口卡准备精确 workload、run manifest 和看门狗；
这些源码/运行数尚未验收，不能把批准主机前提写成校准 PASS。

继续保持 PR #6/#7 草稿/未合并状态，不使用旧 pilot 或 CLOUD 调用额度。
