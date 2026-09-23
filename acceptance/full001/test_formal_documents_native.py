"""Bound upstream-shaped text through actual supervisor, native worker and gold.

Service replies are explicitly hand-authored ENGINEERING_REPLAY, not live E0.
"""
import json,os,unittest
from pathlib import Path
from test_formal_documents import fixture
from rcwg_full.data.formal_documents import bind_candidate
from rcwg_full.runtime.documents import Documents
from rcwg_full.runtime.supervisor import execute
from rcwg_full.verification.prepared import check_prepared
from rcwg_full.evidence import digest,write,read
from support import EvidenceDirectory


class BoundDocumentNative(unittest.TestCase):
    def test_f5_and_f6_bound_sources_reach_independent_semantic_verification(self):
        tmp=EvidenceDirectory(self.id());self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        for template in ['F5-01','F6-01']:
            with self.subTest(template=template):
                bundle,design,expected=fixture(template)
                bound=bind_candidate(bundle,design,expected,root/template,reviewers=['fixture-a','fixture-b'],profile='engineering_tiny_v1')
                docs=bundle['public']['documents'];adapter=Documents(docs);rows=expected['stages']['extract']
                ids=list(dict.fromkeys(r['paper_id'] for r in rows))
                read_node=next(n for n in bound['plan']['nodes'] if n['operator']=='read_documents')
                contexts=[adapter.selected_context(c) for c in adapter.read_documents(ids,['canonical_text'],read_node['params']['batch_size'],'batched','fixture-recording')]
                node=next(n for n in bound['plan']['nodes'] if n['operator']=='semantic_extract')
                request={'service_id':'engineering-replay-e0','question':node['params']['question'],
                    'field_schema':node['params']['field_schema'],'contexts':contexts}
                replay=root/(template+'-replay.json');write(replay,{'revision':'full001-engineering-replay-1','service_id':'engineering-replay-e0','responses':{digest(request):rows}})
                out=root/(template+'-run')
                result=execute(bound['task'],bound['plan'],bound['manifest_path'],build=os.environ['RCWG_FULL_BUILD'],
                    output=out,mode='ENGINEERING_REPLAY',semantic_replay=replay,
                    verify=lambda actual,_:check_prepared(actual,bound['private_verifier']))
                self.assertEqual(result['terminal_status'],'COMPLETED',result.get('failure'))
                self.assertEqual(result['verification']['status'],'PASS',result.get('verification'))
                self.assertEqual(result['paid_calls'],0);self.assertFalse(result['formal_ready'])
                wire=json.loads(read(out/'request.json'));self.assertNotIn('private_verifier',wire)
