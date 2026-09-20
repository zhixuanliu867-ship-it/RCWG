"""Use an already installed compiler; no installer, dependency fetch or fallback."""
from pathlib import Path
import argparse
import os
import platform
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rcwg_native.evidence import ROOT,bootstrap,source_hashes,sha,write

FLAGS=['-std=c++17','-O2','-Wall','-Wextra','-pedantic','-fno-fast-math','-ffp-contract=off','-static-libstdc++','-static-libgcc']

def build(output,compiler=None):
    out=bootstrap(output)
    compiler=shutil.which(compiler or 'g++')
    if not compiler:
        write(out/'SOURCE_AND_BINARY_MANIFEST.json',{'status':'BLOCKED_TOOLCHAIN_UNAVAILABLE','source':source_hashes(),'formal_ready':False,'system_installs':0})
        return 2
    version=subprocess.check_output([compiler,'--version'],text=True)
    target=subprocess.check_output([compiler,'-dumpmachine'],text=True).strip()
    manifest={'revision':'NATIVE001_BINARY_MANIFEST_V1','source':source_hashes(),'compiler':compiler,'compiler_sha256':sha(Path(compiler).read_bytes()),'compiler_version':version,'compiler_target':target,'flags':FLAGS,'platform':platform.platform(),'python':platform.python_version(),'binaries':{},'dependencies':'C++ stdlib statically linked; Linux libc/loader dynamically linked; no third-party packages','installs':0,'formal_ready':False}
    for mode in ['diagnostic','performance']:
        binary=out/('rcwg-native-'+mode)
        args=[compiler,*FLAGS,'-DRCWG_NATIVE_DIAGNOSTICS='+('1' if mode=='diagnostic' else '0'),str(ROOT/'native001/worker.cpp'),'-o',str(binary)]
        result=subprocess.run(args,capture_output=True,timeout=120)
        write(out/(mode+'-build.log'),result.stdout+result.stderr)
        if result.returncode:
            write(out/'BUILD_FAILED.json',{'mode':mode,'returncode':result.returncode,'command':args});return result.returncode
        binary.chmod(0o700)
        manifest['binaries'][mode]={'name':binary.name,'sha256':sha(binary.read_bytes()),'size':binary.stat().st_size,'command':args,'ldd':subprocess.run(['ldd',str(binary)],capture_output=True,text=True).stdout}
    if manifest['source']!=source_hashes():raise RuntimeError('SOURCE_CHANGED_DURING_BUILD')
    manifest['status']='BUILD_PASS';write(out/'SOURCE_AND_BINARY_MANIFEST.json',manifest)
    print('NATIVE001_BUILD_PASS');return 0

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--compiler');a=p.parse_args();raise SystemExit(build(a.output,a.compiler))
