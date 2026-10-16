"""Five native domain interfaces. No method in this module reads a task oracle."""
import sqlite3,time,sys,subprocess,threading,queue,copy,re,os,json,ast
from collections import Counter
from common import *
class DomainError(Exception):pass
class Adapter:
    def __init__(self,task,episode):
        self.task=task;self.episode=episode;self.scenario=task['scenario'];self.dataset=task['dataset'];self.version=task['initial_version'];self.dbfile=self.dataset+'.sqlite'
        self.updated=False;self.read_fault=False;self.write_count=0;self.fault_fired=False;self.proc=None;self._lock=threading.RLock();self.closed=False;self.context=threading.local();self.concurrent_readers=set();self.concurrent_snapshot=None
        self.assets={'source':self.version};self.native_private=[]
        if self.scenario=='incident':
            import pandas as pd
            p=ROOT/'assets'/self.dataset
            self.metric=pd.read_parquet(p/'metrics.parquet');self.logs=pd.read_parquet(p/'logs.parquet');self.traces=pd.read_parquet(p/'traces.parquet');self.cut=task['cut_timestamp'];self.trace_state=task['conditions'].get('traces','available')
        self.tools={
            'graph':{'search_nodes':{'text':'substring','type':'optional node type','offset':0,'limit':120},'nodes':{'ids':'up to 100 integer IDs'},'neighbors':{'ids':'up to 100 IDs','edge_type':'0 affiliation,1 citation,2 topic,3 authorship','direction':'in/out','offset':0,'limit':120}},
            'analytics':{'schema':{},'select':{'sql':'one readonly SELECT/WITH','offset':0,'limit':1000},'explain':{'sql':'readonly query'},'row_lookup':{'table':'table name','key':'column','value':'exact key'}},
            'code_review':{'list_files':{'prefix':'optional'},'read_file':{'path':'relative source path','start':1,'lines':200},'search_source':{'text':'literal substring','offset':0,'limit':100},'run_checks':{'check_names':'public names; omit to list'},'read_probe_inputs':{'start':1,'lines':200}},
            'incident':{'service_catalog':{},'metric_summary':{'filter':'metric substring','service':'optional exact service','offset':0,'limit':100},'log_search':{'regex':'case insensitive','service':'optional','offset':0,'limit':30},'trace_summary':{'service':'optional'},'trace_relations':{'service':'exact service','offset':0,'limit':100}},
            'appworld':{'profile':{},'list_apps':{},'api_doc':{'app':'name','api':'optional'},'app_call':{'app':'name','api':'name','arguments':'object'}}}[self.scenario]
    def maybe_update(self,tool,event_id,result):
        u=self.task.get('update')
        if not self.updated and u and tool in u['trigger_tools'] and result.get('ok') and result.get('exposed',True):
            self.updated=True;self.version=u['target_version'];self.assets[u['asset']]=self.version
            if u.get('target_asset'):self.dbfile=u['target_asset']
            if u['asset']=='traces':self.trace_state='available'
            return {'version':self.version,'changed_asset':u['asset'],'notice':u['notice'],'exposure_event':event_id}
    def snapshot(self):
        folder=self.task['conditions'].get('snapshot_folder',{'r0':'v0','r1':'v1','r2':'fixed'}[self.version])
        return ROOT/'assets'/self.dataset/folder
    def call(self,name,args,actor='worker:unknown'):
        name={'search':'search_nodes','query':'select','read_artifact':'artifact_read'}.get(name,name)
        start=time.perf_counter(); cpu=time.thread_time();work=Counter(tool_attempts=1)
        with self._lock:
            version=self.version;self.context.version=version;self.context.dbfile=self.dbfile;self.context.actor=actor
        if self.task['conditions'].get('controlled_delay_seconds'):time.sleep(self.task['conditions']['controlled_delay_seconds'])
        try:
            if name not in self.tools:raise DomainError('Unknown domain operation: '+name)
            with self._lock:
                if self.task['conditions'].get('first_read_fault') and not self.read_fault and name not in ('schema','list_files','api_doc','list_apps'):
                    self.read_fault=True;raise DomainError('RECOVERABLE_READ_FAILURE: no records were returned; retry is permitted.')
            data,morework,refs=getattr(self,'_'+self.scenario)(name,args);work.update(morework)
            ok=not(isinstance(data,dict) and data.get('error'))
            if not ok:work['failed_tools']+=1
            return {'ok':ok,'data':data,'work':dict(work),'source_refs':refs,'version':version,'wall_seconds':time.perf_counter()-start,'cpu_seconds':time.thread_time()-cpu}
        except Exception as e:
            work.update(getattr(e,'work',{}));work['failed_tools']+=1
            return {'ok':False,'data':{'error':type(e).__name__,'detail':str(e)[:800]},'work':dict(work),'source_refs':[],'version':version,'wall_seconds':time.perf_counter()-start,'cpu_seconds':time.thread_time()-cpu}
    def _graph(self,name,a):
        limit=int(a.get('limit',120));offset=int(a.get('offset',0))
        if not 1<=limit<=1000 or offset<0:raise DomainError('limit must be 1..1000; offset nonnegative')
        c=sqlite3.connect(f'file:{ROOT.as_posix()}/assets/{getattr(self.context,'dbfile',self.dbfile)}?mode=ro',uri=True);c.row_factory=sqlite3.Row;ticks=[0];c.set_progress_handler(lambda:ticks.__setitem__(0,ticks[0]+1000) or 0,1000)
        try:
            if name=='search_nodes':
                q='SELECT * FROM nodes WHERE lower(name) LIKE ?';p=['%'+str(a['text']).lower()+'%']
                if a.get('type'):q+=' AND type=?';p.append(a['type'])
                q+=' ORDER BY id'
            else:
                ids=a.get('ids',[])
                if not isinstance(ids,list) or len(ids)>100 or any(type(i) is not int for i in ids):raise DomainError('ids requires at most 100 integers; oversized batches are rejected, never truncated')
                if len(ids)!=len(set(ids)):raise DomainError('duplicate IDs in a single request')
                ph=','.join('?'*len(ids));p=ids
                if name=='nodes':q=f'SELECT * FROM nodes WHERE id IN ({ph}) ORDER BY id'
                else:
                    if a.get('direction','out') not in ('in','out'):raise DomainError('direction must be in or out')
                    k,o=('src','dst') if a.get('direction','out')=='out' else ('dst','src')
                    q=f'SELECT e.src,e.dst,e.type,n.id,n.type node_type,n.name,n.year,n.citations FROM edges e JOIN nodes n ON n.id=e.{o} WHERE e.{k} IN ({ph})'
                    if a.get('edge_type') is not None:q+=' AND e.type=?';p=p+[int(a['edge_type'])]
                    q+=' ORDER BY e.src,e.dst,e.type'
            rows=[dict(r) for r in c.execute(q+' LIMIT ? OFFSET ?',p+[limit+1,offset])]
        finally:c.close()
        refs=[{'source':'graph','version':self.version,'identity':{k:r[k] for k in ('src','dst','type') if k in r} if 'src' in r else {'node_id':r['id']}} for r in rows[:limit]]
        return {'rows':rows[:limit],'has_more':len(rows)>limit,'next_offset':offset+limit if len(rows)>limit else None}, {'returned_records':min(len(rows),limit),'pages':1,'sqlite_vm_steps_lower_bound':ticks[0]},refs
    def _analytics(self,name,a):
        version=getattr(self.context,'version',self.version);path=ROOT/'assets'/getattr(self.context,'dbfile',self.dbfile);c=sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True);tables=set();cols=set();steps=[0];beg=time.perf_counter()
        try:
            if name=='schema':
                data={n:[list(r) for r in c.execute('PRAGMA table_info("'+n.replace('"','""')+'")')] for n, in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                return data,{'schema_reads':1},[{'source':self.dataset,'version':version,'identity':{'schema':True}}]
            def auth(op,p1,p2,db,tr):
                if op==sqlite3.SQLITE_READ:tables.add(p1);cols.add((p1,p2))
                if op in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_RECURSIVE):return sqlite3.SQLITE_OK
                if op==sqlite3.SQLITE_FUNCTION and str(p2).lower() not in ('load_extension','readfile','writefile'):return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY
            c.set_authorizer(auth)
            def progress():steps[0]+=1000;return int(time.perf_counter()-beg>20)
            c.set_progress_handler(progress,1000)
            if name=='row_lookup':
                if not all(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',a[k]) for k in ('table','key')):raise DomainError('Invalid SQL identifier')
                sql=f'SELECT * FROM "{a["table"]}" WHERE "{a["key"]}"=?';params=[a['value']]
            else:sql=a['sql'].strip().rstrip(';');params=[]
            if name=='explain':sql='EXPLAIN QUERY PLAN '+sql
            limit=int(a.get('limit',1000));offset=int(a.get('offset',0))
            if limit<1 or limit>1000 or offset<0:raise DomainError('limit 1..1000; offset nonnegative')
            cur=c.execute(sql,params);names=[x[0] for x in cur.description]
            for _ in range(offset):
                if cur.fetchone() is None:break
            rows=[list(r) for r in cur.fetchmany(limit+1)];data={'columns':names,'rows':rows[:limit],'has_more':len(rows)>limit,'next_offset':offset+limit if len(rows)>limit else None,'read_tables':sorted(tables),'read_columns':sorted([list(x) for x in cols]),'sql':sql,'parameters':params}
            refs=[{'source':self.dataset,'version':version,'identity':dict(zip(names,r)),'tables':sorted(tables)} for r in rows[:limit]]
            return data,{'returned_rows':min(limit,len(rows)),'sqlite_vm_steps_lower_bound':steps[0],'queries':1},refs
        except Exception as e:
            e.work={'sqlite_vm_steps_lower_bound':steps[0],'failed_queries':1};raise
        finally:c.close()
    def _code_review(self,name,a):
        repo=self.snapshot();refs=[];work={}
        if name=='list_files':
            data=sorted(str(p.relative_to(repo)).replace('\\','/') for p in repo.rglob('*') if p.is_file() and '__pycache__' not in str(p) and str(p.relative_to(repo)).replace('\\','/').startswith(a.get('prefix','')));work={'files_listed':len(data)}
        elif name in ('read_file','read_probe_inputs'):
            rel='REGISTERED_CHECKS.py' if name=='read_probe_inputs' else a['path'];p=(repo/rel).resolve()
            if not p.is_relative_to(repo.resolve()) or p.suffix not in ('.py','.md','.rst','.txt','.toml','.cfg',''):raise DomainError('Only public text files inside this snapshot are readable')
            lines=p.read_text(encoding='utf-8').splitlines();start=max(1,int(a.get('start',1)));length=min(1000,max(1,int(a.get('lines',200))))
            data={'path':rel,'lines':lines[start-1:start-1+length],'start':start,'total_lines':len(lines),'sha256':sha(p)};work={'source_lines_read':len(data['lines']),'source_bytes_read':sum(len(x.encode()) for x in data['lines'])}
            refs=[{'source':self.dataset,'version':self.version,'identity':{'path':rel,'sha256':sha(p),'line_start':start,'line_end':start+len(data['lines'])-1}}]
        elif name=='search_source':
            hits=[];count=0
            for p in sorted(repo.rglob('*')):
                if p.is_file() and p.suffix in ('.py','.md','.rst','.txt'):
                    s=p.read_text(encoding='utf-8',errors='replace');count+=len(s.encode());hits.extend({'path':str(p.relative_to(repo)).replace('\\','/'),'line':i+1,'text':z} for i,z in enumerate(s.splitlines()) if a['text'].lower() in z.lower())
            off=int(a.get('offset',0));lim=min(1000,int(a.get('limit',100)));data={'hits':hits[off:off+lim],'has_more':len(hits)>off+lim,'next_offset':off+lim if len(hits)>off+lim else None};work={'source_bytes_scanned':count}
        elif name=='run_checks':
            spec=load(ROOT/f'protocol/{self.dataset}_checks.json');catalog={x['name']:x for x in spec['public_checks']}
            if not a.get('check_names'):return {'available_checks':spec['public_checks']},{'catalog_reads':1},[]
            if not isinstance(a['check_names'],list) or any(x not in catalog for x in a['check_names']):raise DomainError('Unknown public check name')
            results=[]
            for name in a['check_names']:
                runner='observe_expansion.py' if spec['family_id'] in ('packaging','dotenv') else 'observe.py'
                p=subprocess.run([sys.executable,str(ROOT/'vendor'/runner),str(repo),spec['family_id'],catalog[name]['runner_name']],capture_output=True,text=True,encoding='utf-8',timeout=60,env={**os.environ,'PYTHONUTF8':'1'})
                if p.returncode:raise DomainError('Native check process failed: '+p.stderr[-600:])
                obj=json.loads(p.stdout);observations=obj.get('observations',[]);results.append({'check':name,'observations':observations,'exitcode':p.returncode})
                refs.extend({'source':self.dataset,'version':self.version,'identity':{'check_id':name,'case_id':x['case_id']},'observed':x['observed_outcome']} for x in observations)
            data={'checks':results};work={'registered_checks':len(results),'native_cases':len(refs)}
        else:raise DomainError('Unsupported code operation')
        return data,work,refs
    def _incident(self,name,a):
        if name=='service_catalog':return {'services':sorted(set(self.traces.serviceName))},{'catalog_reads':1},[]
        channel='metrics' if name=='metric_summary' else 'logs' if name=='log_search' else 'traces'
        if channel=='traces' and self.trace_state!='available':raise DomainError('CHANNEL_'+self.trace_state.upper()+': traces have not been observed')
        refs=[];off=int(a.get('offset',0));lim=min(1000,int(a.get('limit',100)))
        if name=='metric_summary':
            cols=[x for x in self.metric.columns if x!='time' and a.get('filter','') in x and (not a.get('service') or x.startswith(a['service']+'_'))];rows=[]
            for x in cols:
                pre=float(self.metric.loc[self.metric.time<self.cut,x].mean());post=float(self.metric.loc[self.metric.time>=self.cut,x].mean());rows.append({'metric':x,'pre_mean':pre,'post_mean':post,'ratio':post/pre if pre else None})
            rows.sort(key=lambda x:-(x['ratio'] or 0));data={'rows':rows[off:off+lim],'has_more':len(rows)>off+lim,'next_offset':off+lim if len(rows)>off+lim else None};work={'metric_values_read':len(cols)*len(self.metric)}
        elif name=='log_search':
            m=self.logs.message.str.contains(a.get('regex','error|fail|timeout'),case=False,regex=True)
            if a.get('service'):m &= self.logs.container_name==a['service']
            found=self.logs[m];data={'count':len(found),'by_service':found.groupby('container_name').size().to_dict(),'samples':found.iloc[off:off+lim].to_dict('records'),'has_more':len(found)>off+lim};work={'log_records_scanned':len(self.logs)}
        elif name=='trace_summary':
            rows=[]
            for svc,g in self.traces.groupby('serviceName'):
                if a.get('service') and a['service']!=svc:continue
                x=float(g.loc[g.startTimeMillis<self.cut*1000,'duration'].median());y=float(g.loc[g.startTimeMillis>=self.cut*1000,'duration'].median());rows.append({'service':svc,'pre_median_duration':x,'post_median_duration':y,'ratio':y/x if x else None,'records':len(g)})
            data=sorted(rows,key=lambda x:-(x['ratio'] or 0));work={'trace_records_scanned':len(self.traces)}
        else:
            tr=self.traces;parents=tr[['traceID','spanID','serviceName']].rename(columns={'spanID':'parentSpanID','serviceName':'parent_service'});j=tr[tr.serviceName==a['service']].merge(parents,on=['traceID','parentSpanID'],how='left');data=j.groupby(['parent_service','serviceName','operationName'],dropna=False).size().reset_index(name='count').sort_values('count',ascending=False).iloc[off:off+lim].to_dict('records');work={'trace_records_scanned':len(tr)}
        def finite(v):
            if isinstance(v,float) and not math.isfinite(v):return None
            if isinstance(v,dict):return {k:finite(x) for k,x in v.items()}
            if isinstance(v,list):return [finite(x) for x in v]
            return v
        data=finite(data);refs=[{'source':self.dataset,'version':self.version,'identity':{'channel':channel,'service':a.get('service','all'),'cut_timestamp':self.cut,'statistic':name,'filter':a.get('filter',a.get('regex',''))}}]
        return data,work,refs
    def _bridge(self,req):
        with self._lock:
            if not self.proc:
                env={**os.environ,'PYTHONUTF8':'1','RCWG_RELEASE_ROOT':str(ROOT)}
                self.proc=subprocess.Popen([config()['appworld_python'],'-u',str(ROOT/'vendor/native_bridge.py'),self.episode,self.task.get('native_task_id','22cc237_1')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',env=env)
                self.responses=queue.Queue();self.stderr=[]
                def reader():
                    for s in self.proc.stdout:
                        try:self.responses.put(json.loads(s))
                        except ValueError:self.stderr.append(s)
                threading.Thread(target=reader,daemon=True).start();threading.Thread(target=lambda:self.stderr.extend(self.proc.stderr.readlines()),daemon=True).start()
            self.proc.stdin.write(dump(req)+'\n');self.proc.stdin.flush()
            try:r=self.responses.get(timeout=120)
            except queue.Empty:raise DomainError('Native AppWorld bridge watchdog; '+''.join(self.stderr)[-500:])
            return r
    def _appworld(self,name,a):
        mutating=name=='app_call' and a.get('api')=='create_payment_request'
        fault=self.task['conditions'].get('fault')
        with self._lock:
            if fault=='stale_two_readers' and name=='app_call' and a.get('api')=='show_sent_payment_requests' and len(self.concurrent_readers)<2:
                actor=getattr(self.context,'actor','worker:unknown')
                fresh=self.concurrent_snapshot is None
                if fresh:self.concurrent_snapshot=self._bridge({'op':name,**a})
                self.concurrent_readers.add(actor);result=copy.deepcopy(self.concurrent_snapshot)
                private={k:result.pop(k) for k in ('business_committed','state_hash','native_calls') if k in result}
                return result,{'app_api_calls':result.get('api_calls',0) if fresh else 0,'snapshot_reads':1},[{'source':'native_appworld','version':private.get('state_hash','unknown'),'identity':{'snapshot_read':True,'api':'show_sent_payment_requests'}}]
            if mutating and fault=='stale_two_readers' and len(self.concurrent_readers)<2:raise DomainError('CONCURRENCY_BARRIER: two distinct worker readers must observe the pending state before these writes are admitted. Other investigations remain available.')
            if mutating:
                self.write_count+=1
                if not self.fault_fired and (fault=='fail_before' or fault=='second_write_fails' and self.write_count==2):
                    self.fault_fired=True;self.native_private.append({'attempt':self.write_count,'committed':False,'fault':fault});raise DomainError('TRANSIENT_WRITE_FAILURE: server rejected this operation before commit. Retry after reconciliation.')
            result=self._bridge({'op':name,**a});private={k:result.pop(k) for k in ('business_committed','state_hash','native_calls') if k in result};self.native_private.append({'attempt':self.write_count,**private})
            if mutating and private.get('business_committed') and fault=='lost_after' and not self.fault_fired:
                self.fault_fired=True;result['output']='DELIVERY_UNCERTAIN: response lost; state may have changed. Inspect current state before retrying.';result['withheld']=True
        if result.get('failed'):result['error']='NativeApiFailure'
        return result,{'app_api_calls':result.get('api_calls',0),'app_mutating_calls':sum(x.get('method')!='get' for x in private.get('native_calls',[])),'business_commit_events':int(private.get('business_committed',False))},[{'source':'native_appworld','version':private.get('state_hash','unknown'),'identity':{'app':a.get('app'),'api':a.get('api'),'arguments':a.get('arguments',{})}}]
    def native_evaluate(self):return self._bridge({'op':'evaluate'})['evaluation']
    def close(self):
        if self.proc and self.proc.poll() is None:
            try:self.proc.stdin.write('{"op":"close"}\n');self.proc.stdin.flush();self.proc.wait(timeout=15)
            except Exception:self.proc.terminate()
        self.closed=True
