"""Pinned SSH/IAP transport; no API credentials or gold are copied to workers."""
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,subprocess,shlex,tarfile,time,uuid
from rcwg_full.evidence import read,write,sha,digest,source_hashes
from rcwg_full.services.broker import SemanticBroker
from rcwg_full.verification.prepared import check_prepared


class RemoteExecutor:
    def __init__(self,root):
        self.root=Path(root).absolute();self.config=json.loads(read(self.root/'RUN_CONFIG.json'));self.remote=self.config['remote']
        self.target=self.remote['user']+'@127.0.0.1'
        session=['-load',self.remote['ssh_session']] if self.remote.get('ssh_session') else []
        self.common=[*session,'-batch','-P',str(self.remote['port']),'-hostkey',self.remote['host_key'],'-i',self.remote['key_reference']]
        self.cached=None;self.cached_at=0

    def ssh(self,command,*,reverse=None,timeout=120):
        argv=[self.remote['plink'],*self.common]
        if reverse:argv+=['-R',reverse]
        return subprocess.run([*argv,self.target,command],capture_output=True,timeout=timeout)

    def transfer(self,source,target):
        result=subprocess.run([self.remote['pscp'],*self.common,source,target],capture_output=True,timeout=300)
        if result.returncode:raise ConnectionError('SSH_FILE_TRANSFER_FAILED:'+result.stderr.decode('utf8',errors='replace')[:200])

    def identity(self):
        if self.cached is not None and time.monotonic()-self.cached_at<3:return dict(self.cached)
        p=self.ssh(self.remote['identity_command'],timeout=45)
        if p.returncode:raise ConnectionError('REMOTE_IDENTITY_UNAVAILABLE')
        record=json.loads(p.stdout)
        if record['source']!=digest(source_hashes()):raise PermissionError('REMOTE_SOURCE_CHANGED')
        self.cached={k:record[k] for k in ['boot','host','build','dependencies']};self.cached_at=time.monotonic()
        return dict(self.cached)

    def execute(self,job,plan,service,*,reference=False):
        ident=str(uuid.uuid5(uuid.NAMESPACE_URL,'AUTO2-WORKER:'+job['id']));out=self.root/'private/worker'/ident
        pending=self.root/'private/dispatch'/(ident+'.json');pending.parent.mkdir(parents=True,exist_ok=True)
        if pending.exists():return {'status':'SENT_UNCONFIRMED','reason':'WORKER_DISPATCH_ALREADY_ATTEMPTED_NO_REPLAY','job':job,'attempt_id':ident}
        self.identity();raw=read(self.root/job['task_file'])
        if sha(raw)!=job['task_file_sha256']:raise PermissionError('FROZEN_PUBLIC_TASK_CHANGED')
        task=json.loads(raw)
        if sha(read(self.root/job['private_verifier']))!=job['private_verifier_sha256']:raise PermissionError('FROZEN_PRIVATE_GOLD_CHANGED')
        req={'source_hash':digest(source_hashes()),'task_hash':digest(task),'data_directory':job['remote_data_directory'],
             'manifest_hash':job['remote_manifest_hash'],'condition':job['condition'],'plan':plan,'attempt_id':ident,
             'output':self.remote['run_directory']+'/'+ident,'build':self.remote['build'],'generation_id':job.get('generation_id'),
             'record_role':'REFERENCE' if reference else 'MODEL','host_scope':job.get('host_scope'),
             'host_scope_hash':job.get('host_scope_hash'),'authority':self.remote.get('authority')}
        broker=None
        try:
            reverse=None
            if service is not None:
                broker=SemanticBroker(service);connection=broker.connection()
                reverse='9900:127.0.0.1:'+str(connection['port']);connection['port']=9900
                req.update(semantic_connection=connection,service_binding=service.client.binding)
            local=self.root/'private/dispatch'/(ident+'-request.json');write(local,req)
            remote=self.remote['request_directory']+'/'+ident+'.json'
            self.transfer(str(local),self.target+':'+remote)
            # Durable worker dispatch marker precedes execution, including crashes.
            write(pending,{'request_hash':digest(req),'attempt_id':ident,'status':'SENDING','job':job})
            cmd=self.remote['execute_command_prefix']+' '+shlex.quote(remote)
            response=self.ssh(cmd,reverse=reverse,timeout=task['resources']['wall_timeout_s']+120)
            out.mkdir(parents=True,exist_ok=True)
            write(out/'ssh-result.json',{'exit_code':response.returncode,'stdout':response.stdout.decode('utf8',errors='replace'),
                                       'stderr':response.stderr.decode('utf8',errors='replace')})
            export=self.ssh(self.remote['export_command_prefix']+' '+shlex.quote(ident),timeout=90)
            if export.returncode:return {'status':'SENT_UNCONFIRMED','job':job,'attempt_id':ident,'reason':'REMOTE_RESULT_UNAVAILABLE'}
            archive=out/'evidence.tar.gz'
            self.transfer(self.target+':'+self.remote['export_directory']+'/'+ident+'.tar.gz',str(archive))
            with tarfile.open(archive) as tf:
                members=tf.getmembers()
                if sum(m.size for m in members)>512*1024**2:raise ValueError('EVIDENCE_EXPORT_SIZE')
                for m in members:
                    if m.issym() or m.islnk() or m.isdev() or Path(m.name).is_absolute() or '..' in Path(m.name).parts:raise ValueError('EVIDENCE_EXPORT_PATH')
                tf.extractall(out/'files',filter='data')
            report=json.loads(read(out/'files/report.json'));verification={'status':'UNKNOWN','reason':'NO_COMPLETED_RESULT'}
            if report['terminal_status']=='COMPLETED':
                actual=json.loads(read(out/'files/worker/result.json'))
                verification=check_prepared(actual,self.root/job['private_verifier'])
            return {'status':report['terminal_status'],'verification':verification,'job':job,'attempt_id':ident,
                    'report_sha256':sha(read(out/'files/report.json')),'archive_sha256':sha(read(archive)),
                    'measurement_validity':report['measurement_validity'],'budget_within':report['measurements'].get('budget_within'),
                    'exec_elapsed_ns':report.get('exec_elapsed_ns'),'measurement_profile':'SERVICE_ONLY','formal_ready':False}
        finally:
            if broker:broker.close()

    def formal_readiness(self,available):
        manifest=json.loads(read(self.root/'FORMAL_PREREQUISITES.json'))
        blockers=list(manifest['blockers'])
        if len(available)!=6:blockers.append('SIX_GENERATOR_COVERAGE_MISSING')
        if self.config['measurement_profile']!='FORMAL_RESOURCE':blockers.append('RESOURCE_CALIBRATION_NOT_CLOSED')
        return {'status':'NOT_ADMITTED' if blockers else 'REQUIRES_EXACT_BLOCK_GATE','blockers':sorted(set(blockers)),
                'formal_generation':0,'formal_execution':0,'original_planned_generation':23040,'original_planned_execution':61440,
                'historical_planned_total':150880,'human_reapproval_required':False}
