# 来源、版本与证据

本轮主要依据用户交付 SPEC001B 的报告、FINAL.patch、机器证据及 EXEC-001_INTERFACE；补丁源/日志逐字节核验。其远端head a1f65120ef0b2b8e1fb6f1c31224244d6f7ee16b、tree 5b1b7cd587bbb3df54952ea24eb6841767a1e0bd；PR3 draft；PR2未合并；CI run35441844827/job105893893081 success。状态均在本轮通过GitHub连接器实际读取。源码复跑仅证明本次观察的测试/输入，不能证明所有程序语义无错。

外部技术参考（本轮实际查阅官方文档）：
- Python3.12 heapq（堆不变量、priority tie序位）：https://docs.python.org/3.12/library/heapq.html
- Python3.12 resource（进程资源与ru_maxrss范围）：https://docs.python.org/3.12/library/resource.html
- Python3.12 time（单调计时/CPU计时）：https://docs.python.org/3.12/library/time.html
- Linux cgroup v2（memory.peak/cpu.stat/oom/max的实际字段与内核差异）：https://docs.kernel.org/admin-guide/cgroup-v2.html
- GitHub CLI merge精确head guard：https://cli.github.com/manual/gh_pr_merge
- GitHub CLI ready：https://cli.github.com/manual/gh_pr_ready

工程单例只作为fixture correctness/instrumentation证据。未产生新模型结果、真实云端测量或资金支出。任何scope受限值以相同scope报告；缺测保持null，不填入论文效率主表。
