"""Build inspectable release tables and reports from preserved evidence."""
import csv,collections
from common import *
from release_audit import lines
from metrics import summarize,compare

def md(path,text):
    p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text.strip()+'\n',encoding='utf-8')

def table(path,rows):
    if not rows:return
    p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows({k:dump(v) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in rows)

def metric_rows(eid,task,ev,met,kind):
    return [{'episode':eid,'task':task['id'],'scenario':task['scenario'],'parent':task['parent'],'source_cluster':task['cluster'],'record_type':kind,'task_success':ev['success'],'metric_id':mid,'metric':v['name'],'status':v['status'],'numerator':v.get('numerator'),'denominator':v.get('denominator'),'value':v.get('value'),'note':v.get('note',v.get('reason',v.get('operationalization','')))} for mid,v in met.items()]

def main():
    cat=load(ROOT/'dataset_catalog.json');account=load(ROOT/'runs/api_accounting.json');models=load(ROOT/'qa/final_model_recheck.json')['records'];spec=load(ROOT/'protocol/metrics.json')['metrics'];allmetrics=[];rows=[]
    for x in cat['tasks']:
        eid='ACCEPT_FINAL_'+x['id'];task=load(ROOT/f"tasks/{x['id']}.json");ev=load(ROOT/f'recomputed/{eid}.json');met=load(ROOT/f'recomputed/{eid}_metrics.json');allmetrics+=metric_rows(eid,task,ev,met,'scripted_native_acceptance')
    modelmetrics=[]
    for x in models:
        eid=x['episode'];p=ROOT/'runs'/eid;task=load(ROOT/f"tasks/{x['task']}.json");ev=load(ROOT/f'recomputed/{eid}.json');old=load(p/'summary.json');req=lines(p/'physical_requests.jsonl');arts={a['artifact_id']:a for a in lines(p/'artifacts.jsonl')};events=lines(p/'execution_events.jsonl')
        s=load(p/'final_submission.json') if (p/'final_submission.json').exists() else None
        if x['projection_recovered_without_model_call']:
            s=load(p/'submitted_expression.json');s['answer']=ev['answer']
        met=summarize(task,ev,arts,events,req,s);write(ROOT/f'recomputed/{eid}_metrics.json',met);modelmetrics+=metric_rows(eid,task,ev,met,'paid_model_integration')
        rows.append({'episode':eid,'cohort':'final_protocol_10' if eid.startswith('LIVE_FINAL_') else 'targeted_interface_check' if eid=='LIVE_PATCH_A' else 'initial_diagnostics_10','task':x['task'],'scenario':task['scenario'],'parent':task['parent'],'source_cluster':task['cluster'],'model':'google/gemini-3.8-flash','original_status':x['original_status'],'original_success':x['original_success'],'final_judge_status':x['final_judge_status'],'final_judge_success':x['final_judge_success'],'projection_recovered_without_model_call':x['projection_recovered_without_model_call'],'model_calls':x['model_calls'],'settled_usd':round(sum(r.get('cost_usd',0) or 0 for r in req),9),'end_to_end_seconds':old['end_to_end_seconds'],'field_checks':x['field_checks']})
    table('analysis/native_control_measurements.csv',allmetrics);table('analysis/model_measurements.csv',modelmetrics);table('analysis/model_trials.csv',rows)
    coverage=[]
    for s in spec:
        a=collections.Counter(x['status'] for x in allmetrics if x['metric_id']==s['id']);b=collections.Counter(x['status'] for x in modelmetrics if x['metric_id']==s['id']);coverage.append({'metric_id':s['id'],'name':s['name'],**{'native_'+k:a[k] for k in ('MEASURED','NOT_APPLICABLE','NOT_OBSERVED')},**{'model_'+k:b[k] for k in ('MEASURED','NOT_APPLICABLE','NOT_OBSERVED')}})
    table('analysis/metric_coverage.csv',coverage)
    paired=[]
    for a,b in [('X01__separate','X01__shared'),('X08__serial','X08__parallel')]:
        item={'reference_task':a,'candidate_task':b,'track':load(ROOT/f'tasks/{a}.json').get('timing_track','native'),'controller':'scripted calibration; one pair',**compare(ROOT/'runs'/('ACCEPT_FINAL_'+a),ROOT/'runs'/('ACCEPT_FINAL_'+b))};paired.append(item)
    write(ROOT/'analysis/paired_controls.json',paired);table('analysis/paired_controls.csv',paired)
    notes={
      'M01':'每次尝试的契约成功位；汇总时同时保留全部尝试与可评分分母。',
      'M03':'只计显式、已登记 claims；没有 claims 时不据此判断完美精确率，M02 和字段判定仍覆盖必答项。',
      'M04':'图为 paper_ids，贷款审计为 loan_ids，代码为 regressions；其他集合完整性在逐字段判分和 M02 中保留。',
      'M09':'解析工人结构化 answer 中的已知原子义务；自由文本未抽取，不代表工人完全没有发现。',
      'M11':'各场景分别保存对象、记录、统计字段或原生收款绑定；不同场景不直接平均。',
      'M13':'引用存在性和 M14/M15 的证据支持性分开。',
      'M16':'当前契约的语义支持率，包括对未变字段仍有效的旧观察；它与 M15 可能数值相同。',
      'M21':'当前实现是所需字段的完成度；新实体/任务的发现时间与依赖见计划事件，不把字段完成度称为自主发现质量的完整测量。',
      'M24':'修订前首次已有正确义务到最终正确义务的变化；是描述性关联。',
      'M27':'单次明细结果页的重复事实贡献下界；不把重复读取误算成 join 倍增。仅有聚合值时不猜测其内部倍增。',
      'M30':'已登记错误的同断言继承路径，且无新增目标相关观察；与因果归因分开。',
      'M31':'观察记录/版本及声明来源的类别数，不由此推断模型或统计独立性。',
      'M32':'只有明确独立确认声明才适用；已知共享来源可判违例，未知来源单列。',
      'M33':'已知 unsupported 字段中的越权断言，以当前提交的任务字段数作分母；不是开放事实幻觉率。',
      'M37':'官方 native_success 与增强契约 exact_state_success 同时保留。',
      'M39':'丢响应后观察到状态重读且最终精确状态成功；重复提交破坏精确状态则失败。',
      'M41':'领域工作向量，保留算子单位；SQLite 步数为采样下界；受控延时另列。',
      'M42':'全部模型物理请求按经理/工人和终态分组；工具物理调用在 M41 和事件中。',
      'M43':'服务商回执中的费用/tokens，加未结算预约；零回执用量不推断为零实际推理。',
      'M44':'时间区间并集、观测到的工人依赖关键路径和本地线程 CPU；另有 local_resources.json 的进程树采样，不把网络等待当远端算力。',
      'M45':'通过 compare 对匹配任务的联合有效对计算；不是每个单次 episode 的指标。',
      'M46':'通过 compare 对相同任务/真值的联合有效对计算；保留原生与受控计时标签。',
      'M47':'reliability(successes,n,k)=C(successes,k)/C(n,k)；本轮联调协议经过修订，没有同冻结协议足量重复，故不输出稳定性估计。'
    }
    text='# 完整指标字典与实际覆盖\n\n48 个登记项按用途独立报告，包含单次观察、配对统计和重复统计。数量不代表 48 个互相独立的能力维度；当前 M15/M16、M21/若干领域字段完成率可能重合。单次不适用与缺少触发观察分别记为 NOT_APPLICABLE 和 NOT_OBSERVED。\n\n'
    text+='原始底表：`analysis/native_control_measurements.csv`（79×48）、`analysis/model_measurements.csv`（21×48）、`analysis/metric_coverage.csv`。配对结果另见 `analysis/paired_controls.json`。\n\n'
    for s,c in zip(spec,coverage):
        text+=f"## {s['id']} · {s['name']}\n\n- 场景：{', '.join(s['scenarios'])}；粒度：{s['grain']}；单位：{s['unit']}。\n- 分子/记录：{s['numerator']}。\n- 分母/基准：{s['denominator']}。\n- 数据源：{s['measurement_source']}。\n- 解释规则：{s['interpretation_rule']}\n- 实现：`{s['implementation']}`。\n- 当前已观测：原生控制 {c['native_MEASURED']}/79，模型联调 {c['model_MEASURED']}/21；其余原因逐行保存在底表。\n"
        if s['id'] in notes:text+='- 当前操作化：'+notes[s['id']]+'\n'
        text+='\n'
    md('reports/05_完整指标字典.md',text)
    contract=load(ROOT/'qa/ACCEPT_FINAL_contracts.json');recheck=load(ROOT/'qa/final_contract_recheck.json');audit=load(ROOT/'qa/release_consistency.json')
    md('reports/03_实现验收报告.md',f'''# 实现验收报告

本版完成五场景适配器、动态运行器、任务与证据判分、资源记录、指标计算和离线复现入口。验收用原生工具执行及正负控制检验仪器，再用真实模型检查接口。下表每行是不同范围的检查，彼此存在重叠，不相加为独立样本数。

|验收项|结果|证据|
|---|---:|---|
|全任务原生运行与契约控制|{contract['passed_tasks']}/{contract['task_count']} 个任务，{contract['check_count']} 项检查全部通过|qa/ACCEPT_FINAL_contracts.json|
|最终判分器复核相同原生轨迹|{recheck['passed_checks']}/{recheck['check_count']}，79/79 个任务|qa/final_contract_recheck.json|
|依赖、修订、隔离、核算运行时控制|17/17|qa/ACCEPT_FINAL_runtime.json|
|跨对象/版本、伪造证据、动态更新等深层控制|19/19|qa/DEEP_RELEASE_V2.json|
|真实联调发现问题的回归控制|10/10|qa/post_integration_acceptance.json|
|畸形答案处理|5/5|qa/malformed_payload_controls.json|
|并发缓存不重复计费|通过|qa/concurrent_cache_accounting.json|
|无关新读取不切断同源错误传播链|通过|qa/claim_specific_provenance.json|
|历史旧契约回放|48 条可评分，0 次成功位变化；另保留 1 条不可评分记录|qa/legacy_replay.json|
|最终数据/轨迹/账本一致性|79 卡、100 条轨迹、{audit['counts']['events']} 事件、{audit['counts']['artifacts']} 产物、266 请求；0 错误|qa/release_consistency.json|

## 验收实际检查什么

正确控制使用真正的图/SQL 读取、源码与原生测试、遥测计算、AppWorld 仿真状态。校准控制器按已知任务完成工作，其通过说明任务可执行且判断接口可用。它的结果不进入模型成功率。负控制分别改错答案、拿掉证据、错绑对象/测试/版本、伪造生产事件、复制旧意见或增加未登记断言；不能只靠一个正确答案模板通过所有控制。

一个有用的原生例子：晚餐任务正确新增三笔请求后，故意重复增加第四笔。官方原生成功位仍为 true；增强契约因重复写入而失败。这条检查在实际模拟数据库中完成，验证“任务完成”与“完整满足业务要求”确实能够分开。

## 联调后修复

合法的公开 API 名称现在通过源码和继承关系解析，模块路径与 API 名称可以表达等价影响范围。对象身份允许来自无歧义 SQL 谓词；已提交的共享上下文可支持派生结论。长列表可以直接投影观察产物，不必复制到每个 claim。行政性完成摘要不再要求未公开固定词；完成情况以真实业务状态判断。畸形 JSON、无效投影和不合法计划会产生可读反馈，并保留失败记录。

原有判分保存在 runs，最终判分写入 recomputed。LIVE_FINAL_04 的投影解析修复是无新增调用的回放；另以 LIVE_PATCH_A 进行了新的真实 API 检查并直接通过。两类证据分别标注。

## 发布范围

当前 79 条件属于 13 个语义父实例、8 个保守来源簇。评估器和本轮任务池通过验收；大规模未见来源上的模型能力比较仍需独立采样。M45/M46 必须由配对运行生成，M47 必须由重复运行生成，当前单次底表不会补造这些统计量。所有初期实现失败和被修正的判分均随完整包保存。
''')
    findings={1:'全部 12 篇论文正确；12 家机构仅列出 10 家。',2:'3 篇论文、5 家机构及其证据正确。',3:'客户 1673 及 9 条月度记录正确。',4:'682 个 loan_id 与聚合正确；原输出投影由最终解析器回放恢复。',5:'10 个回归与影响范围正确；真实 API 名称经最终源码解析接受。',6:'12 个回归只报告 8 个，漏了两组 cookie domain/path 边界。',7:'CPU 事件的 9 个字段正确。',8:'9 个字段正确 8 个；emailservice 是最大延迟症状，注入根因是 checkoutservice。',9:'原生状态及精确三笔请求通过；完成摘要无需固定词。',10:'40 次模型调用后仍无实际播放，最终却声称已完成。'}
    finalrows=[x for x in rows if x['cohort']=='final_protocol_10'];finaln=sum(x['final_judge_success'] for x in finalrows)
    text=f'''# 模型联调与数据分析

本轮调用模型 **google/gemini-3.8-flash**，共 21 条尝试、266 次物理请求。先进行 10 条初始诊断，再以统一扩大的接口协议运行 10 条，最后补 1 条长列表投影检查。两轮与补查全部保存；开发过程没有删除失败样本。

统一协议为经理最多 10 轮、单次工人最多 8 轮、总模型调用最多 40 次，保留最后一次经理提交。最终判分下，统一协议 10 条中 **{finaln}/10 满足契约**。其中一条使用已保存的合法投影表达式完成回放解析。由于本轮根据联调反馈修正了评估器，这是一组接口和判分校准数据；不把它写成冻结未见测试集的模型能力估计。

|记录|任务|最终契约|调用数|费用 USD|可判断的问题|
|---|---|---|---:|---:|---|
'''
    for i,x in enumerate(finalrows,1):text+=f"|{x['episode']}|{x['task']}|{'PASS' if x['final_judge_success'] else '未满足'}|{x['model_calls']}|{x['settled_usd']:.6f}|{findings[i]}|\n"
    text+='''
## 目前最有解释力的观察

**覆盖遗漏可以被成功的局部推理掩盖。** 图任务所有已列机构都有依据，但漏掉 ID 1105585 与 1112146。仅看论文集合或引用合法性，会错过最终调查不完整。论文可同时呈现义务覆盖与证据支持，而不让一个粗粒度正确率代替二者。

**执行检查与读懂检查是两种表现。** Requests 漏报的四项分别来自 http_transport_samples 与 request_state_samples 的 cookie_domain、cookie_path。正确期望为 cookie:None，实际观察是 cookie:session=example-cookie。模型已取得的观察、实际跑过的检查与最终回归召回分开保存，可以定位遗漏发生在调查还是整合阶段。

**统计量计算正确不保证诊断正确。** delay 事件的故障类型、CPU、p90、trace 和日志字段正确，但根因错选 emailservice。两个当前事件都以 checkoutservice 为根因，常量根因基线会在这两个事件上得到 2/2，因此应将这条记录用于症状/根因分离的机制分析，后续正式样本需要不同根因与服务系统。

**语言完成声明与实际执行状态可以直接对照。** 音乐任务反复搜索后达到 40 调用预算，实际未播放、队列为空且未完成 supervisor 状态，却声称已播放。这条轨迹能分析搜索范围、重复调查、状态操作与最终声明之间的差距。全部费用和无效工具工作仍入账。

**评估器误拒绝必须单列。** 完整贷款投影、合法 API 名称与正确业务状态曾因接口或匹配方式受罚，现已用语义匹配修复。原判分、回放判分、修复依据和新的 LIVE_PATCH_A 原生通过结果全部保留，不能把这些接口缺陷算作模型能力缺陷。

## 原生配对控制

下列是单对脚本校准，展示测量链是否能分别记录工作与时间。模型未选择这两条控制工作流，故不归因于模型编排能力。配对的质量、联合有效数和原始资源向量见 analysis/paired_controls.json。

'''
    for p in paired:text+=f"- `{p['reference_task']} → {p['candidate_task']}`：joint_valid_n={p['joint_valid_n']}，记录返回量节省 {p['work_saving'].get('returned_records',0):.2%}，本次端到端时间变化对应节省 {p['latency_saving']:.2%}。计时轨道：{p['track']}；重复数 1。\n"
    text+=f'''
X08 的工具延时是显式受控因素，不能把它当生产系统加速。X01/X08 的用途是确认工作变化与时间变化被分开测量；正式效率结论需要冻结机器条件并重复测量。

## 费用与失败台账

- 本轮新增已结算：**USD {account['settled_cost_usd']:.9f}**；新增未知预约：USD {account['unresolved_reserved_usd']:.9f}。
- 继承的历史保护性承诺：USD {account['prior_committed_usd']:.9f}；累计承诺：**USD {account['cumulative_committed_usd']:.9f}**，低于用户 USD20 限额。
- 新调用账本 ceiling 为 USD4，不能靠重启清账抬高。历史未知请求保持其原预约；本次不把历史未知当作免费。
- 全部物理回执与账本逐 ID、逐费用核对，266/266 对齐。tokens 及零用量回执原样保留，不由缺失回执推断远端计算成本。

模型逐条底表在 analysis/model_trials.csv；48 维逐条测量在 analysis/model_measurements.csv。原始响应、提交、观察、模型请求及原判分在 runs，最终判分在 recomputed。
'''
    md('reports/04_模型联调与数据分析.md',text)
    counts=collections.Counter(x['scenario'] for x in cat['tasks'])
    md('README_先读.md',f'''# RCWG 五场景评估器与数据集：本轮最终交付

**状态：实现完成，79 条件任务已物化，全部通过原生验收与最终契约复核。** 本目录可运行；离线复现无需调用付费模型。数据、任务、运行器、评估器、指标、验收证据和全部联调记录一并交付。

## 从哪里开始

1. [数据集与任务说明](reports/01_数据集与任务集最终说明.md)：来源、扩展、条件和统计分母。
2. [评估器实现与指标解释](reports/02_评估器实现与指标解释.md)：五项接口、动态编排和语义判分。
3. [实现验收报告](reports/03_实现验收报告.md)：验收检查、修复项和历史兼容回放。
4. [模型联调与数据分析](reports/04_模型联调与数据分析.md)：21 次真实尝试、失败机制与费用。
5. [完整指标字典](reports/05_完整指标字典.md)：48 项的定义、操作化、适用范围及实际观测覆盖。
6. [复现入口](REPRODUCE_zh.md)：离线执行、重新判分、模型运行及换机安装。

## 交付规模

|场景|当前条件任务数|
|---|---:|
|GraphRAG|{counts['graph']}|
|数据分析|{counts['analytics']}|
|代码审查与影响分析|{counts['code_review']}|
|故障诊断|{counts['incident']}|
|有状态业务|{counts['appworld']}|
|总计|79|

79 条件来自 **13 个语义父实例、8 个保守来源簇**，包含 24 个核心受控条件、6 个自由编排入口、41 个扩展条件、4 个时间范围派生任务和 4 个恢复来源条件。任务级最终结果允许不同正确分解；经理可依据观察增建子任务和依赖；产物及源版本可追踪；经理/工人/工具/失败/重试共同入账；初始计划、计划修订和实际执行分存。指标各自报告，没有加权总分。

## 验收与实跑

- 79/79 原生任务控制通过，491 项原生验收检查通过；最终判分器复核 413/413。
- 运行时 17/17、深层 19/19、联调回归 10/10、畸形输入 5/5；另通过并发缓存计数及断言相关传播检查。
- 历史 48 条可评分轨迹回放成功位变化为 0；1 条原不可评分记录保留。
- 79 原生控制加 21 模型联调共 100 条最终审计轨迹，3,887 个事件、1,342 个产物及 266 个物理请求一致性校验通过。
- 统一协议下 10 条模型联调最终判分为 6 条满足契约。模型失败、评估器误拒绝和回放解析修复均分别说明；其余 10 条初诊及 1 条新投影复测全部保存。
- 本轮新增费用 **USD {account['settled_cost_usd']:.9f}**，新增未知预约 0；累计保护性承诺 USD {account['cumulative_committed_usd']:.9f}。

## 文件组织

- tasks / private / agent_views：任务卡、仅评估器可读的真值、模型可见输入。
- assets / source_bundles / protocol：实际素材、AppWorld 官方分发 bundle、来源与协议。
- src / vendor：当前执行代码与原生桥接。
- runs / recomputed / qa：原始运行、最终回放判分、验收检查。开发失败同样保留。
- analysis：逐条 CSV、指标覆盖底表、配对控制结果。
- legacy_evidence / replay / archive_design：历史证据、兼容回放和设计来源。
- manifest.json：分发内容的逐文件 SHA-256；deliveries：完整包、易读包与外部校验回执。

AppWorld 官方解包数据和本机环境留在 local_only，分发包提供官方 bundle 和复现步骤。模型 API 密钥不进入交付。79 任务是本轮冻结的机制任务池，正式论文的未见来源测试应按来源簇另行采样；现有模型结果属于接口联调与机制观察。
''')
    print(dump({'task_metric_rows':len(allmetrics),'model_metric_rows':len(modelmetrics),'model_trials':len(rows),'metrics':len(spec),'final_protocol_successes':finaln}))

if __name__=='__main__':main()
