"""Read pinned source ASTs to verify native adapter call signatures offline."""
import ast
from pathlib import Path
from rcwg_full.evidence import read,sha
from .native_external import registry

CALLS={
 'TPS-Bench':[('eval/gemini-tool-selection.py','generate_with_gemini_eval',None,4,[])],
 'WorFEval':[('evaluator/graph_evaluator.py',name,None,3,[]) for name in ['t_eval_graph','t_eval_nodes','t_eval_plan']],
 'SemBench':[('src/scenario/movie/runner/lotus_runner/lotus_runner.py','__init__','LotusRunner',1,['use_case','scale_factor','model_name','concurrent_llm_worker']),
             ('src/runner/generic_runner.py','execute_queries','GenericRunner',2,[])],
 'LOTUS':[('lotus/sem_ops/'+name+'.py','__call__',None,1,arguments) for name,arguments in [
     ('sem_filter',['user_instruction']),('sem_extract',['input_cols','output_cols','extract_quotes']),
     ('sem_topk',['user_instruction','K','method']),('sem_join',['other','join_instruction'])]],
 'DocETL':[('docetl/runner.py','__init__','DSLRunner',2,['max_threads']),
           ('docetl/runner.py','load','DSLRunner',1,[]),('docetl/runner.py','run','DSLRunner',1,[])]}


def inspect_contract(track,source_root):
    entry=registry()['tracks'][track];root=Path(source_root);checks=[]
    for path,expected in entry['files'].items():
        if sha(read(root/path))!=expected:raise ValueError('PINNED_UPSTREAM_SOURCE_MISMATCH:'+path)
    for path,name,owner,positional,keywords in CALLS[track]:
        tree=ast.parse(read(root/path));scope=tree
        if owner:
            scope=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==owner)
        matches=[n for n in ast.walk(scope) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
        if len(matches)!=1:raise ValueError('NATIVE_CALLABLE_AMBIGUOUS:'+name)
        args=matches[0].args;position_names=[p.arg for p in args.posonlyargs+args.args]
        allowed=[p.arg for p in args.args+args.kwonlyargs]
        if positional>len(position_names) and args.vararg is None:raise ValueError('NATIVE_POSITIONAL_ARGUMENTS:'+name)
        if set(keywords)-set(allowed) and args.kwarg is None:raise ValueError('NATIVE_KEYWORD_ARGUMENTS:'+name)
        if set(keywords)&set(position_names[:positional]):raise ValueError('NATIVE_DUPLICATE_ARGUMENT:'+name)
        supplied=set(position_names[:positional])|set(keywords)
        required=set(position_names[:len(position_names)-len(args.defaults)])|{a.arg for a,d in zip(args.kwonlyargs,args.kw_defaults) if d is None}
        if required-supplied:raise ValueError('NATIVE_REQUIRED_ARGUMENT:'+name)
        checks.append({'path':path,'callable':name,'owner':owner,'positional_count':positional,'keywords':keywords,'status':'PASS'})
    return {'track':track,'revision':entry['revision'],'source_hashes':entry['files'],'calls':checks,'status':'PASS',
        'scope':'PINNED_NATIVE_API_SIGNATURES_ONLY','upstream_execution_performed':False,'formal_ready':False}
