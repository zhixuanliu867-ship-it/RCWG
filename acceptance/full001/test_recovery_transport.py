"""BOOT_ONLY staged HTTP faults; assertions use captured bytes, never the network."""
from types import SimpleNamespace
from unittest.mock import patch
import http.client, io, json, unittest
from rcwg_full.services.transport import ExistingVertexTransport
from rcwg_full.services.transport_evidence import EvidenceHTTPSConnection,TransportFailure
import test_auto2, test_auto2_services


TOKEN='fixture-private-credential-must-not-enter-evidence'


class Stream:
    def __init__(self, chunks, headers=None):
        self.chunks=list(chunks);self.code=200
        self.headers=headers or {'x-request-id':'provider-123','Authorization':'Bearer '+TOKEN}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):
        chunk=self.chunks.pop(0) if self.chunks else b''
        if isinstance(chunk,Exception):raise chunk
        assert len(chunk)<=limit
        return chunk


def transport(open_action,token_source=lambda:TOKEN):
    t=ExistingVertexTransport.__new__(ExistingVertexTransport)
    t.binding={'endpoint':'https://fixture.invalid/model'}
    t.existing=SimpleNamespace(token_source=token_source,dispatch_count=0,
        config={'project_id':'fixture-project','request_timeout_s':90,'max_response_bytes':1048576},
        opener=SimpleNamespace(open=open_action))
    return t


class RecoveryTransport(unittest.TestCase):
    def exercise_failure(self, t, sent, phase):
        events=[]
        with self.assertRaises(TransportFailure) as caught:
            t.send_with_evidence('G',b'{}','local-id',reservation=1,evidence_sink=lambda r,p:events.append((r,p)))
        self.assertIs(caught.exception.transport_evidence['sent'],sent)
        self.assertEqual(caught.exception.transport_evidence['phase'],phase)
        self.assertNotIn(TOKEN,json.dumps([r for r,p in events]))
        self.assertNotIn(TOKEN,b''.join(p or b'' for r,p in events).decode(errors='replace'))
        return caught.exception.transport_evidence,events

    def test_credentials_failure_is_confirmed_not_dispatched(self):
        def credential():raise OSError(13,TOKEN)
        t=transport(lambda *a,**k:self.fail('unexpected HTTP'),credential)
        proof,_=self.exercise_failure(t,False,'CREDENTIALS')
        self.assertEqual(proof['errno'],13);self.assertEqual(t.existing.dispatch_count,0)

    def test_real_connection_hook_distinguishes_connect_failure(self):
        def opening(request,**kw):
            c=EvidenceHTTPSConnection('fixture.invalid',observer=request._rcwg_transport_observer)
            with patch.object(http.client.HTTPSConnection,'connect',side_effect=ConnectionRefusedError(111,TOKEN)):
                c.send(b'POST fixture')
        proof,_=self.exercise_failure(transport(opening),False,'CONNECTING')
        self.assertEqual(proof['errno'],111)

    def test_write_failure_is_unknown_even_if_socket_reports_zero(self):
        def opening(request,**kw):
            c=EvidenceHTTPSConnection('fixture.invalid',observer=request._rcwg_transport_observer)
            def sendall(data):raise BrokenPipeError(32,TOKEN)
            c.sock=SimpleNamespace(sendall=sendall)
            c.send(b'POST fixture')
        self.exercise_failure(transport(opening),None,'REQUEST_WRITE')

    def test_wait_response_failure_is_unknown(self):
        def opening(request,**kw):
            c=EvidenceHTTPSConnection('fixture.invalid',observer=request._rcwg_transport_observer)
            with patch.object(http.client.HTTPSConnection,'getresponse',side_effect=TimeoutError(TOKEN)):
                c.getresponse()
        self.exercise_failure(transport(opening),None,'WAIT_RESPONSE')

    def test_uninstrumented_opener_failure_does_not_claim_zero_bytes(self):
        def opening(*a,**kw):raise ConnectionRefusedError(111,TOKEN)
        self.exercise_failure(transport(opening),None,'OPEN_SEND_OR_WAIT')

    def test_headers_and_partial_body_survive_read_failure(self):
        stream=Stream([b'{"partial":',OSError(104,TOKEN)])
        proof,events=self.exercise_failure(transport(lambda *a,**kw:stream),True,'RESPONSE_BODY')
        self.assertEqual(proof['http_status'],200);self.assertFalse(proof['response_complete'])
        self.assertEqual(proof['received_bytes'],11)
        self.assertEqual(proof['response_headers'],{'x-request-id':'provider-123'})
        header_index=next(i for i,(r,p) in enumerate(events) if r['event']=='RESPONSE_HEADERS')
        prefix_index=next(i for i,(r,p) in enumerate(events) if p is not None)
        self.assertLess(header_index,prefix_index)

    def test_incomplete_read_exception_preserves_its_received_prefix(self):
        proof,events=self.exercise_failure(transport(lambda *a,**kw:Stream([http.client.IncompleteRead(b'abc',7)])),True,'RESPONSE_BODY')
        self.assertEqual(proof['received_bytes'],3)
        self.assertIn(b'abc',[p for r,p in events])

    def test_premature_eof_with_content_length_is_not_complete(self):
        stream=Stream([b'{}'],{'content-length':'20'})
        proof,_=self.exercise_failure(transport(lambda *a,**kw:stream),True,'RESPONSE_BODY')
        self.assertFalse(proof['response_complete'])

    def test_partial_stream_cannot_extend_the_total_http_deadline(self):
        stream=Stream([b'partial',b'never-read'])
        with patch('rcwg_full.services.transport.time.monotonic',side_effect=[0,1,91]):
            proof,_=self.exercise_failure(transport(lambda *a,**kw:stream),True,'RESPONSE_BODY')
        self.assertEqual(proof['received_bytes'],7)
        self.assertFalse(proof['response_complete']);self.assertEqual(stream.chunks,[b'never-read'])

    def test_prefix_is_bounded_and_credentials_are_redacted(self):
        chunks=[b'x'*16384]*5+[TOKEN.encode(),OSError(104,TOKEN)]
        proof,events=self.exercise_failure(transport(lambda *a,**kw:Stream(chunks)),True,'RESPONSE_BODY')
        self.assertTrue(all(len(p)<=65536 for r,p in events if p is not None))
        self.assertEqual(proof['received_bytes'],81920+len(TOKEN))
        _,early=self.exercise_failure(transport(lambda *a,**kw:Stream([TOKEN.encode(),OSError(104,TOKEN)])),True,'RESPONSE_BODY')
        self.assertTrue(any(r['credential_echo_redacted'] for r,p in early))

    def test_complete_response_records_distinct_provider_identity_and_usage(self):
        body=b'{"responseId":"provider-id","modelVersion":"model-r1","usageMetadata":{"totalTokenCount":17}}'
        events=[];t=transport(lambda *a,**kw:Stream([body],{'content-length':str(len(body))}))
        response=t.send_with_evidence('G',b'{}','local-id',reservation=1,evidence_sink=lambda r,p:events.append(r))
        self.assertEqual(response.body,body)
        final=events[-1];self.assertTrue(final['response_complete'])
        self.assertEqual((final['local_request_id'],final['provider_response_id']),('local-id','provider-id'))
        self.assertEqual(final['usage'],{'totalTokenCount':17})


class RecoveryClientTransport(unittest.TestCase):
    setUp=test_auto2.Auto2Control.setUp
    client=test_auto2_services.Auto2Services.client
    request=test_auto2_services.Auto2Services.request

    def test_partial_json_is_persisted_but_never_passed_to_parser(self):
        client,_=self.client([])
        client.transport=transport(lambda *a,**kw:Stream([b'{"modelVersion":"r1"',OSError(104,TOKEN)]))
        request=self.request(client)
        with patch('rcwg_full.services.client.parse_count',side_effect=AssertionError('partial parsed')):
            result=client.call(request,'COUNT')
        self.assertEqual(result['status'],'INFRA_FAILURE');self.assertIs(result['sent'],True)
        self.assertFalse(result['response_complete']);self.assertEqual(result['http_status'],200)
        self.assertFalse((client.index.root/request['request_id']/'response.raw').exists())
        self.assertTrue(list((client.index.root/request['request_id']).glob('transport-*.prefix')))

    def test_pre_dispatch_failure_keeps_reservation_and_distinct_send_fact(self):
        client,_=self.client([])
        def credential():raise OSError(13,TOKEN)
        client.transport=transport(lambda *a,**kw:self.fail('HTTP'),credential)
        result=client.call(self.request(client),'COUNT')
        self.assertEqual(result['status'],'INFRA_FAILURE');self.assertIs(result['sent'],False)
        self.assertEqual(len(self.state.summary()['reservations']),2)
