#!/usr/bin/env python3
"""Download the best video for each source slug listed on stdin (one per line).
Resolves slug -> Internet Archive identifier via sources.json, 4 downloads at a time."""
import json, subprocess, sys, os
from concurrent.futures import ThreadPoolExecutor
here = os.path.dirname(os.path.abspath(__file__))
srcs = json.load(open(os.path.join(here, '..', 'sources.json')))
slugs = [l.strip() for l in sys.stdin if l.strip() and not l.startswith('#')]
def get(slug):
    ia = srcs[slug]['ia']
    if not ia: return f'{slug}: no IA id'
    r = subprocess.run([sys.executable, os.path.join(here, 'ia_get.py'), ia[0], os.path.join(here, '..', 'sources')], capture_output=True, text=True)
    return (r.stdout.strip() or r.stderr.strip()) + f'  [{slug}]'
with ThreadPoolExecutor(4) as ex:
    for line in ex.map(get, slugs): print(line, flush=True)
