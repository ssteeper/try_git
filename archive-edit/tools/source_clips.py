#!/usr/bin/env python3
"""Fetch the complete shot list for source slugs (stdin, one per line) from the
Moving Image Archive source pages, whose server payload embeds every shot.
Writes/updates clips_full.json: {slug: [clip, ...]}."""
import json, re, sys, os, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
here = os.path.dirname(os.path.abspath(__file__))
out = os.path.join(here, '..', 'clips_full.json')
db = json.load(open(out)) if os.path.exists(out) else {}
slugs = [l.strip() for l in sys.stdin if l.strip() and not l.startswith('#')]
def fetch(slug):
    if slug in db: return slug, None, 'cached'
    for a in range(5):
        try:
            s = urllib.request.urlopen(f'https://www.movingimagearchive.com/sources/{slug}', timeout=90).read().decode()
            i = s.find('\\"clips\\":[')
            if i < 0: return slug, [], 'no clips key'
            j = s.find('],\\"', i)  # end of the clips array
            frag = s[i + len('\\"clips\\":'): j + 1].replace('\\"', '"').replace('\\\\', '\\')
            clips = json.loads(frag)
            keep = [{k: c.get(k) for k in ('id', 'position', 'startSeconds', 'endSeconds', 'durationSeconds', 'colorMode', 'aspectRatio')} for c in clips]
            import html as _h
            ia = sorted(set(re.findall(r'archive\.org/details/([A-Za-z0-9_.\-]+)', s)) - {'prelinger'})
            t = re.sub(r'<script.*?</script>', '', s, flags=re.S); t = re.sub(r'<[^>]+>', ' ', t); t = _h.unescape(re.sub(r'\s+', ' ', t))
            m = re.search(r'Collection (.*?) Original title', t); coll = m.group(1) if m else None
            m = re.search(r'Rights ([a-z_]+)', t); rights = m.group(1) if m else None
            meta = dict(sourceId=clips[0].get('sourceId') if clips else None, title=(clips[0].get('sourceTitle') if clips else slug),
                        year=(clips[0].get('sourceYear') if clips else None), n=len(keep), ia=ia, collection=coll, rights=rights)
            return slug, (keep, meta), f'{len(keep)} shots, ia={ia}, rights={rights}'
        except Exception as e:
            err = e; time.sleep(2 * (a + 1))
    return slug, [], f'error {err}'
srcp = os.path.join(here, '..', 'sources.json')
srcs = json.load(open(srcp)) if os.path.exists(srcp) else {}
with ThreadPoolExecutor(4) as ex:
    for slug, res, msg in ex.map(fetch, slugs):
        if isinstance(res, tuple):
            clips, meta = res
            if clips: db[slug] = clips
            if slug not in srcs: srcs[slug] = meta
            elif not srcs[slug].get('ia'): srcs[slug]['ia'] = meta['ia']
        print(f'{slug}: {msg}', flush=True)
json.dump(db, open(out, 'w'))
json.dump(srcs, open(srcp, 'w'), indent=1)
print('total sources in clips_full.json:', len(db), 'shots:', sum(len(v) for v in db.values()))
