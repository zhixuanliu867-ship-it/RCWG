"""BOOT_ONLY controlled clocks and processes; never an inference probe."""
import http.client,json,socket,time,unittest
from types import SimpleNamespace
from unittest.mock import patch
from rcwg_full.services.timeout3 import PROFILE,Deadline
from rcwg_full.services.transport_evidence import EvidenceHTTPSConnection,TransportFailure
from rcwg_full.auto2.watchdog import run_process,reconcile_exit
from rcwg_full.auto2.dispatch import DispatchGate
from rcwg_full.evidence import digest
import test_recovery_transport as fixtures
import test_auto2_services

def sleeping_child():time.sleep(60)

class Clock:
    now=0
    def __call__(self):return self.now

class Timeout3(unittest.TestCase):
    def test_delayed_first_byte_120_old_fails_new_accepts(self):
        for modern in [False,True]:
            c=Clock();events=[]
            def opening(request,timeout):
                c.now=120
                if modern:
                    self.assertEqual(timeout,20);self.assertEqual(request._rcwg_deadline.end,600)
                    request._rcwg_deadline.remaining()
                elif timeout<120:raise TimeoutError('BOOT_ONLY')
                return fixtures.Stream([b'{}'])
            t=fixtures.transport(opening)
            if modern:t.existing.config['timeout_profile']=PROFILE
            with patch('time.monotonic',c),patch.object(Deadline,'start'):
                if modern:self.assertEqual(t.send('G',b'{}','id',reservation=1).body,b'{}')
                else:
                    with self.assertRaises(TransportFailure):t.send('G',b'{}','id',reservation=1)
    def test_connect_twenty_then_wait_uses_remaining_total(self):
        c=Clock();d=Deadline(600,clock=c);sock=SimpleNamespace(settimeout=lambda t:values.append(t));values=[]
        conn=EvidenceHTTPSConnection('fixture.invalid',deadline=d,connect_timeout=20)
        def connect(_):self.assertEqual(conn.timeout,20);c.now=12;conn.sock=sock
        with patch.object(http.client.HTTPSConnection,'connect',connect):conn.connect()
        self.assertEqual(values,[588])
        c.now=30
        with patch.object(http.client.HTTPSConnection,'getresponse',return_value=None):conn.getresponse()
        self.assertEqual(values[-1],570)
    def test_connect_timeout_is_unsent_and_write_timeout_uncertain(self):
        for phase,sent in [('CONNECTING',False),('REQUEST_WRITE',None)]:
            def opening(request,**kw):
                conn=EvidenceHTTPSConnection('fixture.invalid',observer=request._rcwg_transport_observer,deadline=request._rcwg_deadline,connect_timeout=20)
                if phase=='CONNECTING':
                    with patch.object(http.client.HTTPSConnection,'connect',side_effect=TimeoutError()):conn.send(b'POST')
                else:
                    conn.sock=SimpleNamespace(settimeout=lambda t:None,sendall=lambda b:(_ for _ in ()).throw(TimeoutError()))
                    conn.send(b'POST')
            t=fixtures.transport(opening);t.existing.config['timeout_profile']=PROFILE
            with self.assertRaises(TransportFailure) as caught:t.send('G',b'{}','id',reservation=1)
            self.assertIs(caught.exception.transport_evidence['sent'],sent)
    def test_slow_chunks_share_absolute_deadline(self):
        c=Clock()
        class Slow(fixtures.Stream):
            def read1(self,n):c.now+=250;return self.read(n)
        stream=Slow([b'{',b'"x":',b'1}'])
        t=fixtures.transport(lambda *a,**kw:stream);t.existing.config['timeout_profile']=PROFILE
        with patch('time.monotonic',c),patch.object(Deadline,'start'),self.assertRaises(TransportFailure) as caught:t.send('G',b'{}','id',reservation=1)
        self.assertFalse(caught.exception.transport_evidence['response_complete'])
        self.assertEqual(caught.exception.transport_evidence['received_bytes'],7)
        self.assertEqual(c.now,750)
    def test_late_headers_archived_but_never_accepted_as_complete(self):
        c=Clock();events=[]
        def opening(request,**kw):c.now=601;return fixtures.Stream([b'{}'])
        t=fixtures.transport(opening);t.existing.config['timeout_profile']=PROFILE
        with patch('time.monotonic',c),patch.object(Deadline,'start'),self.assertRaises(TransportFailure) as caught:
            t.send_with_evidence('G',b'{}','id',reservation=1,evidence_sink=lambda r,p:events.append(r))
        self.assertEqual(caught.exception.transport_evidence['http_status'],200)
        self.assertIs(caught.exception.transport_evidence['sent'],True)
        self.assertFalse(caught.exception.transport_evidence['response_complete'])
        self.assertTrue(any(e['event']=='RESPONSE_HEADERS' for e in events))
    def test_count_keeps_ninety_and_e_not_admitted(self):
        def opening(request,**kw):self.assertAlmostEqual(request._rcwg_deadline.remaining(),90,delta=1);return fixtures.Stream([b'{}'])
        t=fixtures.transport(opening);t.existing.config['timeout_profile']=PROFILE
        t.send('COUNT',b'{}','id',reservation=1)
        with self.assertRaises(TransportFailure):t.send('E',b'{}','id2',reservation=1)
        self.assertEqual(t.existing.dispatch_count,1)
    def test_truncated_or_invalid_length_never_complete(self):
        for length in ['20','nonsense','-1']:
            t=fixtures.transport(lambda *a,**kw:fixtures.Stream([b'{'],{'content-length':length}));t.existing.config['timeout_profile']=PROFILE
            with self.assertRaises(TransportFailure) as caught:t.send('G',b'{}','id',reservation=1)
            self.assertFalse(caught.exception.transport_evidence['response_complete'])
    def test_timer_interrupts_socket_stall(self):
        a,b=socket.socketpair();self.addCleanup(a.close);self.addCleanup(b.close)
        d=Deadline(.05);d.bind(a);d.start()
        try:
            try:chunk=a.recv(10)
            except (TimeoutError,OSError):chunk=b''
            self.assertEqual(chunk,b'')
            with self.assertRaises(TimeoutError):d.remaining()
        finally:d.close()
    def test_independent_process_is_stopped(self):
        result=run_process(sleeping_child,(),.25)
        self.assertTrue(result['timed_out']);self.assertTrue(result['child_stopped'])
        self.assertLess(result['elapsed_seconds'],10)

class WatchdogPersistence(unittest.TestCase):
    setUp=fixtures.RecoveryClientTransport.setUp
    client=fixtures.RecoveryClientTransport.client
    request=fixtures.RecoveryClientTransport.request
    def test_outer_stop_preserves_pending_and_restart_cannot_send(self):
        client,_=self.client([]);request=self.request(client);rid=request['request_id']
        payload={**request,'mode':'LIVE','kind':'COUNT','input_measurement':None}
        with DispatchGate(self.state).locked() as gate:
            gate.admit(rid,'COUNT',body_hash=request['body_hash'],scope_hash=client.scope_hash)
            client.index.begin(rid,payload);client.budget.reserve(rid,'COUNT')
        proof={'child_stopped':True,'timed_out':True}
        got=reconcile_exit(self.state,client.index,rid,proof)
        self.assertEqual(got['status'],'SENT_UNCONFIRMED')
        with patch.object(client.transport,'send',side_effect=AssertionError('resend')):
            self.assertEqual(client.call(request,'COUNT'),got)
        with self.state.db() as db:self.assertEqual(db.execute('SELECT status FROM dispatch_control').fetchone()[0],'FUSED')
