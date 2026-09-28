"""Independent Python oracles exercise compiled algorithms, not registry names."""
from collections import Counter
from fractions import Fraction
import os
import random
import tempfile
import unittest
from rcwg_full.runtime.native import Native


def literal(v):return {'literal':v}
def expr(op,a,b):return {'op':op,'left':a,'right':b}


class NativeKernels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pyarrow as pa
        cls.pa=pa
        build=os.environ.get('RCWG_FULL_BUILD')
        if not build:raise RuntimeError('NATIVE_BUILD_REQUIRED: explicitly set RCWG_FULL_BUILD')
        cls.perf=Native(build);cls.diag=Native(build,'diagnostic')

    def table(self,rows):return self.pa.Table.from_pylist(rows)

    def test_filter_actual_algorithms_nulls_and_short_circuit(self):
        rows=[{'id':i,'v':None if i%11==0 else i%17} for i in range(2063)]
        p=expr('gt',{'field':'v'},literal(7));expected=[x for x in rows if x['v'] is not None and x['v']>7]
        for impl in ['scalar','vectorized']:
            out,c=self.diag.relational('filter',impl,self.table(rows),{'predicate':p})
            self.assertEqual(out.to_pylist(),expected);self.assertEqual(c['predicate_evaluations'],len(rows))
            self.assertEqual(c.get('vector_batches',0),3 if impl=='vectorized' else 0)
        dangerous=expr('div',literal(1),literal(0))
        self.assertFalse(self.perf.expression({'op':'and','args':[literal(False),dangerous]},{}))
        self.assertTrue(self.perf.expression({'op':'or','args':[literal(True),dangerous]},{}))
        self.assertIsNone(self.perf.expression({'op':'and','args':[literal(True),literal(None)]},{}))

    def test_topk_grouped_ties_k0_and_heap_counters(self):
        rows=[{'id':i,'g':i%3,'score':(i*31)%19} for i in range(73)]
        for k in [0,1,9,100]:
            expected=[r for g in range(3) for r in sorted([r for r in rows if r['g']==g],key=lambda r:-r['score'])[:k]]
            for impl in ['full_sort','streaming_heap']:
                out,c=self.diag.relational('top_k',impl,self.table(rows),{'partition_by':['g'],'k':k,'keys':[{'field':'score','direction':'desc'}]})
                self.assertEqual(out.to_pylist(),expected)
                if impl=='streaming_heap' and k:self.assertGreater(c['heap_pushes'],0)
        _,counts=self.perf.relational('top_k','streaming_heap',self.table(rows),{'k':3,'keys':[{'field':'score','direction':'desc'}]})
        self.assertEqual(counts,{})

    def test_dedup_first_last_actual_source_ordinal(self):
        rows=[{'id':i,'v':None if i%5==0 else i%3} for i in range(21)]
        for keep in ['first','last']:
            chosen={}
            for r in rows:
                if keep=='last' or r['v'] not in chosen:chosen[r['v']]=r
            expected=sorted(chosen.values(),key=lambda r:r['id'])
            for impl in ['hash','sort_unique']:
                out,c=self.diag.relational('deduplicate',impl,self.table(rows),{'keys':['v'],'keep':keep})
                self.assertEqual(out.to_pylist(),expected)
                self.assertGreater(c['hash_probes' if impl=='hash' else 'key_comparisons'],0)

    def test_join_all_modes_build_sides_nulls_and_duplicate_multiplicity(self):
        left=[{'id':i,'k':k} for i,k in enumerate([1,1,2,None,5])]
        right=[{'rid':i,'k':k} for i,k in enumerate([1,1,3,None])]
        matches=[(l,r) for l in left for r in right if l['k'] is not None and l['k']==r['k']]
        ml={l['id'] for l,r in matches};mr={r['rid'] for l,r in matches}
        for mode in ['inner','left','right','full','semi','anti']:
            if mode in ['semi','anti']:expected=[l for l in left if (l['id'] in ml)==(mode=='semi')]
            else:
                pairs=list(matches)
                if mode in ['left','full']:pairs.extend((l,{'rid':None,'k':None}) for l in left if l['id'] not in ml)
                if mode in ['right','full']:pairs.extend(({'id':None,'k':None},r) for r in right if r['rid'] not in mr)
                expected=[{**{('left.'+k if k=='k' else k):v for k,v in l.items()},**{('right.'+k if k=='k' else k):v for k,v in r.items()}} for l,r in pairs]
            for impl,side in [('hash','left'),('hash','right'),('sort_merge','left'),('block_nested','left')]:
                out,c=self.diag.relational('join',impl,self.table(left),{'keys':[{'left':'k','right':'k'}],'join_type':mode,'build_side':side},self.table(right))
                self.assertEqual(Counter(tuple(sorted(r.items())) for r in out.to_pylist()),Counter(tuple(sorted(r.items())) for r in expected))
                self.assertGreater(c[{'hash':'hash_probes','sort_merge':'key_comparisons','block_nested':'pairs_considered'}[impl]],0)

    def test_aggregates_null_empty_and_source_order(self):
        rows=[{'g':i%3,'v':None if i%4==0 else i-8} for i in range(23)]
        specs=[{'function':fn,'field':'v','as':fn} for fn in ['count','sum','min','max','mean']]
        expected=[]
        for g in range(3):
            vals=[r['v'] for r in rows if r['g']==g and r['v'] is not None]
            expected.append({'g':g,'count':len(vals),'sum':sum(vals),'min':min(vals),'max':max(vals),'mean':sum(vals)/len(vals)})
        for impl in ['hash_group','sorted_group']:
            out,_=self.perf.relational('aggregate',impl,self.table(rows),{'group_by':['g'],'aggregates':specs})
            self.assertEqual(out.to_pylist(),expected)
            out,_=self.perf.relational('aggregate',impl,self.table(rows).slice(0,0),{'group_by':[],'aggregates':specs})
            self.assertEqual(out.to_pylist(),[{'count':0,'sum':None,'min':None,'max':None,'mean':None}])

    def test_sort_multi_run_stable_nulls_and_payload(self):
        rows=[{'id':i,'v':None if i%101==0 else (i*17)%23,'text':'证据'+str(i)} for i in range(9317)]
        expected=sorted(rows,key=lambda r:(r['v'] is None,r['v'] or 0))
        for impl in ['in_memory','external_merge']:
            with tempfile.TemporaryDirectory() as directory:
                out,c=self.diag.relational('sort',impl,self.table(rows),{'keys':[{'field':'v','direction':'asc','nulls':'last'}]},directory=directory)
                self.assertEqual(out.to_pylist(),expected)
                if impl=='external_merge':self.assertGreaterEqual(c['sort_runs'],10);self.assertGreater(c['spill_write_bytes'],sum(len(r['text'].encode()) for r in rows));self.assertGreaterEqual(c['merge_passes'],2)

    def test_projection_buffers_view_and_copy(self):
        table=self.table([{'id':i,'v':str(i)} for i in range(9)])
        view,_=self.perf.relational('project','column_view',table,{'columns':['v']})
        copy,_=self.perf.relational('project','copy',table,{'columns':['v']})
        self.assertEqual(view.column(0).chunk(0).buffers()[2].address,table.column(1).chunk(0).buffers()[2].address)
        self.assertNotEqual(copy.column(0).chunk(0).buffers()[2].address,view.column(0).chunk(0).buffers()[2].address)
        self.assertEqual(copy.to_pylist(),view.to_pylist())

    def test_int64_checked_arithmetic_and_independent_rounding(self):
        for op,a,b in [('add',2**63-1,1),('sub',-2**63,1),('mul',2**62,3),('div',1,0)]:
            with self.assertRaises(Exception):self.perf.expression(expr(op,literal(a),literal(b)),{})
        rng=random.Random(123)
        pairs=[(2**63-1,3),(-2**63,-1),(2**53+1,7)]+[(rng.randrange(-2**63,2**63),rng.randrange(1,2**63)) for _ in range(10000)]
        for a,b in pairs:self.assertEqual(self.perf.expression(expr('div',literal(a),literal(b)),{}),float(Fraction(a,b)),(a,b))

    def test_unicode_count_and_set_algorithms(self):
        self.assertEqual(self.perf.expression({'op':'count','arg':literal('中🙂e\u0301')},{}),4)
        for impl in ['hash','sorted_merge']:
            for mode,expected in [('union',{1,2,3,4}),('intersection',{2}),('difference',{1,3})]:
                out,c=self.diag.set_op([1,2,2,3],[2,4],mode,impl)
                self.assertEqual(set(out),expected);self.assertEqual(len(out),len(expected))

    def test_graph_multiedges_directions_reachability_and_shortest_oracle(self):
        graph={'directed':True,'nodes':[{'node_id':i} for i in range(8)],'edges':[
            {'edge_id':i,'src':a,'dst':b,'type':'A' if i%2 else 'B','weight':w}
            for i,(a,b,w) in enumerate([(0,1,2),(0,1,1),(1,2,0),(0,3,5),(2,3,1),(3,4,1),(4,1,1),(6,7,1),(2,2,0)])]}
        graph['edge_index']=list(reversed(range(len(graph['edges']))))
        for impl in ['csr','indexed_adjacency']:
            for direction in ['in','out','both']:
                out,_=self.diag.graph('graph_neighbors',impl,graph,[1],{'direction':direction,'edge_types':[]})
                expected=[e for e in graph['edges'] if (direction!='in' and e['src']==1) or (direction!='out' and e['dst']==1)]
                self.assertEqual({e['edge_id'] for e in out},{e['edge_id'] for e in expected})
        for hops in [0,1,2,3,8]:
            expected={0}
            for _ in range(hops):expected|={e['dst'] for e in graph['edges'] if e['src'] in expected}
            for impl in ['bfs','dfs']:
                out,_=self.diag.graph('graph_reachability',impl,graph,[0],{'direction':'out','max_hops':hops})
                self.assertEqual(set(out),expected)
        # Independent Bellman-Ford scans edges, without the kernel adjacency or heap.
        distance=[float('inf')]*8;distance[0]=0
        for _ in range(7):
            for e in graph['edges']:distance[e['dst']]=min(distance[e['dst']],distance[e['src']]+e['weight'])
        out,_=self.diag.graph('graph_shortest_path','dijkstra',graph,[0],{'target':list(range(8)),'weight_field':'weight'})
        edges={e['edge_id']:e for e in graph['edges']}
        for item in out:
            d=distance[item['target']];self.assertEqual(item['reachable'],d<float('inf'));self.assertEqual(item['distance'],d if d<float('inf') else None)
            if item['reachable']:
                self.assertEqual(sum(edges[i]['weight'] for i in item['edges']),d)
                self.assertEqual(item['nodes'][0],0);self.assertEqual(item['nodes'][-1],item['target'])
                for a,b,i in zip(item['nodes'],item['nodes'][1:],item['edges']):self.assertEqual((edges[i]['src'],edges[i]['dst']),(a,b))
        with self.assertRaises(Exception):self.perf.graph('graph_shortest_path','bfs',graph,[0],{'target':3,'weight_field':'weight'})
        predicate=expr('eq',{'field':'type'},literal('A'))
        for impl in ['edge_mask','index_filter']:
            out,c=self.diag.graph('graph_filter',impl,graph,[],{'predicate':predicate})
            self.assertEqual(out['edges'],[e for e in graph['edges'] if e['type']=='A'])
        induced,_=self.perf.graph('graph_subgraph','induced',graph,[0,1,2],{})
        self.assertEqual(induced['edges'],[e for e in graph['edges'] if e['src'] in {0,1,2} and e['dst'] in {0,1,2}])
        selected,_=self.perf.graph('graph_subgraph','edge_selected',graph,[1,7],{})
        self.assertEqual({n['node_id'] for n in selected['nodes']},{0,1,6,7})
