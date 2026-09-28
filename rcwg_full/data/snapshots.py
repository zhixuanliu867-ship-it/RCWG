"""Hash-bound local/HTTPS snapshots and bounded, traversal-safe extraction."""
from pathlib import Path,PurePosixPath
import hashlib
import json
import os
import re
import shutil
import stat
import urllib.request
from urllib.parse import urlsplit
import zipfile
from rcwg_full.evidence import digest,read,write,safe_path,sha
from rcwg_full.campaign.sealing import relative_file


def file_hash(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def snapshot(source,directory,*,expected_sha256,max_bytes,upstream_revision,license_record=None,allow_network=False,resume=False):
    if not re.fullmatch('[0-9a-f]{64}',expected_sha256) or type(max_bytes) is not int or max_bytes<1 or not upstream_revision:raise ValueError('SNAPSHOT_IDENTITY')
    root=safe_path(directory)
    declaration={'revision':'FULL001_SOURCE_SNAPSHOT_1','source':str(source),'expected_sha256':expected_sha256,'max_bytes':max_bytes,
                 'upstream_revision':upstream_revision,'license_record':license_record}
    if resume:
        if json.loads(read(root/'declaration.json'))!=declaration:raise ValueError('SNAPSHOT_RESUME_BINDING')
    else:root.mkdir(parents=True,exist_ok=False,mode=0o700);write(root/'declaration.json',declaration)
    target=root/'source.snapshot'
    if target.exists():
        if file_hash(target)!=expected_sha256:raise ValueError('SNAPSHOT_CHANGED')
        return json.loads(read(root/'snapshot.json'))
    partial=root/'source.partial';offset=partial.stat().st_size if partial.exists() else 0
    if offset>max_bytes:raise ValueError('SNAPSHOT_SIZE_LIMIT')
    url=urlsplit(str(source));remote=url.scheme.lower() in {'http','https'}
    if remote:
        if not allow_network:raise PermissionError('EXPLICIT_SOURCE_NETWORK_REQUIRED')
        if url.scheme!='https' or url.username or url.password or url.fragment:raise ValueError('SNAPSHOT_HTTPS_URL')
        from rcwg_api.vertex import NoRedirect
        opener=urllib.request.build_opener(NoRedirect())
        request=urllib.request.Request(str(source),headers={'Accept-Encoding':'identity',**({'Range':f'bytes={offset}-'} if offset else {})})
        stream=opener.open(request,timeout=60)
        if offset and (stream.status!=206 or not stream.headers.get('Content-Range','').startswith(f'bytes {offset}-')):
            stream.close();raise ValueError('SNAPSHOT_RANGE_NOT_HONORED')
        if not offset and stream.status!=200:stream.close();raise ValueError('SNAPSHOT_HTTP_STATUS')
    else:
        source=safe_path(source)
        if not source.is_file() or source.stat().st_size>max_bytes:raise ValueError('SNAPSHOT_LOCAL_SOURCE')
        if offset:
            with partial.open('rb') as old,source.open('rb') as original:
                remaining=offset
                while remaining:
                    a=old.read(min(1024**2,remaining));b=original.read(len(a))
                    if not a or a!=b:raise ValueError('SNAPSHOT_PREFIX_CHANGED')
                    remaining-=len(a)
        stream=source.open('rb');stream.seek(offset)
    size=offset
    with stream,partial.open('ab' if offset else 'xb') as sink:
        while True:
            chunk=stream.read(min(1024**2,max_bytes-size+1))
            if not chunk:break
            size+=len(chunk)
            if size>max_bytes:raise ValueError('SNAPSHOT_SIZE_LIMIT')
            sink.write(chunk)
        sink.flush();os.fsync(sink.fileno())
    if file_hash(partial)!=expected_sha256:raise ValueError('SNAPSHOT_HASH_MISMATCH')
    os.rename(partial,target)
    result={'revision':'FULL001_SOURCE_SNAPSHOT_1','status':'HASH_VERIFIED','declaration_hash':digest(declaration),
            'sha256':expected_sha256,'bytes':size,'upstream_revision':upstream_revision,'source':str(source),
            'license_status':'RECORDED_PENDING_REVIEW' if license_record else 'UNVERIFIED_NO_REDISTRIBUTION',
            'redistribution_authorized':False,'formal_frozen':False}
    write(root/'snapshot.json',result);return result


def extract_zip(snapshot_path,directory,*,expected_sha256,max_files,max_uncompressed_bytes):
    if file_hash(snapshot_path)!=expected_sha256:raise ValueError('ARCHIVE_HASH')
    root=safe_path(directory)
    with zipfile.ZipFile(snapshot_path) as archive:
        members=archive.infolist();files=[m for m in members if not m.is_dir()]
        if len(files)>max_files or sum(m.file_size for m in files)>max_uncompressed_bytes:raise ValueError('ARCHIVE_CAPACITY')
        names=set()
        for member in members:
            relative_file(root,member.orig_filename.rstrip('/'))
            name=member.filename.rstrip('/')
            relative_file(root,name)
            folded=name.casefold()
            if folded in names:raise ValueError('ARCHIVE_DUPLICATE_PATH')
            names.add(folded)
            kind=stat.S_IFMT(member.external_attr>>16)
            if kind not in {0,stat.S_IFREG,stat.S_IFDIR} or member.flag_bits&1:raise ValueError('ARCHIVE_SPECIAL_FILE')
        root.mkdir(parents=True,exist_ok=False,mode=0o700);manifest=[]
        for member in files:
            path=relative_file(root,member.filename);path.parent.mkdir(parents=True,exist_ok=True)
            total=0;h=hashlib.sha256()
            with archive.open(member) as source,path.open('xb') as sink:
                while True:
                    raw=source.read(1024**2)
                    if not raw:break
                    total+=len(raw)
                    if total>member.file_size:raise ValueError('ARCHIVE_DECLARED_SIZE')
                    h.update(raw);sink.write(raw)
                sink.flush();os.fsync(sink.fileno())
            if total!=member.file_size:raise ValueError('ARCHIVE_PARTIAL_FILE')
            manifest.append({'path':member.filename,'sha256':h.hexdigest(),'bytes':total})
    result={'archive_sha256':expected_sha256,'files':manifest,'logical_duplicate_content_groups':{},'executed_files':0,'formal_frozen':False}
    for entry in manifest:result['logical_duplicate_content_groups'].setdefault(entry['sha256'],[]).append(entry['path'])
    write(root/'extraction-manifest.json',result);return result
