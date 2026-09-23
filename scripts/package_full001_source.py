"""Produce a local source bundle and verify clean baseline application."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rcwg_full.acceptance_delivery import source_delivery

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(source_delivery(args.output)))
