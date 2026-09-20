"""Build only using existing GitHub/local compiler; never installs software."""
from pathlib import Path
import argparse,platform,shutil,subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rcwg_native.evidence import ROOT,bootstrap,write,sha
def main(output):
    out=bootstrap(output);manifest={'revision':'N4_BUILD_V1','status':'BUILD_PASS','platform':platform.platform(),'binaries':{},'source':{},'system_installs':0}
    for name,filename,compiler,flags in [('launcher','launcher.c','gcc',['-std=c11','-O2','-Wall','-Wextra']),('calibration','calibration.cpp','g++',['-std=c++17','-O2','-Wall','-Wextra','-fno-fast-math','-ffp-contract=off','-static-libstdc++','-static-libgcc'])]:
        cc=shutil.which(compiler)
        if not cc:raise RuntimeError('EXISTING_COMPILER_REQUIRED')
        src=ROOT/'native001_n4'/filename;dest=out/('rcwg-n4-'+name);command=[cc,*flags,str(src),'-o',str(dest)]
        r=subprocess.run(command,capture_output=True,timeout=120);write(out/(name+'.build.log'),r.stdout+r.stderr)
        if r.returncode:raise RuntimeError('BUILD_FAILED:'+name)
        dest.chmod(0o700);manifest['source'][str(src.relative_to(ROOT))]=sha(src.read_bytes())
        manifest['binaries'][name]={'name':dest.name,'sha256':sha(dest.read_bytes()),'command':command,'flags':flags,
            'compiler_sha256':sha(Path(cc).read_bytes()),'compiler_version':subprocess.check_output([cc,'--version'],text=True),
            'ldd':subprocess.run(['ldd',str(dest)],capture_output=True,text=True).stdout}
    write(out/'N4_BUILD.json',manifest);print('N4_BUILD_PASS')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args().output)
