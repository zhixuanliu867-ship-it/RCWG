"""Seal the reproducible delivery; no deletions or external uploads."""
import datetime,hashlib,zipfile
from common import *

def included(p):
    rel=p.relative_to(ROOT)
    return p.is_file() and rel.parts[0] not in ('local_only','deliveries','.git') and '__pycache__' not in rel.parts and p.suffix not in ('.pyc','.pyo') and rel.as_posix()!='manifest.json' and p.name not in ('.env',)

def make_zip(path,files,manifest):
    if path.exists():raise FileExistsError('Delivery already exists; do not overwrite a sealed package: '+str(path))
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for p in files:z.write(p,p.relative_to(ROOT).as_posix())
    failures=[];expected={x['path']:x for x in manifest['files']};checked=0
    with zipfile.ZipFile(path) as z:
        bad=z.testzip()
        if bad:failures.append({'crc':bad})
        for info in z.infolist():
            if info.filename=='manifest.json':continue
            with z.open(info) as f:
                h=hashlib.sha256()
                for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
            if info.filename not in expected or h.hexdigest()!=expected[info.filename]['sha256']:failures.append(info.filename)
            checked+=1
    result={'file':path.name,'bytes':path.stat().st_size,'sha256':sha(path),'archive_entries':len(files),'content_files_verified':checked,'crc_and_content_hash_pass':not failures,'errors':failures}
    if failures:raise RuntimeError(dump(result))
    return result

def main():
    if not load(ROOT/'qa/release_consistency.json')['pass']:raise RuntimeError('Release consistency check has not passed')
    files=sorted((p for p in ROOT.rglob('*') if included(p)),key=lambda p:p.relative_to(ROOT).as_posix())
    manifest={'release':'RCWG_FINAL_IMPLEMENTED_20261013','sealed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'file_count':len(files),'excluded':['local_only/** (installed official data, caches, local environment)','deliveries/** (archives and external verification receipt)','__pycache__/**','*.pyc','manifest.json (self hash in delivery receipt)'],'files':[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in files]}
    write(ROOT/'manifest.json',manifest)
    d=ROOT/'deliveries';d.mkdir(exist_ok=True)
    full=make_zip(d/'RCWG_FINAL_完整数据任务与评估器_20261013.zip',files+[ROOT/'manifest.json'],manifest)
    readable=[p for p in files if p.relative_to(ROOT).parts[0] in ('reports','analysis','protocol','qa','replay') or p.relative_to(ROOT).as_posix() in ('README_先读.md','REPRODUCE_zh.md','dataset_catalog.json','task_index.csv','environment.lock.txt','appworld_environment.lock.txt')]
    small=make_zip(d/'RCWG_FINAL_易读报告与底表_20261013.zip',readable+[ROOT/'manifest.json'],manifest)
    receipt={'release':manifest['release'],'manifest_sha256':sha(ROOT/'manifest.json'),'manifest_files':len(files),'manifest_uncompressed_bytes':sum(x['bytes'] for x in manifest['files']),'archives':[full,small],'readable_scope':'Selected reports, tables, protocols and QA; manifest describes full release. It is not the standalone executable distribution.','full_scope':'Full runnable release excluding installed local environments, unpacked official AppWorld data and caches; official AppWorld bundle included.'}
    write(d/'交付校验.json',receipt);print(dump(receipt))

if __name__=='__main__':main()
