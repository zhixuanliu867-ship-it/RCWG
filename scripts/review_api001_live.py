#!/usr/bin/env python3
"""Independent read-only inspection of one sealed live pilot. No API calls."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rcwg_api.live_review import review_live
from rcwg_api.common import ApiError,Archive
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True)
p.add_argument('--manifest-sha256',required=True);p.add_argument('--seal-sha256',required=True);p.add_argument('--output',required=True)
a=p.parse_args()
try:
    r=review_live(Path(a.directory),manifest_sha256=a.manifest_sha256,seal_sha256=a.seal_sha256)
except (ApiError,OSError,ValueError,TypeError,KeyError) as e:r={'status':'API001_LIVE_REVIEW_BLOCKED','code':e.code if isinstance(e,ApiError) else 'EVIDENCE_INCOMPLETE','formal_ready':False}
Archive(Path(a.output)).json('LIVE_REVIEW.json',r)
print(json.dumps(r,ensure_ascii=False,indent=2))
raise SystemExit(0 if r['status']=='API001_LIVE_F1_ENGINEERING_ACCEPTED' else 2)
