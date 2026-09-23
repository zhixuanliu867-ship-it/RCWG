"""Derive coverage from actual exact-commit outcomes and hashed artifacts.

No declaration in a progress file can turn a missing test or journal into PASS.
"""
import json,re
from pathlib import Path
from rcwg_full.evidence import ROOT,read,sha,digest,source_hashes
from rcwg_full.acceptance_identity import git_identity,file_hash,file_manifest
from rcwg_full.runtime.events import verify_journal


def require(value,code):
    if not value:raise ValueError(code)


def validate_results(directory,build,*,exact=True):
    directory=Path(directory);build=Path(build);report=json.loads(read(directory/'TEST_RESULTS.json'))
    require(report['status']=='PASS' and report['exit_code']==0,'TEST_REPORT_NOT_PASS')
    tests={t['test_id']:t['status'] for t in report['tests']}
    require(len(tests)==report['tests_run']==len(report['tests']) and set(tests.values())=={'PASS'},'TEST_OUTCOMES')
    expected=json.loads(read(directory/'EXPECTED_TESTS.json'))
    require(set(expected['test_ids'])==set(tests),'TEST_DISCOVERY_MISMATCH')
    require(all(t['status']=='PASS' for t in report['subtests']),'SUBTEST_FAILURE')
    require(report['dependencies']['python']=='3.12.14' and report['dependencies']['system']=='Linux' and
        report['dependencies']['packages']=={'pyarrow':'21.0.0','pybind11':'3.0.1'},'TARGET_ENVIRONMENT')
    require(report['dependencies']['lock_sha256']==file_hash(ROOT/'environments/full001/requirements.lock'),'DEPENDENCY_LOCK')
    binary=json.loads(read(build/'BUILD.json'));require(binary['status']=='BUILD_PASS','NATIVE_BUILD_NOT_PASS')
    require(report['native_build']['manifest_sha256']==file_hash(build/'BUILD.json') and report['native_build']['manifest']==binary,'NATIVE_MANIFEST_MISMATCH')
    require(binary['source']==report['source']==expected['source']==source_hashes(),'ACCEPTANCE_SOURCE_MISMATCH')
    for entry in binary['binaries'].values():require(file_hash(build/entry['name'])==entry['sha256'],'NATIVE_BINARY_MISMATCH')
    if exact:
        current=git_identity()
        for identity in [current,report['git_identity'],binary['git_identity']]:
            require(identity['head']==current['head'] and identity['tree']==current['tree'] and identity['baseline_is_ancestor'] and
                identity['tracked_content_clean'] and not identity['untracked_source_files'],'EXACT_COMMIT_IDENTITY')
    files=file_manifest(directory);files.pop('TEST_RESULTS.json')
    require(files==report['artifact_files'],'ARTIFACT_CLOSURE_CHANGED')
    frozen=json.loads(read(ROOT/'specs/full001/retained_tests_r1.json'))
    require(set(frozen['test_ids'])<=set(tests),'RETAINED_TEST_ID_MISSING')
    protected=json.loads(read(ROOT/'docs/full001/INHERITED_FILE_HASHES.json'))
    require(all(file_hash(ROOT/p)==h for p,h in protected.items()),'PROTECTED_SOURCE_CHANGED')
    return report,tests,files,{'retained_test_count':len(frozen['test_ids']),'protected_files':len(protected),
        'report_sha256':file_hash(directory/'TEST_RESULTS.json'),'build_sha256':file_hash(build/'BUILD.json'),
        'source_sha256':digest(report['source']),'artifact_closure_sha256':digest(files),'git_identity':report['git_identity']}


def actual_dispatches(directory,tests,files,required=None):
    directory=Path(directory)
    if required is None:
        registry=json.loads(read(ROOT/'specs/full001/operators.json'))
        required={r['operator_id']+':'+i for r in registry['operators'] for i in r['implementations']}
    witnesses={};excluded=[]
    paths=[p for p in files if p.endswith('/events.jsonl') and p.startswith('evidence/')]
    def priority(p):
        ident=p.split('/')[1]
        return (0 if ident.startswith('test_dispatch_completion.') else 1 if ident.startswith('test_templates_') else 2,p)
    for relative in sorted(paths,key=priority):
        case=directory/Path(relative).parts[0]/Path(relative).parts[1]
        ident=(case/'TEST_ID.txt').read_text('utf8').strip() if (case/'TEST_ID.txt').exists() else case.name
        if tests.get(ident)!='PASS':continue
        try:events=verify_journal(directory/relative,expected_sha256=files[relative]['sha256'])
        except (ValueError,KeyError):excluded.append(relative);continue  # Deliberately corrupt negative fixtures remain evidence, never coverage.
        for event in events:
            if event['event_kind']!='node_finished' or event['status']!='COMPLETED':continue
            payload=event['payload'];branch=payload['operator']+':'+payload['implementation']
            if branch in required and branch not in witnesses:
                witnesses[branch]={'test_id':ident,'journal':relative,'journal_sha256':files[relative]['sha256'],
                    'node_instance':event['node_instance'],'event_hash':event['event_hash'],'event_id':event['event_id']}
        if set(witnesses)==required:break
    require(set(witnesses)==required,'DISPATCH_EVIDENCE_MISSING:'+','.join(sorted(required-set(witnesses))))
    return {'count':len(witnesses),'witnesses':witnesses,'excluded_invalid_negative_journals':excluded}


def fixture_closures(directory,tests,files):
    directory=Path(directory);tiny={};mutations={};equivalences={}
    for family in range(1,7):
        for template in range(1,13):
            for base in range(5):
                for condition in range(4):
                    ident=f'test_templates_f{family}.F{family}Templates.test_F{family}_{template:02d}_b{base}_C{condition}'
                    require(tests.get(ident)=='PASS','TINY_TEST_MISSING:'+ident)
                    prefix='evidence/'+ident+'/'
                    actual=prefix+('execution/' if family>=5 else '')+'actual.json'
                    verification=prefix+('execution/verification.json' if family>=5 else 'independent-verification.json')
                    require(actual in files and verification in files,'TINY_ARTIFACT_MISSING:'+ident)
                    require(json.loads(read(directory/verification))['status']=='PASS','TINY_VERIFICATION_FAILED')
                    tiny[ident]={'actual':actual,'verification':verification,'actual_sha256':files[actual]['sha256'],
                                 'verification_sha256':files[verification]['sha256']}
    for ident in tests:
        target=mutations if ident.startswith('test_verification.Mutations.test_') else equivalences if ident.startswith('test_verification.Equivalences.test_') else None
        if target is None:continue
        path='evidence/'+ident+'/CASE_RESULT.json';inputs='evidence/'+ident+'/CASE_INPUTS.json'
        require(path in files and inputs in files,'VERIFIER_CASE_EVIDENCE_MISSING')
        result=json.loads(read(directory/path));require(result['status']=='PASS' and result['actual_accept']==result['expected_accept'],'VERIFIER_CASE_FAILED')
        target[ident]={'result_sha256':files[path]['sha256'],'input_sha256':files[inputs]['sha256']}
    require(len(mutations)>=100 and len(equivalences)>=100,'VERIFIER_CASE_COUNT')
    return {'tiny':tiny,'mutations':mutations,'equivalences':equivalences}


def resolve_requirements(tests,identity,coverage,fixtures):
    definitions=json.loads(read(ROOT/'specs/full001/requirement_tests_r1.json'));requirements=[]
    registry=json.loads(read(ROOT/'specs/full001/requirements.json'))['requirements']
    for row in registry:
        ident=row['requirement_id']
        if ident.startswith('EXT-'):
            requirements.append({**row,'status':'PENDING_EXTERNAL_EVIDENCE','actual_evidence':[]});continue
        selectors=definitions[ident]['test_selectors'];selected=set()
        for selector in selectors:
            matched={t for t in tests if re.search(selector,t)}
            require(matched,'REQUIREMENT_TEST_SELECTOR_EMPTY:'+ident+':'+selector);selected|=matched
        requirements.append({**row,'status':'SOFTWARE_TESTS_PASS_PENDING_DELIVERY' if ident.startswith('M00-') else 'PASS',
            'actual_evidence':[{'test_ids':sorted(selected),'report_sha256':identity['report_sha256'],
                'source_sha256':identity['source_sha256'],'artifact_closure_sha256':identity['artifact_closure_sha256'],
                'environment_id':'Linux-Python-3.12.14-locked-Arrow21-pybind3.0.1',
                'exit_code':0,'coverage_checks':definitions[ident].get('coverage_checks',[])}]})
    require(set(definitions)=={r['requirement_id'] for r in registry if not r['requirement_id'].startswith('EXT-')},'REQUIREMENT_MAP_SET')
    return requirements


def build_evidence(directory,build,*,exact=True):
    report,tests,files,identity=validate_results(directory,build,exact=exact)
    coverage=actual_dispatches(directory,tests,files);fixtures=fixture_closures(directory,tests,files)
    requirements=resolve_requirements(tests,identity,coverage,fixtures)
    for r in requirements:
        for e in r['actual_evidence']:e['command']=report['command']
    return {'revision':'FULL001_SOFTWARE_EVIDENCE_R1','status':'SOFTWARE_TEST_EVIDENCE_PASS',
        'identity':identity,'dispatches':coverage,'fixture_closures':fixtures,'requirements':requirements,
        'tests_run':report['tests_run'],'source':report['source'],'formal_ready':False,
        'remaining_acceptance':'inherited gates, clean application and delivery package must also bind this exact commit'}
