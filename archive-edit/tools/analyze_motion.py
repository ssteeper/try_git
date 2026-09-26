#!/usr/bin/env python3
"""Per-source motion/brightness curves. Decodes each video once at 96x72 grey,
8 fps, and stores per-frame mean-abs-difference and mean luma in analysis/<ia>.npz.
usage: analyze_motion.py <video> [<video> ...]"""
import subprocess, sys, os, numpy as np
W, H, FPS = 96, 72, 8
here = os.path.dirname(os.path.abspath(__file__))
outdir = os.path.join(here, '..', 'analysis'); os.makedirs(outdir, exist_ok=True)
for path in sys.argv[1:]:
    ident = os.path.basename(path).split('__')[0]
    dest = os.path.join(outdir, ident + '.npz')
    if os.path.exists(dest): print(ident, 'cached'); continue
    cmd = ['ffmpeg', '-v', 'error', '-i', path, '-vf', f'fps={FPS},scale={W}:{H}', '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**7)
    prev = None; motion = []; luma = []; contrast = []
    n = W * H
    while True:
        buf = p.stdout.read(n)
        if len(buf) < n: break
        f = np.frombuffer(buf, np.uint8).astype(np.float32)
        luma.append(f.mean()); contrast.append(f.std())
        motion.append(0.0 if prev is None else np.abs(f - prev).mean())
        prev = f
    p.wait()
    np.savez_compressed(dest, motion=np.array(motion, np.float32), luma=np.array(luma, np.float32), contrast=np.array(contrast, np.float32), fps=FPS)
    print(ident, len(motion) / FPS, 's analysed', flush=True)
