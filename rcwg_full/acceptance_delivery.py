"""Local source delivery and exact baseline patch/mode verification, no publish."""
import json,subprocess,zipfile
from pathlib import Path
from rcwg_full.evidence import ROOT,exclusive_directory,write,source_hashes,digest
from rcwg_full.acceptance_identity import BASELINE,git_identity,file_hash


def source_delivery(directory):
    out=exclusive_directory(directory);identity=git_identity()
    if not identity['tracked_content_clean'] or identity['untracked_source_files']:raise ValueError('DELIVERY_CLEAN_COMMIT_REQUIRED')
    def git(*args,cwd=ROOT):
        result=subprocess.run(['git',*map(str,args)],cwd=cwd,capture_output=True)
        if result.returncode:raise ValueError('DELIVERY_GIT_FAILED:'+result.stderr.decode('utf8',errors='replace'))
        return result.stdout
    head=identity['head'];bundle=out/'source.bundle';patch=out/'baseline_to_head.patch';archive=out/'public_source.zip'
    git('bundle','create',bundle,'HEAD');git('bundle','verify',bundle)
    write(patch,git('diff','--binary','--full-index','--no-ext-diff','--no-textconv',BASELINE,head))
    git('archive','--format=zip','--output='+str(archive),head)
    checkout=out/'clean_application'
    git('clone','--no-checkout','--config','core.autocrlf=false','--config','core.filemode=false',bundle,checkout)
    git('checkout','--detach',BASELINE,cwd=checkout);git('apply','--check','--index',patch,cwd=checkout)
    git('apply','--index','--binary',patch,cwd=checkout)
    tree=git('write-tree',cwd=checkout).decode().strip()
    if tree!=identity['tree']:raise ValueError('DELIVERY_APPLIED_TREE_MISMATCH')
    sources=source_hashes()
    if any(file_hash(checkout/p)!=h for p,h in sources.items()):raise ValueError('DELIVERY_SOURCE_BYTES')
    protected=json.loads((ROOT/'docs/full001/INHERITED_FILE_HASHES.json').read_text('utf8'))
    if any(file_hash(checkout/p)!=h for p,h in protected.items()):raise ValueError('DELIVERY_PROTECTED_BYTES')
    public={}
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() is not None:raise ValueError('DELIVERY_ZIP_CRC')
        for entry in zipped.infolist():
            if not entry.is_dir():
                from rcwg_full.evidence import sha
                public[entry.filename]={'sha256':sha(zipped.read(entry)),'bytes':entry.file_size}
    write(out/'PUBLIC_FILES_SHA256.json',public)
    proof={'status':'PASS','identity':identity,'baseline':BASELINE,'applied_index_tree':tree,
        'git_modes_and_blob_ids_identical':True,'raw_source_hash':digest(sources),'protected_files':len(protected),
        'bundle_sha256':file_hash(bundle),'patch_sha256':file_hash(patch),'public_zip_sha256':file_hash(archive),
        'scope':'CLEAN_BASELINE_APPLY_AND_SOURCE_DELIVERY_NOT_HOST_APPROVAL','formal_ready':False}
    write(out/'CLEAN_APPLY_PROOF.json',proof);return proof
