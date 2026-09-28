"""F2 constructors, imported lazily by the task-builder registry."""
import random
from .templates import Plan,scalar,key,predicate,both,descriptor,task_shell,seed_for


def f2(template,base,condition):
    if condition not in {'C0','C1','C2','C3'}:raise ValueError('CONDITION')
    number=int(template[-2:]);seed=seed_for(template,base);rng=random.Random(seed)
    if number not in range(1,13):raise ValueError('TEMPLATE_UNREGISTERED')
    axis='key_skew' if number==2 else 'selectivity' if number==10 else 'row_count'
    n=113 if condition=='C1' and axis=='row_count' else 37;m=7 if number==3 else 37
    a=[{'left_id':i,'join_key':None if i%13==0 else i%17,'group_id':i%6,'entity_id':i%9,
        'amount':rng.randrange(-5,35),'timestamp':i*10,'eligible':i%3==0,'payload':f'左{base}·{rng.randrange(99999)}'} for i in range(n)]
    rng=random.Random(seed ^ 0xB001)
    b=[{'right_id':i,'join_key':None if i%11==0 else i%11,'right_entity_id':None if i%17==0 else i%8,
        'qualified':i%4!=0,'payload_b':f'右{base}·{rng.randrange(99999)}'} for i in range(m)]
    c=[{'entity_key':i%8,'weight':1+i%3} for i in range(13)]
    if condition=='C1' and number==2:
        for rows in [a,b]:
            for i,row in enumerate(rows):
                if row['join_key'] is not None:row['join_key']=0 if i%5 else row['join_key']
    if condition=='C1' and number==10:
        for i,row in enumerate(a):row['eligible']=i%7==0
    sa={'left_id':'Int64','join_key':scalar('Int64',True),'group_id':'Int64','entity_id':'Int64','amount':'Int64','timestamp':'Int64','eligible':'Bool','payload':'Utf8'}
    sb={'right_id':'Int64','join_key':scalar('Int64',True),'right_entity_id':scalar('Int64',True),'qualified':'Bool','payload_b':'Utf8'}
    sc={'entity_key':'Int64','weight':'Int64'}
    sources={'left':a};schemas={'left':sa}
    if number!=11:sources['right']=b;schemas['right']=sb
    if number in {9,10}:sources['third']=c;schemas['third']=sc
    instructions={1:'一对多等值 inner join，null key 不匹配，保留所有重复键乘积；输出 left_id/right_id。',
        2:'偏斜键 inner join 后按左 join_key 统计实际匹配条数。',3:'大小不对称表 inner join，输出 left_id/right_id，build side 不改变逻辑左右。',
        4:'受 RAM 预算约束完整连接，按 group_id 计数；所选实现的所有排序、物化与读取成本属于执行。',
        5:'left join 保留所有左行；无匹配右行时 right_id=null。',6:'右表 qualified=true 后 semi join，返回每个匹配左行一次。',
        7:'连接后按 group_id 统计不同非 null right_entity_id 的数量。',8:'inner join 后按 group_id 求左 amount 总和，保留所有匹配乘数。',
        9:'先 left.join_key=right.join_key，再 right_entity_id=third.entity_key，按 group_id 求 amount 总和。',
        10:'先对 left.eligible=true 筛选，再进行两次等值连接，按 group_id 求 amount 总和。',
        11:'对 timestamp 在 [70,230) 的左表行按 entity_id 求 amount 总和，再保留 total>=30 的实体。',
        12:'共享同一个 inner join 结果，分别求全局 sum(amount) 与 count(*)，以 sum/count 命名合并。'}
    out={'left_id':'Int64','right_id':scalar('Int64',True) if number==5 else 'Int64'}
    if number==2:out={'left.join_key':scalar('Int64',True),'count':'Int64'}
    if number in {4,7}:out={'group_id':'Int64','count':'Int64'}
    if number==6:out={'left_id':'Int64','group_id':'Int64'}
    if number in {8,9,10}:out={'group_id':'Int64','total':'Int64'}
    if number==11:out={'entity_id':'Int64','total':'Int64'}
    if number==12:out={'sum':{'kind':'Record','schema':{'total':scalar('Int64',True)}},'count':{'kind':'Record','schema':{'count':'Int64'}}}
    output={'id':'result','type':'record' if number==12 else 'records','mode':'exact','fields':list(out),'schema':out}
    task=task_shell(template,base,condition,instructions[number],output);task['datasets']=[descriptor(name,schemas[name],rows) for name,rows in sources.items()]
    plan=Plan(task['task_id']);left=plan.scan('left',sa)
    if number==11:
        selected=plan.filter('time_window',left,both(predicate('timestamp','ge',70),predicate('timestamp','lt',230)))
        source=plan.aggregate('totals',selected,['entity_id'],'sum','amount','total')
        source=plan.filter('having',source,predicate('total','ge',30),'Table')
    else:
        right=plan.scan('right',sb)
        if number==6:right=plan.filter('qualified',right,predicate('qualified','eq',True))
        if number==10:left=plan.filter('eligible',left,predicate('eligible','eq',True))
        if number==4:
            left=plan.add('sort_left','sort','external_merge',{'rows':left},{'keys':[dict(key('join_key'),nulls='last')]})
            right=plan.add('sort_right','sort','external_merge',{'rows':right},{'keys':[dict(key('join_key'),nulls='last')]})
        source=plan.add('joined','join','sort_merge' if number==4 else 'hash',{'left':left,'right':right},
            {'keys':[{'left':'join_key','right':'join_key'}],'join_type':'left' if number==5 else 'semi' if number==6 else 'inner','build_side':'right'})
        if number in {9,10}:
            third=plan.scan('third',sc);source=plan.add('joined_third','join','hash',{'left':source,'right':third},
                {'keys':[{'left':'right_entity_id','right':'entity_key'}],'join_type':'inner','build_side':'right'})
        if number==2:source=plan.aggregate('key_counts',source,['left.join_key'],'count',None,'count')
        if number==4:source=plan.aggregate('group_counts',source,['group_id'],'count',None,'count')
        if number==7:
            source=plan.project('distinct_fields',source,['group_id','right_entity_id'])
            source=plan.add('distinct_entities','deduplicate','hash',{'rows':source},{'keys':['group_id','right_entity_id'],'keep':'first'})
            source=plan.aggregate('group_counts',source,['group_id'],'count','right_entity_id','count')
        if number in {8,9,10}:source=plan.aggregate('group_sums',source,['group_id'],'sum','amount','total')
        if number==12:
            source=plan.add('read_joined','stream_read','arrow_batches',{'artifact':source},{'batch_size':7},{'rows':'Stream[Record]'})
            source=plan.add('shared','materialize','memory',{'rows':source},{'format':'arrow_ipc'},storage='memory')
            plan.add('fan','broadcast','shared_ref',{'artifact':source},{'consumers':['sum','count']},{'sum':'ArtifactRef','count':'ArtifactRef'})
            for label in ['sum','count']:
                r=plan.add('read_'+label,'stream_read','arrow_batches',{'artifact':'fan.'+label},{'batch_size':7},{'rows':'Stream[Record]'})
                r=plan.aggregate('aggregate_'+label,r,[],label,'amount' if label=='sum' else None,'total' if label=='sum' else 'count')
                plan.project('record_'+label,r,['total' if label=='sum' else 'count'],'Record',representation='record')
            source=plan.add('combine','project','column_view',{'sum':'record_sum.rows','count':'record_count.rows'},
                {'representation':'record','field_map':{'sum':'sum','count':'count'}},{'rows':'Record'})
    if number!=12:source=plan.project('result_fields',source,list(out))
    return {'task':task,'plan':plan.end(source),'rows':sources,'schemas':schemas,'template_id':template,'base_id':base,'condition':condition,
            'seed':seed,'axis':axis,'comparison':'record' if number==12 else 'bag','output_fields':list(out)}
