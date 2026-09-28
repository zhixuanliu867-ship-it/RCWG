"""Local frozen token-embedding encoder with authenticated numeric weights.

This is an actual mean-pooling model, never hash-generated vectors or BM25.
Model selection/weights/license review remain part of the dataset freeze. The
engineering model used in tests has hand-authored weights and is labeled so.
"""
import math
from rcwg_full.evidence import digest
from rcwg_full.runtime.documents import tokens

PROFILE={'revision':'full001-static-token-embedding-1',
    'tokenizer':'full001-unicode-word-punctuation-v1','transform':'casefold',
    'pooling':'mean including OOV','oov':'explicit model vector','similarity':'exact dot product'}


class FrozenTokenEncoder:
    def __init__(self,model):
        from copy import deepcopy
        model=deepcopy(model)
        if set(model)!={'profile','model_id','dimension','normalize','weights','oov','provenance'} or model['profile']!=PROFILE:raise ValueError('DENSE_MODEL_PROFILE')
        if type(model['model_id']) is not str or not model['model_id'] or type(model['normalize']) is not bool:raise ValueError('DENSE_MODEL_ID')
        n=model['dimension']
        if type(n) is not int or not 1<=n<=4096:raise ValueError('DENSE_MODEL_DIMENSION')
        if type(model['weights']) is not dict or not model['weights']:raise ValueError('DENSE_MODEL_WEIGHTS')
        for token,vector in list(model['weights'].items())+[(None,model['oov'])]:
            if token is not None and (type(token) is not str or [t['token'].casefold() for t in tokens(token)]!=[token]):raise ValueError('DENSE_MODEL_TOKEN')
            if type(vector) is not list or len(vector)!=n or any(type(x) not in {int,float} or not math.isfinite(x) for x in vector):raise ValueError('DENSE_MODEL_VECTOR')
        if not isinstance(model['provenance'],dict) or not all(model['provenance'].get(k) for k in ['origin','license','source_revision']):raise ValueError('DENSE_MODEL_PROVENANCE')
        self.model=model;self.identity=digest(model);self.origin=model['provenance']['origin']

    def encode(self,text):
        vector=[0.]*self.model['dimension'];count=0
        for token in tokens(text):
            embedding=self.model['weights'].get(token['token'].casefold(),self.model['oov']);count+=1
            for i,value in enumerate(embedding):vector[i]+=value
        if count:vector=[v/count for v in vector]
        if self.model['normalize']:
            norm=math.sqrt(sum(v*v for v in vector))
            if norm:vector=[v/norm for v in vector]
        if any(not math.isfinite(v) for v in vector):raise ValueError('DENSE_ENCODING_NONFINITE')
        return vector


def bind_encoder(source,documents):
    import json
    spec=source.entry.get('dense_encoder')
    public=source.public
    declared=[i for i in public.get('indexes',[]) if i['kind']=='dense_fixed']
    if spec is None:
        if declared or public.get('dense_model_id'):raise ValueError('DENSE_MODEL_ASSET_REQUIRED')
        return None
    encoder=FrozenTokenEncoder(json.loads(source.file(spec['model_file'])))
    if spec['model_sha256']!=encoder.identity or any(i['model_id']!=encoder.model['model_id'] for i in declared) or public.get('dense_model_id',encoder.model['model_id'])!=encoder.model['model_id']:raise ValueError('DENSE_MODEL_BINDING')
    index=[]
    for doc in documents:
        expected=encoder.encode(doc['canonical_text'])
        if doc.get('vector')!=expected:raise ValueError('DENSE_INDEX_ENCODING_MISMATCH')
        index.append({'document_id':doc['document_id'],'text_sha256':doc['canonical_text_sha256'],'vector':expected})
    if digest(index)!=spec['index_sha256']:raise ValueError('DENSE_INDEX_BINDING')
    return encoder
