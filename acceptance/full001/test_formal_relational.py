"""Independent builder tests on bounded fixtures, never formal host workloads."""
from collections import Counter
import json
from pathlib import Path
import unittest
from rcwg_full.data.formal_relational import definition,build_fixture,build_formal,build_request
from rcwg_full.data.conditions import check_group
from rcwg_full.runtime.catalog import DataCatalog
from rcwg_full.evidence import read,digest
from rcwg_full.verification.relational_oracle import f1_expected,f2_expected
from rcwg_full.verification.compare import check_output
from support import EvidenceDirectory


class FormalRelationalTests(unittest.TestCase):
    def setUp(self):self.evidence=EvidenceDirectory(self.id());self.root=Path(self.evidence.name)
    def tearDown(self):self.evidence.cleanup()

    def test_all_twenty_four_builders_four_conditions_sql_matches_independent_python(self):
        for family in ['F1','F2']:
            for number in range(1,13):
                template=f'{family}-{number:02d}';siblings={}
                for condition in ['C0','C1','C2','C3']:
                    with self.subTest(template=template,condition=condition):
                        directory=self.root/(template+condition);siblings[condition]=directory
                        result=build_fixture(template,0,condition,directory)
                        self.assertEqual(result['proof']['status'],'IR_VALIDATED',result['proof'])
                        catalog=DataCatalog(result['manifest_path']).bind(result['task'])
                        values={ident.removeprefix('dataset:'):source.table().to_pylist() for ident,source in catalog.sources.items()}
                        gold=json.loads(read(result['private_verifier']))
                        expected=(f1_expected if family=='F1' else f2_expected)(number,values)
                        self.assertEqual(check_output(gold['expected'],expected,{'comparison':gold['comparison']})['status'],'PASS')
                        self.assertFalse(result['build']['native_execution_performed']);self.assertFalse(result['build']['formal_frozen'])
                        self.assertEqual(result['build']['profile'],'formal_builder_fixture_v1')
                        self.assertTrue(all(s['builder_observations']['peak_batch_rows']<=31 for s in result['manifest']['sources']))
                self.assertEqual(check_group(siblings)['status'],'PASS',template)

    def test_single_axis_selectivity_skew_and_join_multiplicity_bounds(self):
        for template in ['F1-02','F1-10','F2-02','F2-10']:
            base=definition(template,1,'C0',fixture=True);changed=definition(template,1,'C1',fixture=True)
            field='join_key' if template=='F2-02' else 'eligible'
            source='dataset:records' if template.startswith('F1') else 'dataset:left'
            a=list(base['sources'][source]());b=list(changed['sources'][source]())
            self.assertEqual([{k:v for k,v in r.items() if k!=field} for r in a],[{k:v for k,v in r.items() if k!=field} for r in b])
            self.assertNotEqual([r[field] for r in a],[r[field] for r in b])
            for alias in ['dataset:right','dataset:third']:
                if alias in base['sources']:self.assertEqual(list(base['sources'][alias]()),list(changed['sources'][alias]()))
        for condition in ['C0','C1']:
            d=definition('F2-10',0,condition,fixture=True)
            for alias,key in [('dataset:right','join_key'),('dataset:third','entity_key')]:
                self.assertLessEqual(max(Counter(r[key] for r in d['sources'][alias]() if r[key] is not None).values()),4)

    def test_full_scale_metadata_only_and_formal_build_denied_before_any_write(self):
        full=definition('F1-01',0,'C1');self.assertEqual(full['data_parameters']['rows'],1000000)
        self.assertEqual(full['task']['datasets'][0]['stats']['row_count'],1000000)
        right=definition('F2-09',0,'C1');self.assertEqual(right['data_parameters'],{'left_rows':1000000,'right_rows':10000,'third_rows':1000})
        out=self.root/'must-not-exist';seen=[]
        with self.assertRaisesRegex(PermissionError,'HOST_ADMISSION_REQUIRED'):build_formal('F1-01',0,'C1',out)
        with self.assertRaisesRegex(PermissionError,'HOST_ADMISSION_REQUIRED'):build_formal('F1-01',0,'C1',out,host_admit=lambda request:seen.append(request))
        self.assertEqual(seen,[build_request('F1-01',0,'C1')]);self.assertFalse(out.exists())
        self.assertNotEqual(full['seed'],definition('F1-01',0,'C1',fixture=True)['seed'])
        self.assertEqual(full['seed'],definition('F1-01',0,'C0')['seed'])

    def test_row_count_and_schema_errors_leave_unsealed_evidence(self):
        from rcwg_full.data.stream_prepare import prepare_streams
        d=definition('F1-01',0,'C0',fixture=True)
        with self.assertRaisesRegex(ValueError,'BUILD_ROW_COUNT'):
            prepare_streams(d['task'],{'dataset:records':iter([])},self.root/'short',profile=d['profile'],provenance={})
        self.assertFalse((self.root/'short/data_manifest.json').exists())
        self.assertTrue(list((self.root/'short').glob('*.arrow')))
        row=next(d['sources']['dataset:records']());row['unregistered']=1
        with self.assertRaisesRegex(ValueError,'BUILD_ROW_FIELDS'):
            prepare_streams(d['task'],{'dataset:records':iter([row])},self.root/'extra',profile=d['profile'],provenance={})
        self.assertFalse((self.root/'extra/data_manifest.json').exists())
