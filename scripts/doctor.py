#!/usr/bin/env python3
"""Standalone, standard-library-only entry. No install, sudo, or network is used."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rcwg_boot.doctor import collect
from rcwg_boot.common import write_json

if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) == 2 else Path("runs/doctor.json")
    if len(sys.argv) > 2:
        raise SystemExit("usage: python3 scripts/doctor.py [new-output.json]")
    write_json(target, collect())
    print(json.dumps({"status": "COLLECTED", "report": str(target)}, ensure_ascii=False))
