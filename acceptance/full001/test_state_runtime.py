import unittest
import test_runtime as fixture


class BoundedStateRuntime(unittest.IsolatedAsyncioTestCase):
    setUpClass=classmethod(fixture.Runtime.setUpClass.__func__)
    setUp=fixture.Runtime.setUp
    tearDown=fixture.Runtime.tearDown
    execute=fixture.Runtime.execute
    def plan(self):
        schema={'n':'Int64','items':{'kind':'List','item':'Int64','max_length':3}}
        self.task['datasets']=[{'id':'dataset:state','kind':'record','revision':'v1','schema_source':'engineering','schema':schema}]
        self.task['output_contract']={'id':'result','type':'record','mode':'exact','fields':['n','items'],'schema':schema}
        step=fixture.node('step','project','column_view',{'rows':'$bound.state'},
            {'representation':'record','columns':['items'],'expressions':{'n':{'op':'add','left':{'field':'n'},'right':{'literal':1}}}},{'rows':'Record'})
        repeat=fixture.node('repeat','loop','bounded_loop',{'state':'$input.state'},
            {'condition':{'op':'lt','left':{'field':'n'},'right':{'literal':3}},'max_iterations':3},{'state':'Record'},
            regions={'body':{'bindings':{'state':'$state'},'nodes':[step],'yield':{'state':'step.rows'}}})
        return {'ir_version':'1.0','task_id':self.task['task_id'],'external_inputs':{'state':'dataset:state'},'nodes':[repeat],'result':'repeat.state'}
    async def test_actual_bounded_list_loop_state(self):
        result=await self.execute(self.plan(),{'dataset:state':{'n':0,'items':[3,4]}})
        self.assertEqual(result,{'n':3,'items':[3,4]})
    async def test_actual_external_state_exceeds_bound(self):
        with self.assertRaisesRegex(ValueError,'LIST_LIMIT'):
            await self.execute(self.plan(),{'dataset:state':{'n':0,'items':[1,2,3,4]}})
