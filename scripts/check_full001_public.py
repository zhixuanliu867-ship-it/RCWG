"""Additional public source-tree guard after staging; no private artifact exports."""
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
files=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
forbidden=[]
for name in files:
    if not name:continue
    p=Path(name)
    if '__pycache__' in p.parts or p.suffix.lower() in {'.pyc','.pyo','.pyd','.so','.dll','.sqlite','.sqlite3','.db','.arrow','.parquet'} or p.name.endswith(('-wal','-shm')):forbidden.append(name)
    if p.parts[0] in {'runs','private','outputs'}:forbidden.append(name)
if forbidden:
    print('PUBLIC_TREE_FAIL',forbidden);raise SystemExit(1)
subprocess.run([sys.executable,'scripts/check_public_tree.py'],cwd=root,check=True)
print('FULL001_PUBLIC_SOURCE_TREE_PASS')
