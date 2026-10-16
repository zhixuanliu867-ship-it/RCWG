"""Registered observation runner: outputs actual behaviour, never gold labels."""
import sys,json,io,hashlib
from pathlib import Path

repo=Path(sys.argv[1]).resolve(); family=sys.argv[2]; check=sys.argv[3]
family={'redirect_matrix':'R1','prepared_redirects':'R1','replay_matrix':'R2','copy_metadata':'R2','migration_matrix':'I1','unsafe_migration':'I1','age_matrix':'I2','age_entrypoints':'I2'}.get(check,family)
sys.path.insert(0,str(repo/'src'))

def safe(fn):
 try:
  value=fn()
  if isinstance(value,bytes):value=value.decode('utf-8','replace')
  return {'returned':value}
 except Exception as e:return {'exception':type(e).__name__}

def redirect_run(old,new,status=302,follow=True,body=None,cookies=None):
 import requests
 from requests.adapters import BaseAdapter
 class Transport(BaseAdapter):
  def __init__(self):self.seen=[]
  def send(self,request,**kwargs):
   data=request.body
   if hasattr(data,'read'):data=data.read()
   if isinstance(data,bytes):data=data.decode()
   self.seen.append({'url':request.url,'method':request.method,'authorization':request.headers.get('Authorization'),'cookie':request.headers.get('Cookie'),'body':data,'body_position':repr(request._body_position)})
   r=requests.Response();r.status_code=status if len(self.seen)==1 else 200
   r._content=b'';r.raw=io.BytesIO(b'');r.request=request;r.url=request.url
   if len(self.seen)==1:r.headers['Location']=new
   return r
  def close(self):pass
 s=requests.Session();s.trust_env=False;a=Transport();s.mount('http://',a);s.mount('https://',a)
 req=requests.Request('POST' if body is not None else 'GET',old,headers={'Authorization':'Bearer example-token'},data=body,cookies=cookies)
 p=s.prepare_request(req);r=s.send(p,allow_redirects=follow)
 out={'sent':a.seen}
 if not follow and r.next is not None:out['next']={'url':r.next.url,'authorization':r.next.headers.get('Authorization'),'cookie':r.next.headers.get('Cookie'),'method':r.next.method}
 return out

def requests_checks():
 out=[]
 if family=='R1':
  cases=[('same_origin','https://a.example/x','https://a.example/y'),('default_alias','https://a.example/x','https://a.example:443/y'),('other_host','https://a.example/x','https://b.example/y'),('standard_upgrade','http://a.example/x','https://a.example/y'),('standard_explicit_upgrade','http://a.example:80/x','https://a.example:443/y'),('downgrade_same_port','https://a.example:443/x','http://a.example:443/y'),('upgrade_nonstandard_same_port','http://a.example:8080/x','https://a.example:8080/y'),('upgrade_nonstandard_ports','http://a.example:8080/x','https://a.example:8443/y')]
  for cid,a,b in cases:out.append({'case_id':cid,**safe(lambda a=a,b=b:redirect_run(a,b,follow=check=='redirect_matrix'))})
  from requests.cookies import RequestsCookieJar
  jar=RequestsCookieJar();jar.set('session','example-cookie',domain='a.example',path='/private')
  for cid,dest in [('cookie_domain','https://b.example/private/y'),('cookie_path','https://a.example/public/y'),('cookie_same_scope','https://a.example/private/y')]:
   out.append({'case_id':cid,**safe(lambda dest=dest:redirect_run('https://a.example/private/x',dest,follow=check=='redirect_matrix',cookies=jar))})
  multi=RequestsCookieJar();multi.set('session','one',domain='a.example');multi.set('session','two',domain='b.example')
  out.append({'case_id':'cookie_duplicate_names',**safe(lambda:redirect_run('https://a.example/private/x','https://b.example/private/y',follow=check=='redirect_matrix',cookies=multi))})
 else:
  if check=='replay_matrix':
   for status in [307,308,302]:
    for offset in [0,7]:
     b=io.BytesIO(b'prefix:PAYLOAD');b.seek(offset)
     out.append({'case_id':f'redirect_{status}_offset_{offset}',**safe(lambda b=b,status=status:redirect_run('https://upload.example/a','https://upload.example/b',status,True,b))})
  else:
   from requests import Request,Session
   from requests.utils import rewind_body
   for offset in [0,7]:
    b=io.BytesIO(b'prefix:PAYLOAD');b.seek(offset)
    p=Session().prepare_request(Request('POST','https://upload.example',data=b));b.read();q=p.copy()
    observed={'original_position':p._body_position,'copied_position':q._body_position}
    observed['rewind']=safe(lambda:(rewind_body(q),q.body.read().decode())[1])
    out.append({'case_id':f'copy_offset_{offset}','returned':observed})
   class NoTell(io.BytesIO):
    def tell(self):raise OSError('position unavailable')
   p=Session().prepare_request(Request('POST','https://upload.example',data=NoTell(b'PAYLOAD')))
   out.append({'case_id':'position_unavailable',**safe(lambda:'unavailable_position_preserved' if p.copy()._body_position is p._body_position else 'position_changed')})
 return out

def migration_checks():
 from itsdangerous import Serializer,URLSafeSerializer,TimedSerializer,URLSafeTimedSerializer
 variants=[('plain',Serializer),('urlsafe',URLSafeSerializer),('timed',TimedSerializer),('urlsafe_timed',URLSafeTimedSerializer)]
 out=[]
 for name,cls in variants:
  for key in ['old-key','new-key']:
   for digest in ['sha1','sha256']:
    for salt in ['configured','request-specific']:
     digestfn=getattr(hashlib,digest)
     maker=cls(key,salt='configured',signer_kwargs={'digest_method':digestfn})
     reader=cls(['old-key','new-key'],salt='configured',signer_kwargs={'digest_method':hashlib.sha256},fallback_signers=[{'digest_method':hashlib.sha1}])
     token=maker.dumps({'record':17},salt=salt)
     method=reader.loads_unsafe if check=='unsafe_migration' else reader.loads
     cid=f'{name}_{key}_{digest}_{salt}'
     out.append({'case_id':cid,**safe(lambda method=method,token=token,salt=salt:method(token,salt=salt))})
  maker=cls('wrong-key');reader=cls(['old-key','new-key'])
  out.append({'case_id':f'{name}_wrong_key',**safe(lambda maker=maker,reader=reader:reader.loads(maker.dumps({'record':17})))})
  maker=cls('new-key',salt='one');reader=cls(['old-key','new-key'],salt='two')
  out.append({'case_id':f'{name}_wrong_salt',**safe(lambda maker=maker,reader=reader:reader.loads(maker.dumps({'record':17})))})
 return out

def age_checks():
 from itsdangerous import TimestampSigner,TimedSerializer,URLSafeTimedSerializer
 class ClockSigner(TimestampSigner):
  clock=1000
  def get_timestamp(self):return self.clock
 out=[]
 cases=[('zero_limit_elapsed',0,1),('zero_limit_exact',0,0),('no_limit_elapsed',None,500),('no_limit_future',None,-20),('limit_boundary',10,10),('limit_exceeded',10,11),('future_positive_limit',10,-1),('future_zero_limit',0,-1)]
 for name,cls in [('timed',TimedSerializer),('urlsafe_timed',URLSafeTimedSerializer)]:
  for cid,limit,age in cases:
   ClockSigner.clock=1000;s=cls('demo-key',signer=ClockSigner);token=s.dumps({'record':17});ClockSigner.clock=1000+age
   fn=s.loads_unsafe if check=='age_entrypoints' else s.loads
   out.append({'case_id':f'{name}_{cid}','max_age':limit,'age':age,**safe(lambda fn=fn,token=token,limit=limit:fn(token,max_age=limit))})
 if check=='age_entrypoints':
  for cid,limit,age in cases:
   ClockSigner.clock=1000;s=ClockSigner('demo-key');token=s.sign(b'payload');ClockSigner.clock=1000+age
   out.append({'case_id':f'signer_{cid}','max_age':limit,'age':age,**safe(lambda:s.validate(token,max_age=limit))})
 return out

def classify(o):
 if 'exception' in o:return 'raises:'+o['exception']
 v=o.get('returned')
 if family=='R1':
  req=v.get('next') or v['sent'][-1]
  if o['case_id'].startswith('cookie_'):return 'cookie:'+str(req.get('cookie'))
  return 'authorization_present' if req.get('authorization') else 'authorization_absent'
 if family=='R2':
  if isinstance(v,str):return v
  if 'sent' in v:
   req=v['sent'][-1]
   return 'method:'+req['method']+';body:'+str(req['body'])
  return 'position:'+str(v['copied_position'])+';replay:'+str(v['rewind'].get('returned',v['rewind'].get('exception')))
 if isinstance(v,(list,tuple)) and v and isinstance(v[0],bool):return 'accepted' if v[0] else 'rejected'
 if isinstance(v,bool):return 'accepted' if v else 'rejected'
 return 'accepted'

try:
 if check=='package_smoke':
  if family.startswith('R'):
   from requests import Request
   from requests.structures import CaseInsensitiveDict
   observations=[{'case_id':'header_case','returned':CaseInsensitiveDict({'Accept':'text/plain'})['accept']},{'case_id':'url_prepare','returned':Request('GET','https://example.invalid',params={'q':'a b'}).prepare().url}]
  else:
   from itsdangerous import URLSafeSerializer
   s=URLSafeSerializer('demo-key');observations=[{'case_id':'simple_roundtrip','returned':s.loads(s.dumps({'value':[1,2]}))}]
  for o in observations:o['observed_outcome']=json.dumps(o.get('returned'),sort_keys=True)
 else:
  observations=requests_checks() if family.startswith('R') else migration_checks() if family=='I1' else age_checks()
  for o in observations:o['observed_outcome']=classify(o)
 print(json.dumps({'check':check,'observations':observations},ensure_ascii=False,default=str))
except Exception as exc:
 print(json.dumps({'check':check,'runner_error':type(exc).__name__,'message':str(exc)}));sys.exit(2)
