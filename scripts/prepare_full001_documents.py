"""Offline real-source F5/F6 binding; no labels, services or approval fabricated."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rcwg_full.data.formal_documents import bind_candidate
from rcwg_full.evidence import read


def main():
    parser=argparse.ArgumentParser()
    for name in ['bundle','design','private-labels','output']:parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--reviewers',nargs=2,required=True)
    args=parser.parse_args()
    result=bind_candidate(json.loads(read(args.bundle)),json.loads(read(args.design)),
        json.loads(read(args.private_labels)),args.output,reviewers=args.reviewers)
    print(json.dumps({'status':'CANDIDATE_BOUND_NOT_FROZEN','task_id':result['task']['task_id'],
        'manifest':str(result['manifest_path']),'private_directory':str(result['private_directory']),
        'formal_ready':False},ensure_ascii=False))


if __name__=='__main__':main()
