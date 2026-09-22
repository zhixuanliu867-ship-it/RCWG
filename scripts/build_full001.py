"""Explicit build with existing compiler and prepared hash-locked dependencies."""
from pathlib import Path
import argparse
import importlib.metadata
import platform
import shutil
import subprocess
import sys
import sysconfig
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rcwg_full.evidence import ROOT,exclusive_directory,source_hashes,write,sha

FLAGS=['-std=c++20','-O2','-shared','-fPIC','-Wall','-Wextra','-fno-fast-math','-ffp-contract=off']

def build(output,compiler='g++'):
    out=exclusive_directory(output)
    manifest={'status':'BUILD_STARTED','python':platform.python_version(),'executable':sys.executable,
        'lock_sha256':sha((ROOT/'environments/full001/requirements.lock').read_bytes()),
        'source':source_hashes(),'flags':FLAGS,'binaries':{},'system_installs':0,'formal_ready':False}
    if platform.python_version()!='3.12.14':
        manifest['status']='BLOCKED_PYTHON_VERSION';write(out/'BUILD.json',manifest);return 2
    for name,version in [('pyarrow','21.0.0'),('pybind11','3.0.1')]:
        if importlib.metadata.version(name)!=version:raise RuntimeError('DEPENDENCY_VERSION_MISMATCH')
    import pyarrow as pa
    import pybind11
    cc=shutil.which(compiler)
    if not cc:
        manifest['status']='BLOCKED_TOOLCHAIN_UNAVAILABLE';write(out/'BUILD.json',manifest);return 2
    lib=Path(pa.get_library_dirs()[0])
    libraries=[next(lib.glob('libarrow.so.*')),next(lib.glob('libarrow_python.so.*'))]
    manifest.update(compiler=cc,compiler_sha256=sha(Path(cc).read_bytes()),
        compiler_version=subprocess.check_output([cc,'--version'],text=True),
        soabi=sysconfig.get_config_var('SOABI'),
        dependencies={p.name:sha(p.read_bytes()) for p in libraries})
    for mode in ['performance','diagnostic']:
        name='_full001_'+mode
        target=out/(name+sysconfig.get_config_var('EXT_SUFFIX'))
        cmd=[cc,*FLAGS,'-DRCWG_FULL_DIAGNOSTICS='+str(int(mode=='diagnostic')),'-DRCWG_MODULE_NAME='+name,
            '-I'+sysconfig.get_paths()['include'],'-I'+pa.get_include(),'-I'+pybind11.get_include(),
            str(ROOT/'native_full001/module.cpp'),*[str(p) for p in libraries],'-Wl,-rpath,'+str(lib),'-o',str(target)]
        result=subprocess.run(cmd,capture_output=True,timeout=180)
        write(out/(mode+'.log'),result.stdout+result.stderr)
        if result.returncode:
            manifest.update(status='BUILD_FAILED',command=cmd,returncode=result.returncode)
            write(out/'BUILD.json',manifest);return 1
        manifest['binaries'][mode]={'name':target.name,'sha256':sha(target.read_bytes()),'command':cmd}
    target=out/'full001-launcher'
    cmd=[cc,'-x','c','-std=c11','-O2','-Wall','-Wextra',str(ROOT/'native_full001/launcher.c'),'-o',str(target)]
    result=subprocess.run(cmd,capture_output=True,timeout=60)
    write(out/'launcher.log',result.stdout+result.stderr)
    if result.returncode:
        manifest.update(status='BUILD_FAILED',command=cmd,returncode=result.returncode)
        write(out/'BUILD.json',manifest);return 1
    manifest['binaries']['launcher']={'name':target.name,'sha256':sha(target.read_bytes()),'command':cmd}
    if manifest['source']!=source_hashes():raise RuntimeError('SOURCE_CHANGED_DURING_BUILD')
    manifest['status']='BUILD_PASS';write(out/'BUILD.json',manifest)
    print('FULL001_BUILD_PASS');return 0

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--compiler',default='g++')
    a=p.parse_args();raise SystemExit(build(a.output,a.compiler))
