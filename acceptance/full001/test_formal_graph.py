"""F3 persisted builders and SQL oracle differential checks, fixture scale only."""
from pathlib import Path
import copy,json,sqlite3
import unittest
from rcwg_full.evidence import read,canonical,digest
from rcwg_full.data.formal_graph import definition,build_fixture,build_formal,build_request
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.data.conditions import check_group
from rcwg_full.verification.compare import shortest_distances
from rcwg_full.verification.graph_oracle import f3_expected
from rcwg_full.verification.prepared import check_prepared
from rcwg_full.verification.graph_sql import connect
from support import EvidenceDirectory


class FormalGraphBuilders(unittest.TestCase):
    def setUp(self):self.tmp=EvidenceDirectory(self.id());self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_all_twelve_builders_sibling_invariants_and_independent_gold(self):
        for number in range(1,13):
            siblings={}
            for condition in ['C0','C1','C2','C3']:
                with self.subTest(template=number,condition=condition):
                    directory=self.root/f'{number}-{condition}';siblings[condition]=directory
                    result=build_fixture(f'F3-{number:02d}',1,condition,directory)
                    self.assertEqual(result['proof']['status'],'IR_VALIDATED',result['proof'])
                    catalog=DataCatalog(result['manifest_path']).bind(result['task']);values={}
                    for ident,source in catalog.sources.items():values[ident.removeprefix('dataset:')]=source.table().to_pylist() if source.entry['kind']=='table' else source.value()
                    recipe=json.loads(read(result['private_verifier']));context=recipe['context']
                    if number in {2,3,5,12}:
                        distances=shortest_distances(values['graph'],values['seeds'],'weight')
                        db=connect(recipe,result['private_verifier'])
                        try:
                            for ident,distance in db.execute('SELECT id,distance FROM best'):
                                expected=distances[canonical(ident)];self.assertEqual(float('inf') if distance is None else distance,expected)
                        finally:db.close()
                    else:
                        args={**context,**values,'graph':values['graph'],'selection':context['selection'],'queries':{'q0':[0,1],'q1':[2,3]}}
                        expected=f3_expected(args)
                        self.assertEqual(check_prepared(expected,result['private_verifier'])['status'],'PASS')
                        bad=copy.deepcopy(expected)
                        if isinstance(bad,list):bad.append(999999)
                        elif 'graph' in bad:bad['graph']['revision']='wrong'
                        else:bad['q0'].append({'edge_id':999999})
                        self.assertEqual(check_prepared(bad,result['private_verifier'])['status'],'FAIL')
                    self.assertFalse(result['build']['formal_frozen']);self.assertFalse(result['build']['native_execution_performed'])
            self.assertEqual(check_group(siblings)['status'],'PASS',number)
    def test_exact_formal_metadata_and_admission_before_creation(self):
        dense=definition('F3-11',0,'C1')
        self.assertEqual(dense['data_parameters'],{'nodes':100000,'edges_upper':(100000*99999+127)//128})
        self.assertEqual(dense['sources']['dataset:graph']['edges'].count,dense['data_parameters']['edges_upper'])
        target=self.root/'not-created';seen=[]
        with self.assertRaisesRegex(PermissionError,'HOST_ADMISSION_REQUIRED'):build_formal('F3-11',0,'C1',target,host_admit=lambda r:seen.append(r))
        self.assertEqual(seen,[build_request('F3-11',0,'C1')]);self.assertFalse(target.exists())
    def test_modified_oracle_is_facility_integrity_failure(self):
        result=build_fixture('F3-01',0,'C0',self.root/'one');recipe=json.loads(read(result['private_verifier']))
        path=result['private_directory']/recipe['oracle_file']
        with path.open('ab') as file:file.write(b'changed')
        with self.assertRaisesRegex(ValueError,'ORACLE_HASH'):check_prepared([],result['private_verifier'])
