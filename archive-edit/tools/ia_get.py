#!/usr/bin/env python3
"""Download the best available video file for an Internet Archive item.

Uses https://archive.org/cors/<id>/<file>, which serves the bytes from
archive.org itself instead of redirecting to a per-item mirror host.

usage: ia_get.py <identifier> <out_dir> [--max-mb N]
prints: <local path>\t<width>x<height>\t<format>
"""
import json, sys, os, time, urllib.request, urllib.parse

VIDEO_EXT = ('.mp4', '.mpeg', '.mpg', '.ogv', '.avi', '.mkv', '.mov', '.m4v')

def rank(f, max_mb):
    name = f['name'].lower(); fmt = (f.get('format') or '').lower()
    size_mb = int(f.get('size', 0)) / 1e6
    w = int(f.get('width') or 0); h = int(f.get('height') or 0)
    if not name.endswith(VIDEO_EXT): return None
    if 'thumb' in name: return None
    if size_mb > max_mb: return None
    score = w * h
    if fmt.startswith('h.264') or 'h.264' in fmt: score += 5_000_000   # prefer h.264 mp4s
    if 'mpeg2' in fmt: score += 2_000_000                              # good quality, big
    if '512kb' in name: score -= 1_000_000
    if name.endswith('.ogv'): score -= 500_000
    return score

def main():
    ident, out_dir = sys.argv[1], sys.argv[2]
    max_mb = float(sys.argv[sys.argv.index('--max-mb')+1]) if '--max-mb' in sys.argv else 900
    os.makedirs(out_dir, exist_ok=True)
    meta = json.load(urllib.request.urlopen(f'https://archive.org/metadata/{ident}', timeout=60))
    files = [f for f in meta.get('files', []) if rank(f, max_mb) is not None]
    if not files:
        print(f'{ident}: no video file under {max_mb} MB', file=sys.stderr); sys.exit(2)
    best = max(files, key=lambda f: rank(f, max_mb))
    dest = os.path.join(out_dir, ident + '__' + os.path.basename(best['name']))
    if os.path.exists(dest) and os.path.getsize(dest) == int(best.get('size', -1)):
        print(f"{dest}\t{best.get('width')}x{best.get('height')}\t{best.get('format')}\tcached"); return
    url = f"https://archive.org/cors/{ident}/{urllib.parse.quote(best['name'])}"
    t0 = time.time()
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(dest + '.part', 'wb') as w:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk: break
                    w.write(chunk)
            os.replace(dest + '.part', dest); break
        except Exception as e:
            print(f'{ident}: attempt {attempt+1} failed: {e}', file=sys.stderr); time.sleep(3 * (attempt + 1))
    else:
        sys.exit(3)
    mb = os.path.getsize(dest) / 1e6
    print(f"{dest}\t{best.get('width')}x{best.get('height')}\t{best.get('format')}\t{mb:.0f}MB in {time.time()-t0:.0f}s ({mb/(time.time()-t0):.1f} MB/s)")

if __name__ == '__main__':
    main()
