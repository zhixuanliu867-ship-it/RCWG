"""Offline reference entry; no public API/cloud execution command is exposed."""
import argparse
import json
from pathlib import Path
from .demo import run_demo
from .errors import ExecFault

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='cmd',required=True)
    d=sub.add_parser('demo');d.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    try:
        r=run_demo(a.output);print(json.dumps(r,ensure_ascii=False,indent=2));return 0 if r['status']=='EXEC001_REFERENCE_DEMO_PASS' else 1
    except (ExecFault,OSError,ValueError) as exc:
        print(json.dumps({'status':'EXEC001_ENGINEERING_ERROR','error_type':type(exc).__name__,
                          'code':getattr(exc,'code','LOCAL_OUTPUT_ERROR'),'formal_ready':False}));return 2
if __name__=='__main__':raise SystemExit(main())
