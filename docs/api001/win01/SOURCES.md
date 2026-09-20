# 核验来源（2026-09-20）

归档内容与当前GitHub精确提交负责证明工程状态，以下官方资料用于解释可用认证与网络机制。

- https://docs.cloud.google.com/docs/authentication/rest — 本地开发REST可以使用有权限的gcloud用户凭据，区别于ADC。
- https://docs.cloud.google.com/sdk/gcloud/reference/auth/print-access-token — 用户access token、X-Goog-User-Project和serviceusage.services.use。
- https://docs.cloud.google.com/sdk/docs/proxy-settings — SDK显式proxy可覆盖http_proxy/https_proxy/no_proxy。
- https://learn.microsoft.com/windows/wsl/networking — NAT模式从WSL访问Windows服务使用host地址。
- https://github.com/zhixuanliu867-ship-it/RCWG/pull/5 — 本次受审PR。
- https://github.com/zhixuanliu867-ship-it/RCWG/actions/runs/35481272645 — 对应远端CI。

模型/价格/额度调用前重新核实，本包没有执行Google Cloud账户读取。
