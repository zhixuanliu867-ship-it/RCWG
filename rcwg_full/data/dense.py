"""Build a fixed exact-dot index from supplied frozen model weights, offline."""
from copy import deepcopy
from rcwg_full.runtime.dense_encoder import FrozenTokenEncoder
from rcwg_full.evidence import canonical,digest,write,sha


def prepare_dense(task,values,models,directory,**kwargs):
    from rcwg_full.data.prepare import prepare
    from pathlib import Path
    task=deepcopy(task);values=deepcopy(values);assets={}
    for public in task['datasets']:
        ident=public['id']
        if ident not in models:continue
        if public['kind']!='document_index':raise ValueError('DENSE_SOURCE_KIND')
        model=models[ident];encoder=FrozenTokenEncoder(model)
        public['dense_model_id']=model['model_id']
        public['indexes']=[i for i in public.get('indexes',[]) if i['kind']!='dense_fixed']+[
            {'id':'dense-exact','kind':'dense_fixed','fields':['canonical_text'],'revision':public['revision'],
             'source':'full001-frozen-encoder','model_id':model['model_id']}]
        index=[]
        for doc in values[ident]:
            doc['vector']=encoder.encode(doc['canonical_text'])
            index.append({'document_id':doc['document_id'],'text_sha256':doc['canonical_text_sha256'],'vector':doc['vector']})
        assets[ident]=(model,encoder.identity,digest(index))
    if set(assets)!=set(models) or not assets:raise ValueError('DENSE_SOURCE_SET')
    prepared,manifest,path=prepare(task,values,directory,**kwargs)
    for entry in manifest['sources']:
        if entry['source_id'] not in assets:continue
        model,identity,index_hash=assets[entry['source_id']];name='dense-'+identity+'.json';raw=canonical(model)+b'\n'
        asset=Path(directory)/name
        if not asset.exists():write(asset,raw)
        entry['dense_encoder']={'model_file':{'path':name,'sha256':sha(raw),'bytes':len(raw)},
            'model_sha256':identity,'index_sha256':index_hash}
    # Preserve the preparation manifest, then publish a distinct bound manifest.
    path=Path(directory)/'dense_data_manifest.json';write(path,manifest)
    return prepared,manifest,path
