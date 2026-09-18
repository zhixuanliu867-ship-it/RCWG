#!/usr/bin/env python3
"""Review tracked/staged files for obvious credential exposure. This is a guard, not a DLP proof."""
import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
result = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, check=True)
patterns = [re.compile(rb'AIza[0-9A-Za-z_\-]{35}'),
            re.compile(rb'-----BEGIN ' + rb'(?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]
bad = []
for raw in result.stdout.split(b'\0'):
    if not raw: continue
    name = raw.decode('utf-8'); p = root / name
    if not p.is_file(): continue
    if name == '.env' or name.startswith(('runs/', 'private_inputs/', 'gold/', 'data/')):
        bad.append(name + ': private path is tracked')
    content = subprocess.run(['git', 'show', ':' + name], cwd=root, capture_output=True, check=True).stdout
    if any(pattern.search(content) for pattern in patterns):
        bad.append(name + ': possible credential pattern')
if bad:
    raise SystemExit('\n'.join(bad))
print('PASS: tracked-file credential-pattern and private-path guard (not a complete secret audit)')
