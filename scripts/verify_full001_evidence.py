"""Read-only source/binary/outcome/dispatch audit; writes a separate report."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rcwg_full.acceptance_evidence import build_evidence
from rcwg_full.evidence import write


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tests',type=Path,required=True)
    parser.add_argument('--build',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:report=build_evidence(args.tests,args.build)
    except (ValueError,KeyError,OSError) as exc:
        report={'status':'FAIL','failure':str(exc),'formal_ready':False};write(args.output,report);print(json.dumps(report));return 1
    write(args.output,report)
    print(json.dumps({'status':report['status'],'tests':report['tests_run'],'dispatches':report['dispatches']['count'],
        'tiny_closures':len(report['fixture_closures']['tiny']),'mutations':len(report['fixture_closures']['mutations']),
        'equivalences':len(report['fixture_closures']['equivalences']),'formal_ready':False}));return 0


if __name__=='__main__':raise SystemExit(main())
