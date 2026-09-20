"""Explicit synthetic wire responses. This module never acquires credentials."""
from copy import deepcopy
from .common import canonical
from .vertex import Response

class MockTransport:
    mode='MOCK'
    def __init__(self,responses):self.responses=list(responses);self.calls=[];self.dispatch_count=0
    def send(self,kind,body,request_id):
        self.dispatch_count+=1;self.calls.append((kind,body,request_id))
        if not self.responses:raise RuntimeError('mock response exhaustion')
        item=self.responses.pop(0)
        if isinstance(item,Exception):raise item
        return item

def count(tokens=1000):return Response(200,canonical({'totalTokens':tokens}),{'content-type':'application/json'},100)

def generated(obj,*,version='MOCK-gemini-3.1-flash-lite',finish='STOP',usage=True):
    body={'modelVersion':version,'responseId':'MOCK_RESPONSE',
          'candidates':[{'finishReason':finish,'content':{'role':'model','parts':[{'text':canonical(obj).decode('utf8')}]}}]}
    if usage:body['usageMetadata']={'promptTokenCount':1000,'candidatesTokenCount':200,'thoughtsTokenCount':0,'totalTokenCount':1200}
    return Response(200,canonical(body),{'content-type':'application/json'},100)

def wire_fixtures(plan):
    logical={field:[field+' public F1 task obligations'] for field in
             ('required_outputs','hard_constraints','necessary_operations','data_dependencies','information_requirements')}
    logical.update(permissible_alternatives=['full_sort or streaming_heap'],uncertainty=[])
    return [count(),generated(plan),count(),generated(logical),count(),generated(plan)]
