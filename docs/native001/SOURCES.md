# 原生与主机接口依据

查阅日期：2026-09-20。以下支持接口设计，不代替本机测量证据。

- Linux kernel cgroup v2：https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html
  新组、进程/后代继承、populated、cpu.stat、memory.peak/events、io.stat 与 cgroup.kill。
- systemd 项目委派说明：https://github.com/systemd/systemd/blob/main/docs/CGROUP_DELEGATION.md
  Delegate 为指定 unit 下的子树委派；DelegateSubgroup 可把 controller 留在独立子组。
  请求了 controller 不代表实际可用，必须读回验证。
- SHA-256：NIST FIPS 180-4：https://csrc.nist.gov/pubs/fips/180-4/upd1/final
  本地实现有空串、abc、百万 a 和跨 block 二进制输入对照测试。
- 仓库历史科学规范：docs/spec001a/METROLOGY-001.md、SPEC-001_DECISIONS.md；
  docs/cloud001/NEXT_NATIVE_METROLOGY_INTERFACE.md；原 rcwg_exec 内核/对照未改写。
