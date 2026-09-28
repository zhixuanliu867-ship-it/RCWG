"""F4 physical/lifetime tasks with concrete public contracts and explicit choices."""
import random
from .templates import Plan,seed_for,task_shell,descriptor,predicate


def expression(op,left,right):return {'op':op,'left':left,'right':right}


def f4(template,base,condition):
    if condition not in {'C0','C1','C2','C3'}:raise ValueError('CONDITION')
    number=int(template[-2:]);seed=seed_for(template,base);rng=random.Random(seed)
    if number not in range(1,13):raise ValueError('TEMPLATE_UNREGISTERED')
    n=(4109 if condition=='C1' else 2053) if number in {3,4,5} else (73 if condition=='C1' else 37)
    schema={'id':'Int64','group_id':'Int64','amount':'Int64','eligible':'Bool','payload':'Utf8'}
    records=[{'id':i,'group_id':i%7,'amount':rng.randrange(-70,300),'eligible':i%3!=1,
              'payload':(f'实例{base}·记录{i}·🙂·{rng.randrange(99999):05d}')*24} for i in range(n)]
    sources={'records':records};schemas={'records':schema}
    grouped={'kind':'Table','schema':{'group_id':'Int64','total':'Int64'}}
    summaries={'sum':{'kind':'Record','schema':{'total':{'kind':'Nullable','item':{'kind':'Int64'}}}},'count':{'kind':'Record','schema':{'count':'Int64'}}}
    outputs={1:summaries,2:{'a':summaries['sum'],'b':summaries['sum']},6:summaries,7:summaries,
             9:{'joined':grouped,'original':grouped},10:{k:{'kind':'Table','schema':{'id':'Int64','value':'Int64'},'revision':'engineering-logical-v1'} for k in ['fast','slow']},
             11:{'a':summaries['sum'],'b':summaries['sum']},12:{'remaining':'Int64','iterations':'Int64','active':'Bool'}}
    output=({'id':'result','type':'record','mode':'exact','fields':list(outputs[number]),'schema':outputs[number]} if number in outputs else
            {'id':'result','type':'records','mode':'exact','fields':['id','value'] if number==8 else ['group_id','total'],
             'schema':{'id':'Int64','value':'Int64'} if number==8 else grouped['schema']})
    instructions={
      1:'同一完整宽表分别计算 sum(amount) 和 count(*)，返回 sum.total 与 count.count。',
      2:'两个只读消费者分别计算全表 sum(amount)，返回 a.total 与 b.total；共享引用与独立复制均须值等价。',
      3:'逐批读取 records，按 group_id 计算 sum(amount)；输出 group_id、total 全部组。',
      4:'先显式物化 records，再读取并按 group_id 计算 sum(amount)；磁盘与内存结果应相同。',
      5:'只需访问 group_id、amount 两列即可计算各组 sum(amount)，不需要 payload 内容。',
      6:'eligible=true 过滤结果由同 run 的两个消费者复用，分别输出 sum.total 与 count.count。',
      7:'全表两个分支分别求 sum(amount)、count(*)；最后消费者完成后显式释放大表，只保留小结果。',
      8:'按 records 输入 ordinal 顺序输出 id 与 value=amount*2，有限并发不得改变次序。',
      9:'共享 eligible=true 过滤结果：original 按 group_id 求和；joined 将它与 weights 按 group_id 内连接，再按 weights.g 求 sum(amount)，保留连接重复数。',
      10:'同一有序输入流的 fast 分支输出 amount*2；slow 经过三步 amount+1、乘2、减2；两支最终按原 ordinal 返回完全相同的 id/value 全部行。',
      11:'同时保留 records 和 other 两个宽表直至各自求和，返回 a.total、b.total 后显式释放两表。',
      12:'初始化 remaining=count(records)、iterations=0、active=' + ('false' if base==0 else 'true') + '；当 active AND remaining>0 时 remaining-=16、iterations+=1，最多16轮；初始谓词为false时不得执行。'}
    task=task_shell(template,base,condition,instructions[number],output);plan=Plan(task['task_id'])
    narrow={'group_id':'Int64','amount':'Int64'} if number==5 else schema
    source=plan.scan('records',narrow)
    if number in {8,10}:plan.value['nodes'][-1]['resources']={'batch_rows':7}
    if number in {6,9}:source=plan.filter('shared_filter',source,predicate('eligible','eq',True))
    def material(name,rows,storage='memory'):
        return plan.add(name,'materialize',storage,{'rows':rows},{'format':'arrow_ipc'},storage=storage)
    def read(name,artifact):return plan.add(name,'stream_read','arrow_batches',{'artifact':artifact},{'batch_size':7},{'rows':'Stream[Record]'})
    def combine(fields,after=()):
        return plan.add('combine','project','column_view',fields,{'representation':'record','field_map':{k:k for k in fields}},{'rows':'Record'},**({'after':list(after)} if after else {}))
    def summary(name,rows,fn):
        alias='count' if fn=='count' else 'total'
        result=plan.aggregate('agg_'+name,rows,[],fn,None if fn=='count' else 'amount',alias)
        return plan.project('record_'+name,result,[alias],'Record',representation='record')
    def mapper(name,rows,slow=False):
        steps=[('a',expression('add',{'field':'amount'},{'literal':1})),('b',expression('mul',{'field':'value'},{'literal':2})),('c',expression('sub',{'field':'value'},{'literal':2}))] if slow else [('a',expression('mul',{'field':'amount'},{'literal':2}))]
        children=[];ref='$bound.row'
        for ident,ast in steps:
            children.append({'id':ident,'operator':'project','implementation':'column_view','inputs':{'rows':ref},'params':{'columns':['id'],'representation':'record','expressions':{'value':ast}},'outputs':{'rows':'Record'}});ref=ident+'.rows'
        return plan.add(name,'map','bounded_map',{'rows':rows},{},{'rows':'Stream[Record]'},regions={'body':{'bindings':{'row':'$item'},'nodes':children,'yield':{'rows':ref}}},resources={'max_parallelism':2})
    if number in {1,2,6,7,9}:
        shared=material('shared',source)
        if number==6:shared=plan.add('cache','cache','memory',{'artifact':shared},{'key_fields':['id']},{'artifact':'ArtifactRef'},storage='memory')
        labels=['a','b'] if number==2 else ['joined','original'] if number==9 else ['sum','count']
        plan.add('fan','broadcast','copy_each' if number==2 else 'shared_ref',{'artifact':shared},{'consumers':labels},{k:'ArtifactRef' for k in labels})
        fields={}
        for label in labels:
            rows=read('read_'+label,'fan.'+label)
            if number==9:
                if label=='joined':
                    sources['weights']=[{'g':i,'weight':j+1} for i in range(7) for j in range(1+(i%3))];schemas['weights']={'g':'Int64','weight':'Int64'}
                    right=plan.scan('weights',schemas['weights'])
                    rows=plan.add('join','join','hash',{'left':rows,'right':right},{'keys':[{'left':'group_id','right':'g'}],'join_type':'inner','build_side':'right'})
                fields[label]=plan.aggregate('agg_'+label,rows,['group_id'],'sum','amount','total')
            else:fields[label]=summary(label,rows,'count' if label=='count' else 'sum')
        after=[]
        if number==7:
            plan.add('release','release','explicit',{'artifact':shared},{},{'done':'ControlToken'},after=['record_sum','record_count']);after=['release']
        source=combine(fields,after)
    elif number in {3,4,5}:
        if number==4:source=read('read_disk',material('on_disk',source,'disk'))
        if number==5:source=plan.project('narrow',source,['group_id','amount'],'Stream[Record]')
        source=plan.aggregate('group',source,['group_id'],'sum','amount','total')
    elif number==8:source=mapper('map',source)
    elif number==10:
        plan.add('fan','broadcast','shared_ref',{'artifact':source},{'consumers':['fast','slow']},{'fast':'Stream[Record]','slow':'Stream[Record]'})
        fields={}
        for label in ['fast','slow']:
            rows=mapper('map_'+label,'fan.'+label,slow=label=='slow')
            fields[label]=plan.add('collect_'+label,'collect','bounded_collect',{'rows':rows},{'limit':n})
        source=combine(fields)
    elif number==11:
        sources['other']=[{**r,'amount':r['amount']*3+11,'payload':r['payload']+'乙'} for r in records];schemas['other']=schema
        a=material('mat_a',source);b=material('mat_b',plan.scan('other',schema));fields={}
        for label,ref in [('a',a),('b',b)]:
            rows=read('read_'+label,ref);plan.value['nodes'][-1]['after']=['mat_a','mat_b']
            fields[label]=summary(label,rows,'sum')
        for label,ref in [('a',a),('b',b)]:plan.add('release_'+label,'release','explicit',{'artifact':ref},{},{'done':'ControlToken'},after=['record_a','record_b'])
        source=combine(fields,['release_a','release_b'])
    else:
        source=plan.aggregate('count',source,[],'count',None,'remaining')
        source=plan.project('state',source,['remaining'],'Record',representation='record',expressions={'iterations':{'literal':0},'active':{'literal':base!=0}})
        step={'id':'step','operator':'project','implementation':'column_view','inputs':{'rows':'$bound.state'},'params':{'representation':'record','columns':['active'],'expressions':{'remaining':expression('sub',{'field':'remaining'},{'literal':16}),'iterations':expression('add',{'field':'iterations'},{'literal':1})}},'outputs':{'rows':'Record'}}
        source=plan.add('loop','loop','bounded_loop',{'state':source},{'condition':{'op':'and','args':[{'field':'active'},predicate('remaining','gt',0)]},'max_iterations':16},{'state':'Record'},regions={'body':{'bindings':{'state':'$state'},'nodes':[step],'yield':{'state':'step.rows'}}})
    task['datasets']=[descriptor(alias,schemas[alias],rows) for alias,rows in sources.items()]
    return {'task':task,'plan':plan.end(source),'rows':sources,'schemas':schemas,'template_id':template,'base_id':base,'condition':condition,
            'seed':seed,'axis':'object_rows','comparison':'bag' if number in {3,4,5} else 'ordered' if number==8 else 'record','output_fields':output['fields']}
