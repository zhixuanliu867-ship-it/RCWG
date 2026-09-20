"""Crash-tolerant, exclusive journals and read-only denominator reconciliation."""
from pathlib import Path
import json
import time
from rcwg_native.evidence import write,read,sha,no_symlink

class Journal:
    def __init__(self,path):
        self.path=no_symlink(path);self.path.mkdir(mode=0o700);self.sequence=0;self.previous=None
    def emit(self,stage,value):
        record={'sequence':self.sequence,'previous_sha256':self.previous,'stage':stage,
                'monotonic_ns':time.monotonic_ns(),'value':value}
        self.previous=write(self.path/('%06d.json'%self.sequence),record);self.sequence+=1
        return self.previous

def inspect_journal(path):
    records=[];previous=None;errors=[]
    for i,p in enumerate(sorted(Path(path).glob('*.json'))):
        try:
            raw=p.read_bytes();r=json.loads(raw)
            if r['sequence']!=i or r['previous_sha256']!=previous:raise ValueError('CHAIN_MISMATCH')
            previous=sha(raw);records.append(r)
        except (OSError,ValueError,KeyError) as e:errors.append({'file':p.name,'error':str(e)});break
    return {'records':records,'errors':errors,'last_sha256':previous}

def reconcile(manifest,directory):
    """No cgroup writes, process creation or mutation of original run evidence."""
    directory=no_symlink(directory);rows=[]
    for slot in manifest['slots']:
        d=directory/slot['run_id'];terminal=d/'terminal.json'
        status='NOT_RUN';reason='NO_ATTEMPT_CLAIM';result=None
        if d.exists():
            status='UNKNOWN';reason='ATTEMPT_WITHOUT_VALID_TERMINAL'
            try:
                result=read(terminal)
                if result['run_id']!=slot['run_id'] or result['slot_sha256']!=sha(__import__('rcwg_native.evidence',fromlist=['canonical']).canonical(slot)):
                    raise ValueError('SLOT_BINDING_MISMATCH')
                status=result['terminal_status'];reason=result.get('reason')
                if (d/'ARCHIVE_FAILURE.json').exists():status='INFRA_FAILURE';reason='ARCHIVE_FAILED'
                if (d/'seal.anchor').exists():
                    from rcwg_native.evidence import reread
                    reread(d,(d/'seal.anchor').read_text())
                    chain=inspect_journal(d/'journal')
                    if chain['errors'] or chain['last_sha256']!=read(d/'JOURNAL_ANCHOR.json')['sha256']:raise ValueError('JOURNAL_INTEGRITY_FAILURE')
            except (OSError,ValueError,KeyError):status='UNKNOWN';reason='TERMINAL_OR_SEAL_INTEGRITY_UNRESOLVED'
        rows.append({'run_id':slot['run_id'],'case':slot['case'],'status':status,'reason':reason,'result':result,
                     'journal':inspect_journal(d/'journal') if (d/'journal').exists() else None})
    return {'expected':len(manifest['slots']),'slots':rows,'formal_ready':False,'budget_within':None}
