"""Private loopback RPC to the runner-owned fixed semantic client, no credentials."""
import asyncio
import hmac
import secrets
import socket
import socketserver
import threading
from rcwg_full.evidence import canonical,digest
from rcwg_api.common import strict

MAX_WIRE=2*1024*1024


class SemanticBroker:
    def __init__(self,service):
        self.service=service;self.token=secrets.token_hex(32);self.cancelled=False
        self.requests=0;self.responses=0;self.failures=0;self.inflight=0;self.lock=threading.Lock();self.admission=threading.BoundedSemaphore(4)
        broker=self
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(180)
                admitted=False
                try:
                    raw=self.rfile.readline(MAX_WIRE+1)
                    if len(raw)>MAX_WIRE or not raw.endswith(b'\n'):raise ValueError('IPC_LIMIT')
                    message=strict(raw,limit=MAX_WIRE)
                    if set(message)!={'token','request'} or not hmac.compare_digest(message['token'],broker.token):raise PermissionError('IPC_CAPABILITY')
                    with broker.admission:
                        if broker.cancelled:raise PermissionError('IPC_CANCELLED')
                        with broker.lock:broker.requests+=1;broker.inflight+=1
                        admitted=True
                        value=asyncio.run(broker.service.extract(message['request']))
                        with broker.lock:broker.responses+=1
                    result={'status':'COMPLETED','result':value,'request_hash':digest(message['request'])}
                except Exception as exc:
                    with broker.lock:broker.failures+=1
                    result={'status':'FAILED','code':type(exc).__name__}
                finally:
                    if admitted:
                        with broker.lock:broker.inflight-=1
                encoded=canonical(result)+b'\n'
                if len(encoded)>MAX_WIRE:encoded=canonical({'status':'FAILED','code':'IPC_RESPONSE_LIMIT'})+b'\n'
                self.wfile.write(encoded)
        class Server(socketserver.ThreadingTCPServer):
            daemon_threads=True
            allow_reuse_address=False
        self.server=Server(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.05},daemon=True)
        self.thread.start()

    def connection(self):
        return {'revision':'FULL001_SEMANTIC_IPC_1','host':'127.0.0.1','port':self.server.server_address[1],
                'token':self.token,'service_id':self.service.service_id,'mode':self.service.mode,
                'binding_hash':digest(self.service.client.binding),'concurrency':4}

    def snapshot(self):
        with self.lock:return {'requests':self.requests,'responses':self.responses,'failures':self.failures,
          'inflight':self.inflight,'service_id':self.service.service_id,'mode':self.service.mode,
          'scope':'SEMANTIC_NODE_RPCS_NOT_PROVIDER_COUNT_OR_HTTP_REQUEST_TOTAL'}

    def close(self):
        self.cancelled=True;self.server.shutdown();self.server.server_close();self.thread.join(timeout=1)


class RemoteSemantic:
    def __init__(self,connection):
        if (connection.get('revision')!='FULL001_SEMANTIC_IPC_1' or connection.get('host')!='127.0.0.1' or
            type(connection.get('port')) is not int or not 1<=connection['port']<=65535 or connection.get('service_id') not in {'E0','E1'}):raise ValueError('IPC_BINDING')
        self.connection=connection;self.service_id=connection['service_id'];self.mode=connection['mode']

    async def extract(self,request):return await asyncio.to_thread(self._extract,request)

    def _extract(self,request):
        raw=canonical({'token':self.connection['token'],'request':request})+b'\n'
        if len(raw)>MAX_WIRE:raise ValueError('IPC_REQUEST_LIMIT')
        with socket.create_connection(('127.0.0.1',self.connection['port']),timeout=180) as stream:
            stream.sendall(raw)
            with stream.makefile('rb') as incoming:raw=incoming.readline(MAX_WIRE+1)
        if len(raw)>MAX_WIRE or not raw.endswith(b'\n'):raise ValueError('IPC_RESPONSE_LIMIT')
        value=strict(raw,limit=MAX_WIRE)
        if value.get('status')!='COMPLETED' or value.get('request_hash')!=digest(request):raise ValueError('SEMANTIC_RPC_FAILED')
        return value['result']
