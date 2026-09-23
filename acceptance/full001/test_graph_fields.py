import os
import unittest
from rcwg_full.runtime.native import Native
from rcwg_full.data.graph_templates import f3
from test_native import expr,literal
import test_runtime as runtime_tests


class PublicGraphFields(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.native=Native(os.environ['RCWG_FULL_BUILD'],'diagnostic')
    def graph(self):
        return {'directed':True,'nodes':[{'id':i,'ok':v} for i,v in enumerate([True,True,False,None,True])],
                'edges':[{'edge_id':i,'source':a,'target':b,'weight':float(w),'type':'A'} for i,(a,b,w) in enumerate([(0,1,1),(1,2,1),(0,3,1),(2,4,1),(1,4,3)])],
                'edge_index':[4,3,2,1,0]}
    def params(self,**kwargs):return {'_graph_fields':{'node_id_field':'id','source_field':'source','target_field':'target'},**kwargs}

    def test_all_traversals_use_public_fields_and_preserve_multiedges(self):
        graph=self.graph()
        for impl in ['csr','indexed_adjacency']:
            out,_=self.native.graph('graph_neighbors',impl,graph,[1],self.params(direction='both',edge_types=[]))
            self.assertEqual({r['edge_id'] for r in out},{0,1,4})
        for impl in ['bfs','dfs']:
            out,_=self.native.graph('graph_reachability',impl,graph,[0],self.params(direction='out',max_hops=2))
            self.assertEqual(set(out),{0,1,2,3,4})
        out,_=self.native.graph('graph_shortest_path','dijkstra',graph,[0],self.params(target=[4],weight_field='weight'))
        self.assertEqual(out,[{'target':4,'distance':3.,'reachable':True,'nodes':[0,1,2,4],'edges':[0,1,3]}])
        induced,_=self.native.graph('graph_subgraph','induced',graph,[0,1,4],self.params())
        self.assertEqual([e['edge_id'] for e in induced['edges']],[0,4])
        selected,_=self.native.graph('graph_subgraph','edge_selected',graph,[2],self.params())
        self.assertEqual([n['id'] for n in selected['nodes']],[0,3])

    def test_node_prefix_evaluates_both_endpoints_and_view_propagates(self):
        graph=self.graph();p={'op':'and','args':[expr('eq',{'field':'node.ok'},literal(True)),expr('le',{'field':'edge.weight'},literal(3.))]}
        expected=[e for e in graph['edges'] if graph['nodes'][e['source']]['ok'] is True and graph['nodes'][e['target']]['ok'] is True and e['weight']<=3.]
        for impl in ['edge_mask','index_filter']:
            view,counts=self.native.graph('graph_filter',impl,graph,[],self.params(predicate=p))
            self.assertEqual(view['edges'],expected);self.assertEqual(view['nodes'],graph['nodes']);self.assertNotIn('edge_index',view)
            actual,_=self.native.graph('graph_reachability','bfs',view,[0],self.params(direction='out',max_hops=5))
            self.assertEqual(set(actual),{0,1,4});self.assertGreater(counts['predicate_evaluations'],len(graph['edges']))
            zero,_=self.native.graph('graph_reachability','dfs',view,[3],self.params(direction='out',max_hops=0))
            self.assertEqual(zero,[3])

    def test_legacy_graph_without_edge_id_traverses_but_cannot_fabricate_path_witness(self):
        graph=self.graph()
        for edge in graph['edges']:edge.pop('edge_id')
        actual,_=self.native.graph('graph_reachability','bfs',graph,[0],self.params(direction='out',max_hops=1))
        self.assertEqual(set(actual),{0,1,3})
        with self.assertRaisesRegex(Exception,'STABLE_EDGE_ID_REQUIRED'):
            self.native.graph('graph_shortest_path','dijkstra',graph,[0],self.params(target=[4],weight_field='weight'))


class PublicGraphRuntime(unittest.IsolatedAsyncioTestCase):
    setUpClass=classmethod(runtime_tests.Runtime.setUpClass.__func__)
    setUp=runtime_tests.Runtime.setUp
    tearDown=runtime_tests.Runtime.tearDown
    execute=runtime_tests.Runtime.execute

    async def test_typed_capabilities_bind_custom_fields_through_filter_view(self):
        case=f3('F3-04',0,'C0');graph=case['rows']['graph'];public=case['task']['datasets'][0]
        for schema,rows,old,new in [('node_schema',graph['nodes'],'node_id','id'),('edge_schema',graph['edges'],'src','source'),('edge_schema',graph['edges'],'dst','target')]:
            public[schema][new]=public[schema].pop(old)
            for row in rows:row[new]=row.pop(old)
        for key in ['node_id_field','source_field','target_field']:public.pop(key)
        self.task=case['task']
        actual=await self.execute(case['plan'],{'dataset:'+k:v for k,v in case['rows'].items()})
        expected=set(case['rows']['seeds'])
        for _ in range(4):expected|={e['target'] for e in graph['edges'] if e['source'] in expected and 10<=e['time']<70 and e['type']=='allowed'}
        self.assertEqual(set(actual),expected)
