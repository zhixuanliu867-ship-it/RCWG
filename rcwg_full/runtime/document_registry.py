"""Domain/revision-bound document adapters created only from prepared public files."""
from rcwg_full.runtime.documents import Documents,validate_document
from rcwg_full.runtime.values import validate


class DocumentRegistry:
    def __init__(self,catalog,*,native=None,event=None):
        self.adapters={}
        for source in catalog.sources.values():
            if source.entry['kind']!='document_index':continue
            if not hasattr(source,'public'):raise ValueError('DOCUMENT_PUBLIC_BINDING_REQUIRED')
            public=source.public;documents=source.value()
            if type(documents) is not list or len(documents)!=public['stats']['document_count']:raise ValueError('DOCUMENT_COUNT')
            seen=set()
            for doc in documents:
                validate_document(doc)
                if doc['revision']!=public['revision']:raise ValueError('DOCUMENT_REVISION_MISMATCH')
                from rcwg_full.compiler.typesystem import parse_schema,type_json
                schema={k:type_json(t) for k,t in parse_schema(public['schema'],'/document/schema').items()}
                if set(schema)-set(doc):raise ValueError('DOCUMENT_SCHEMA_FIELDS')
                validate({k:doc[k] for k in schema},{'kind':'Record','schema':schema},None)
                ident=doc[public.get('id_field','id')]
                if type(ident)!=type(doc['document_id']) or ident!=doc['document_id']:raise ValueError('DOCUMENT_ID_MAPPING')
                key=(type(ident).__name__,ident)
                if key in seen:raise ValueError('DOCUMENT_ID_DUPLICATE')
                seen.add(key)
            key=(public['domain'],public['revision'])
            if key in self.adapters:raise ValueError('DOCUMENT_DOMAIN_REVISION_AMBIGUOUS')
            from rcwg_full.runtime.dense_encoder import bind_encoder
            encoder=bind_encoder(source,documents)
            self.adapters[key]=Documents(documents,native=native,event=event,query_encoder=encoder)

    async def dispatch(self,op,impl,inputs,p,*,semantic,instance,scheduler,node):
        port='index' if 'index' in node['inputs'] else 'documents' if 'documents' in node['inputs'] else 'chunks' if 'chunks' in node['inputs'] else 'evidence'
        typ=node['inputs'][port]
        while typ['kind'] in {'ArtifactRef','DatasetRef'}:typ=typ['item']
        key=(typ.get('domain'),typ.get('revision'))
        if key not in self.adapters:raise ValueError('DOCUMENT_DOMAIN_REVISION_UNBOUND')
        return await self.adapters[key].dispatch(op,impl,inputs,p,semantic=semantic,instance=instance,scheduler=scheduler,node=node)
