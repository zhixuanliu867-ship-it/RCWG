"""Private OpenRouter transport with durable, atomic pre-dispatch accounting.

Only this module sends paid requests. Never place credentials in artifacts.
"""
from __future__ import annotations
import contextlib
import datetime as dt
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor' / 'rcwg_legacy'))
from evidence import canonical, digest, write

MODEL = 'google/gemini-3.8-flash'
KEY_PATH = Path('D:/Trae_Code/CodexWork/RCWG_NEXT_20261003/private-access/openrouter-key.dpapi.txt')

class BudgetStop(RuntimeError): pass
class TransportStop(RuntimeError): pass

def timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def load_key():
    key = os.environ.get('OPENROUTER_API_KEY')
    if key: return key
    # The child writes only to a pipe consumed in memory. No secret appears in
    # arguments, inherited environment, journal, exception, or terminal output.
    literal = str(KEY_PATH).replace("'", "''")
    command = (
        "$ErrorActionPreference='Stop';$p=[IntPtr]::Zero;try{"
        f"$s=Get-Content -LiteralPath '{literal}' -Raw|ConvertTo-SecureString;"
        "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);"
        "[Console]::Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($p))"
        "}finally{if($p -ne [IntPtr]::Zero){[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}}"
    )
    shell=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe'
    result = subprocess.run([str(shell) if shell.exists() else 'powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, timeout=30, creationflags=0x08000000)
    if result.returncode or not result.stdout: raise TransportStop('CREDENTIAL_UNAVAILABLE')
    return result.stdout.decode('utf-8').strip()

class Ledger:
    def __init__(self, root, ceiling=18.0):
        self.root=Path(root); self.path=self.root/'runs'/'api_ledger.sqlite'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ceiling=int(round(ceiling*1_000_000_000))
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, ceiling INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO config VALUES (1,?)',(self.ceiling,))
            if db.execute('SELECT ceiling FROM config WHERE id=1').fetchone()[0] != self.ceiling:
                raise BudgetStop('CEILING_CHANGE_REQUIRES_NEW_PROTOCOL_NOT_NEW_LEDGER')
            db.execute('''CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, episode TEXT, role TEXT, status TEXT,
                reserved INTEGER NOT NULL, cost INTEGER, created TEXT, completed TEXT,
                generation_id TEXT, request_hash TEXT, response_hash TEXT,
                prompt_tokens INTEGER, completion_tokens INTEGER, reasoning_tokens INTEGER,
                cached_tokens INTEGER, wall_seconds REAL, error_code TEXT)''')
            db.execute('CREATE TABLE IF NOT EXISTS controls (name TEXT PRIMARY KEY, value TEXT)')
    @contextlib.contextmanager
    def db(self):
        db=sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db: yield db
        finally: db.close()
    def reserve(self, rid, episode, role, amount, request_hash):
        n=math.ceil(amount*1_000_000_000)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM controls WHERE name='fuse'").fetchone():
                raise BudgetStop('UNRESOLVED_TRANSPORT_FUSE')
            committed=db.execute('SELECT COALESCE(SUM(COALESCE(cost,reserved)),0) FROM requests').fetchone()[0]
            if committed+n>self.ceiling: raise BudgetStop('EXPERIMENT_ADMISSION_LIMIT')
            db.execute('INSERT INTO requests (id,episode,role,status,reserved,created,request_hash) VALUES (?,?,?,?,?,?,?)',
                       (rid,episode,role,'RESERVED',n,timestamp(),request_hash))
    def finish(self, rid, response, wall, response_hash):
        usage=response.get('usage') or {}; cost=usage.get('cost')
        if not isinstance(cost,(int,float)) or not math.isfinite(cost) or cost<0:
            self.unknown(rid,'MISSING_COST',wall,response.get('id'))
            raise TransportStop('MISSING_COST_REQUIRES_RECONCILIATION')
        nano=math.ceil(cost*1_000_000_000)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            reserve=db.execute('SELECT reserved FROM requests WHERE id=?',(rid,)).fetchone()[0]
            db.execute('''UPDATE requests SET status='SETTLED', cost=?,completed=?,generation_id=?,response_hash=?,
                prompt_tokens=?,completion_tokens=?,reasoning_tokens=?,cached_tokens=?,wall_seconds=? WHERE id=?''',
                (nano,timestamp(),response.get('id'),response_hash,usage.get('prompt_tokens'),usage.get('completion_tokens'),
                 (usage.get('completion_tokens_details') or {}).get('reasoning_tokens'),
                 (usage.get('prompt_tokens_details') or {}).get('cached_tokens'),wall,rid))
            if nano>reserve:
                db.execute("INSERT OR REPLACE INTO controls VALUES ('fuse','COST_EXCEEDS_RESERVATION')")
        if nano>reserve:
            raise BudgetStop('COST_EXCEEDS_RESERVATION')
    def unknown(self,rid,code,wall,generation=None):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE requests SET status='UNKNOWN', completed=?,error_code=?,wall_seconds=?,generation_id=? WHERE id=?",
                       (timestamp(),code,wall,generation,rid))
            db.execute("INSERT OR REPLACE INTO controls VALUES ('fuse',?)",(code,))
    def summary(self):
        with self.db() as db:
            db.row_factory=sqlite3.Row
            rows=[dict(x) for x in db.execute('SELECT * FROM requests ORDER BY created,id')]
            fuse=db.execute("SELECT value FROM controls WHERE name='fuse'").fetchone()
        return {'requests':rows,'request_count':len(rows),'settled_cost_usd':sum(x['cost'] or 0 for x in rows)/1e9,
                'unresolved_reserved_usd':sum(x['reserved'] for x in rows if x['cost'] is None)/1e9,
                'committed_usd':sum(x['cost'] if x['cost'] is not None else x['reserved'] for x in rows)/1e9,
                'admission_ceiling_usd':self.ceiling/1e9,'absolute_user_ceiling_usd':20.0,
                'fuse':fuse[0] if fuse else None}

class APIClient:
    def __init__(self, root=ROOT, *, api_key=None, ceiling=18.0, timeout=150, max_parallel=4):
        self.root=Path(root); self.ledger=Ledger(root,ceiling); self.key=api_key or load_key()
        self.timeout=timeout; self.slots=threading.BoundedSemaphore(max_parallel)
        self.journal=self.root/'runs'/'api'; self.journal.mkdir(parents=True,exist_ok=True)
    def get(self,path):
        req=urllib.request.Request('https://openrouter.ai/api/v1/'+path,
                                   headers={'Authorization':'Bearer '+self.key})
        with urllib.request.urlopen(req, timeout=30) as resp: return json.load(resp)
    def key_snapshot(self):
        d=self.get('key')['data']
        return {k:d.get(k) for k in ['limit','limit_remaining','usage','usage_daily','limit_reset','is_free_tier','include_byok_in_limit']}
    def chat(self,messages,tools=None,*,role,episode_id,max_tokens,metadata=None):
        if not isinstance(max_tokens,int) or not 128<=max_tokens<=8192: raise ValueError('OUTPUT_LIMIT')
        body={'model':MODEL,'messages':messages,'max_tokens':max_tokens,'temperature':0.2,
              'reasoning':{'effort':'low'},'stream':False,
              'provider':{'only':['google-ai-studio'],'ignore':['google-ai-studio/flex','google-ai-studio/priority'],
                          'allow_fallbacks':False,'require_parameters':True,
                          'max_price':{'prompt':0.8,'completion':4.0}}, 'plugins':[]}
        if tools: body['tools']=tools; body['tool_choice']='auto'
        raw=canonical(body)
        # UTF-8 bytes plus serialization margin conservatively bound text tokens.
        # Count completion twice to cover any separately billed reasoning ambiguity;
        # actual usage.cost is authoritative and reasoning is not double-added there.
        reservation=(len(raw)+4096)*0.8/1e6 + 2*max_tokens*4/1e6 + 0.005
        rid='req-'+uuid.uuid4().hex
        waiting_start=time.perf_counter()
        with self.slots:
            admission_wait=time.perf_counter()-waiting_start
            self.ledger.reserve(rid,episode_id,role,reservation,digest(body))
            folder=self.journal/rid; folder.mkdir(exist_ok=False)
            write(folder/'request.json',body)
            write(folder/'local.json',{'request_id':rid,'episode_id':episode_id,'role':role,'metadata':metadata or {},
                                     'created_at':timestamp(),'reservation_usd':reservation})
            request=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',data=raw,
                headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json',
                         'X-OpenRouter-Title':'RCWG Code Review 20261011'},method='POST')
            start=time.perf_counter()
            try:
                with urllib.request.urlopen(request,timeout=self.timeout) as response:
                    response_raw=response.read()
                write(folder/'response.json',response_raw)
                data=json.loads(response_raw)
                wall=time.perf_counter()-start
                if 'error' in data or not data.get('choices'):
                    raise TransportStop('PROVIDER_ERROR_OR_EMPTY_CHOICES')
            except BaseException as e:
                wall=time.perf_counter()-start
                code='HTTP_'+str(e.code) if isinstance(e,urllib.error.HTTPError) else type(e).__name__
                # Raw HTTP bodies may contain provider messages, but never auth headers.
                if isinstance(e,urllib.error.HTTPError):
                    try: write(folder/'error_body.txt',e.read())
                    except Exception: pass
                write(folder/'failure.json',{'error_code':code,'wall_seconds':wall,'at':timestamp()})
                self.ledger.unknown(rid,code,wall)
                raise TransportStop(code) from None
            self.ledger.finish(rid,data,wall,digest(data))
            data['_accounting']={'request_id':rid,'wall_seconds':wall,'role':role,
                                 'admission_wait_seconds':admission_wait,
                                 'request_bytes':len(raw),'response_bytes':len(response_raw),
                                 'cost_usd':data['usage']['cost'],'reservation_usd':reservation}
            write(folder/'receipt.json',data['_accounting'])
            return data

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['status','smoke'])
    args=parser.parse_args()
    client=APIClient()
    if args.action=='status': print(json.dumps({'key':client.key_snapshot(),'ledger':client.ledger.summary()},ensure_ascii=False))
    else:
        result=client.chat([{'role':'user','content':'Reply with exactly READY.'}],role='development',episode_id='DEV-transport-01',max_tokens=512)
        print(json.dumps({'id':result.get('id'),'model':result.get('model'),'provider':result.get('provider'),
                          'message':result['choices'][0]['message'],'usage':result.get('usage'),'accounting':result['_accounting']},ensure_ascii=False))
