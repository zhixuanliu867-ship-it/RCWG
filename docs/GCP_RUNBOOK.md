# GCP 一次云端工程验收操作卡

状态：模板已经静态检查；下面操作尚未在用户账号中执行。所有收费资源、API启用、IAM与上传动作由账号所有者批准后操作。

## A. 本轮架构

```text
用户手工启动 Workflows（外层）
        │ 固定job名称，等待任务完成
        ▼
Cloud Run Job（1 task / 1 parallel / 1 CPU / 1 GiB / 120 s / retry 0）
        │ 固定mock夹具 → 独立排序校验 → hash与工程报告
        ▼
私有 Cloud Storage：boot/<execution>/<attempt>/report.json
        │
用户核对报告、镜像digest与账单，完成单次验收
```

真实API调用使用另一个经批准的本地探针，不挂在此云流程里。正式生成、WorkIR执行器和验收器按后续工作包接入该外层框架。

## B. 控制台准备与批准点

在Google Cloud控制台选择专门的RCWG项目并绑定你确认的结算账号，记录项目ID。区域候选为 `us-central1`；所有桶/仓库/Job/Workflow尽量同区域。若数据位置或网络测试要求新加坡，在批准后同步更改region与价格估算，不混用两个区域的正式结果。

在 Billing → Budgets & alerts 建立覆盖本项目的告警；参考 COSTS.md 配置小额Cloud Run服务级spend cap（控制台支持时）。把外部模型提供商的限额单独登记。首次执行批准金额建议USD5。

按需要启用 Artifact Registry、Cloud Run、Workflows、Cloud Storage 对应API。API启用与IAM修改属于账号变更步骤；遇到权限错误先保存错误，不使用Owner/Editor大权限作为默认补丁。

## C. 身份与最小授权

| 身份 | 用途 | 授权范围 |
|---|---|---|
| 你的部署账号 | 创建镜像、Job、工作流并配置IAM | 按控制台要求逐项批准，serviceAccountUser仅针对所用服务账号 |
| `rcwg-boot-worker` | Job运行身份 | `roles/storage.objectCreator`，仅在本轮artifact bucket |
| `rcwg-boot-workflow` | 调用固定Job、等待状态 | `roles/run.invoker`在该Job；若连接器读取执行状态需要，`roles/run.viewer`在独立RCWG项目 |

工作账号不申请API key、隐藏gold读权限和服务账号JSON私钥。Google访问令牌由Job元数据服务短期取得。工作流服务账号不需要管理Job或对象存储权限。参考[S9][S11]。

## D. 镜像：先在具备Docker的目标开发/构建环境验证

在仓库根目录执行，下列本地smoke覆盖镜像默认云入口，不访问外部API：

```bash
docker build -t rcwg-boot:boot-001 .
docker run --rm --network=none rcwg-boot:boot-001 \
  python -m rcwg_boot smoke --out /tmp/rcwg-runs
docker image inspect rcwg-boot:boot-001 --format '{{.Id}}'
docker image inspect python:3.12-slim-bookworm --format '{{json .RepoDigests}}'
```

记录Docker版本、基础镜像RepoDigest与Python补丁版本。基础tag在本包是候选，不作为正式不可变版本。若本地没有Docker，先提交该待审批项；可用你批准的云端构建环境完成相同验证。当前CI只跑标准库测试，不会替你建立收费Cloud Build任务。

控制台创建同区域Artifact Registry Docker仓库 `rcwg`。在已经登录你的gcloud账号的构建终端中，用实际项目替换占位符后运行：

```bash
PROJECT_ID='<真实项目ID>'
REGION='us-central1'
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/rcwg/boot:boot-001"
gcloud auth configure-docker "$REGION-docker.pkg.dev"
docker tag rcwg-boot:boot-001 "$IMAGE"
docker push "$IMAGE"
gcloud artifacts docker images describe "$IMAGE" \
  --project="$PROJECT_ID" --format='value(image_summary.digest)'
```

最后返回的 `sha256:...` 形成不可变 `IMAGE_DIGEST`：`REGION-docker.pkg.dev/PROJECT_ID/rcwg/boot@sha256:...`。把它填入Job模板，避免部署mutable tag。

## E. 存储与Job

控制台创建一个私有Standard存储桶，开启统一桶级访问和公开访问防护，不授予 `allUsers` / `allAuthenticatedUsers`。配置并记录软删除/版本保留政策，先不建立未经确认的自动删除规则。worker服务账号仅在该桶获得objectCreator。

复制 `infra/gcp/job.yaml.template` 到忽略目录 `runs/job.yaml`，填入实际项目、worker邮箱、不可变镜像digest和桶名。然后：

```bash
gcloud run jobs replace runs/job.yaml --project="$PROJECT_ID" --region="$REGION"
```

该命令创建/更新Job定义，尚不执行任务。模板没有公开HTTP服务，也不包含模型密钥；任务数1、并行1、重试0、超时120秒。Job云入口会拒绝缺失存储配置，归档失败时以失败结束。[S9][S10]

## F. 工作流：只启动一次

确认 `infra/gcp/workflow.yaml` 中region与Job一致。赋予workflow身份上表权限，在控制台 Workflows → Create 中选择相同区域、服务账号，粘贴YAML；也可使用已批准的gcloud操作：

```bash
WORKFLOW_SA="rcwg-boot-workflow@$PROJECT_ID.iam.gserviceaccount.com"
gcloud workflows deploy rcwg-boot-001 \
  --source=infra/gcp/workflow.yaml \
  --service-account="$WORKFLOW_SA" \
  --project="$PROJECT_ID" --location="$REGION"

# 下面这一条是实际执行批准点：不要重复点击/重复运行。
gcloud workflows run rcwg-boot-001 --project="$PROJECT_ID" --location="$REGION"
```

不创建Scheduler、Eventarc、GitHub自动部署和重试包装器。Workflows连接器会等待操作并进行轮询；发生超时时先检查对应Job是否仍执行，不能直接重新提交来掩盖状态。该系统不承诺全局exactly-once；每个实际execution和attempt都需要核对。[S9]

## G. 验收证据

在Cloud Run执行日志看到 `status=PERSISTED` 与 `gs://.../report.json`。去私有桶打开对应文件：`status=PASS`、`provider=mock`、`api_requests=0`、`formal_result=false`，保存输出hash、执行ID、镜像digest、开始/结束时间与账单截图（分享前隐藏账号/付款信息）。

API请求数0只表示没有调用大模型；Job使用了Google身份与存储API。若只有本地report而无GCS归档成功证据，云端验收记失败或待完成。预算账单可能延迟，应在停止任务后再复核。

按照 `infra/gcp/cleanup.md` 审批清理。Job执行结束后的镜像、对象与日志仍需要保留期管理；停止计算不等于所有云费用归零。
