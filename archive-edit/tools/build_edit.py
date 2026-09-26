#!/usr/bin/env python3
"""Beat-synced edit of Moving Image Archive shots to a music track.

Pipeline
  1. Beat-track the song; measure per-bar loudness and label bars low / mid / high.
  2. Turn bars into cut slots: long cuts in quiet bars, one cut per beat in loud
     bars, half-beat stutters on the loudest bars, and white flash frames on the
     hardest downbeats.
  3. Build a shot pool from clips_full.json (the archive's own shot boundaries)
     joined with analysis/*.npz (motion, brightness, contrast per shot).
  4. Assign shots to slots: fast shots for loud bars, calm shots (often in
     slow motion) for quiet bars, no shot reused, sources rotated, with short
     A/B "motif" runs in the loud sections.
  5. Render each slot frame-exactly with ffmpeg (cover-crop to 16:9, 24 fps),
     concatenate, add grain/vignette/fades, mux the song, append a credits card.

usage: build_edit.py --audio audio/cut_and_run.mp3 --out out/cut_and_run.mp4 [--seed 7] [--jobs 4]
"""
import argparse, json, os, random, subprocess, sys, glob, math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
FPS = 24
W, H = 1920, 1080
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
FONT_REG = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


# ---------------------------------------------------------------- music
def analyse_music(path):
    import librosa, warnings; warnings.filterwarnings('ignore')
    y, sr = librosa.load(path, sr=22050, mono=True)
    dur = len(y) / sr
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units='time', trim=False)
    tempo = float(np.atleast_1d(tempo)[0])
    period = 60.0 / tempo
    # extend the beat grid to cover the whole track at the estimated period
    beats = list(beats)
    while beats[-1] + period < dur: beats.append(beats[-1] + period)
    while beats[0] - period > 0: beats.insert(0, beats[0] - period)
    beats = np.array(beats)
    onset = librosa.onset.onset_strength(y=y, sr=sr)
    ot = librosa.frames_to_time(np.arange(len(onset)), sr=sr)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rt = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)
    # choose the downbeat phase: the beat phase (0..3) with the strongest onsets
    best = max(range(4), key=lambda p: sum(np.interp(b, ot, onset) for b in beats[p::4]))
    bars = beats[best::4]
    if best > 0: bars = np.concatenate([[beats[0]], bars]) if beats[0] < bars[0] - period * 0.5 else bars
    bar_e = np.array([rms[(rt >= a) & (rt < b)].mean() if ((rt >= a) & (rt < b)).any() else 0 for a, b in zip(bars[:-1], bars[1:])])
    bar_o = np.array([onset[(ot >= a) & (ot < b)].mean() if ((ot >= a) & (ot < b)).any() else 0 for a, b in zip(bars[:-1], bars[1:])])
    bar_e = bar_e / bar_e.max(); bar_o = bar_o / bar_o.max()
    beat_on = np.array([np.interp(b, ot, onset) for b in beats])
    return dict(dur=dur, tempo=tempo, period=period, beats=beats, bars=bars, bar_energy=0.6 * bar_e + 0.4 * bar_o, beat_onset=beat_on)


def label_bars(e):
    """low / mid / high per bar: percentile rank of smoothed loudness+onset density,
    with the bars right after a quiet run promoted to high (the drop)."""
    s = np.convolve(e, [0.25, 0.5, 0.25], mode='same')
    lo, hi = np.percentile(s, 15), np.percentile(s, 58)
    lab = ['low' if v < lo else 'mid' if v < hi else 'high' for v in s]
    # first two bars of the song stay calm; a drop after a quiet run is always high
    for k in range(len(lab)):
        if k >= 2 and lab[k - 1] == 'low' and lab[k] != 'low':
            for j in range(k, min(len(lab), k + 8)):
                if lab[j] == 'low': break
                lab[j] = 'high'
    lab[0] = 'low'
    return lab


# ---------------------------------------------------------------- slots
def make_slots(m, rng):
    beats, bars, labels = m['beats'], m['bars'], label_bars(m['bar_energy'])
    beat_on = m['beat_onset']
    on_hi = np.percentile(beat_on, 88)
    slots = []  # dict(t0, t1, level, flash, stutter)
    period = m['period']
    bi = 0
    run = 0; prev = None
    nbars = len(bars) - 1
    for k in range(nbars):
        lvl = labels[k]
        run = run + 1 if lvl == prev else 0
        prev = lvl
        b0 = bars[k]; b1 = bars[k + 1]
        bl = (b1 - b0) / 4
        # sub-beat grid for this bar
        if lvl == 'low':
            # 2-bar and 1-bar holds, slow motion later
            if slots and slots[-1]['level'] == 'low' and slots[-1].get('extend', False) is False and rng.random() < 0.45:
                slots[-1]['t1'] = b1; slots[-1]['extend'] = True; continue
            slots.append(dict(t0=b0, t1=b1, level='low', flash=False, speed=rng.choice([0.5, 0.5, 0.75, 1.0]), extend=False))
        elif lvl == 'mid':
            # ramp: early bars of a mid run cut every 4 beats, later every 2, occasionally every 1
            if run < 2 and rng.random() < 0.6:
                pat = [4]
            elif rng.random() < 0.18:
                pat = [1, 1, 2]
            else:
                pat = rng.choice([[2, 2], [2, 2], [2, 1, 1], [1, 1, 2]])
            t = b0
            for n in pat:
                slots.append(dict(t0=t, t1=t + n * bl, level='mid', flash=False, speed=1.0))
                t += n * bl
        else:  # high
            r = rng.random()
            if r < 0.12:
                pat = [0.5] * 8               # stutter bar
            elif r < 0.26:
                pat = [1, 0.5, 0.5, 1, 1]     # syncopated (sums to 4 beats)
            elif r < 0.42:
                pat = rng.choice([[2, 1, 1], [1, 1, 2]])
            elif r < 0.60:
                pat = [2, 2]                  # breathe
            else:
                pat = [1, 1, 1, 1]
            t = b0
            for i, n in enumerate(pat):
                beat_idx = int(np.argmin(np.abs(beats - t)))
                flash = abs(beats[beat_idx] - t) < 0.02 and beat_on[beat_idx] >= on_hi and (i == 0 or rng.random() < 0.35)
                slots.append(dict(t0=t, t1=t + n * bl, level='high', flash=bool(flash), speed=1.0 if rng.random() < 0.8 else 1.5))
                t += n * bl
    # trim to song length and give the last slot the remaining audio
    slots = [s for s in slots if s['t0'] < m['dur'] - 0.2]
    slots[-1]['t1'] = min(slots[-1]['t1'], m['dur'])
    for s in slots:
        s.pop('extend', None)
        s['f0'] = int(round(s['t0'] * FPS)); s['f1'] = int(round(s['t1'] * FPS))
    slots = [s for s in slots if s['f1'] > s['f0']]
    for a, b in zip(slots, slots[1:]):
        assert a['f1'] == b['f0'], f"slot gap/overlap at {a['t1']:.2f}s: {a['f1']} vs {b['f0']}"
    return slots


# ---------------------------------------------------------------- pool
def load_pool():
    clips = json.load(open(os.path.join(ROOT, 'clips_full.json')))
    srcs = json.load(open(os.path.join(ROOT, 'sources.json')))
    files = {os.path.basename(p).split('__')[0]: p for p in glob.glob(os.path.join(ROOT, 'sources', '*')) if not p.endswith(('.log', '.part', '.txt'))}
    pool = []
    for slug, shots in clips.items():
        ia = (srcs.get(slug) or {}).get('ia') or []
        if not ia or ia[0] not in files: continue
        npz = os.path.join(ROOT, 'analysis', ia[0] + '.npz')
        if not os.path.exists(npz): continue
        a = np.load(npz); mo, lu, co, fps = a['motion'], a['luma'], a['contrast'], float(a['fps'])
        for sh in shots:
            t0, t1 = float(sh['startSeconds']), float(sh['endSeconds'])
            d = t1 - t0
            if d < 0.55: continue
            i0, i1 = int((t0 + 0.12) * fps), int((t1 - 0.12) * fps)
            if i1 - i0 < 2 or i1 > len(mo): continue
            seg_m, seg_l, seg_c = mo[i0 + 1:i1], lu[i0:i1], co[i0:i1]
            if len(seg_m) == 0: continue
            luma = float(seg_l.mean()); contrast = float(seg_c.mean())
            if luma < 22 or luma > 228 or contrast < 10: continue   # blank / burnt / featureless
            pool.append(dict(slug=slug, ia=ia[0], file=files[ia[0]], id=sh['id'], t0=t0, t1=t1, dur=d,
                             motion=float(np.percentile(seg_m, 70)), luma=luma, contrast=contrast,
                             color=sh.get('colorMode') or 'unknown', year=srcs[slug].get('year'), title=srcs[slug]['title']))
    mots = np.array([p['motion'] for p in pool])
    order = mots.argsort().argsort()
    for p, r in zip(pool, order): p['mrank'] = r / max(1, len(pool) - 1)
    return pool


# ---------------------------------------------------------------- assignment
def assign(slots, pool, rng):
    by_src = {}
    for p in pool: by_src.setdefault(p['slug'], []).append(p)
    used = set(); recent = []
    motif = None  # (sources, remaining)
    edl = []

    def candidates(slot, need, lo, hi, avoid):
        c = [p for p in pool if p['id'] not in used and p['dur'] >= need and lo <= p['mrank'] <= hi and p['slug'] not in avoid]
        if len(c) < 8:
            c = [p for p in pool if p['id'] not in used and p['dur'] >= need and p['slug'] not in avoid]
        if len(c) < 4:
            c = [p for p in pool if p['id'] not in used and p['dur'] >= need]
        return c

    for i, s in enumerate(slots):
        span = s['t1'] - s['t0']
        need = span * s['speed'] + 0.1
        lvl = s['level']
        lo, hi = {'low': (0.0, 0.55), 'mid': (0.35, 0.9), 'high': (0.6, 1.0)}[lvl]
        avoid = set(recent[-4:])
        pick = None
        if lvl == 'high':
            if motif and motif[1] > 0:
                srcs, left = motif
                slug = srcs[i % len(srcs)]
                c = [p for p in by_src.get(slug, []) if p['id'] not in used and p['dur'] >= need and p['mrank'] >= 0.45]
                if c: pick = rng.choice(c); motif = (srcs, left - 1)
                else: motif = None
            elif rng.random() < 0.22:
                # start a motif: two sources with plenty of fast shots left
                rich = [k for k, v in by_src.items() if sum(1 for p in v if p['id'] not in used and p['mrank'] >= 0.55 and p['dur'] >= 0.6) >= 6]
                if len(rich) >= 2:
                    srcs = rng.sample(rich, 2); motif = (srcs, rng.choice([4, 6, 8]))
        if pick is None:
            c = candidates(s, need, lo, hi, avoid)
            if not c: raise SystemExit(f'pool exhausted at slot {i}')
            # weight towards the target band centre, and towards higher motion in loud bars
            w = np.array([1.0 + (p['mrank'] if lvl == 'high' else (1 - abs(p['mrank'] - (lo + hi) / 2))) for p in c])
            pick = c[rng.choices(range(len(c)), weights=w)[0]]
        used.add(pick['id']); recent.append(pick['slug'])
        slack = pick['dur'] - need
        off = rng.uniform(0, min(slack, 0.6)) if slack > 0 else 0.0
        edl.append(dict(slot=i, f0=s['f0'], f1=s['f1'], frames=s['f1'] - s['f0'], level=lvl, flash=s['flash'], speed=s['speed'],
                        file=pick['file'], src_t0=pick['t0'] + off, slug=pick['slug'], clip=pick['id'], title=pick['title'], year=pick['year'],
                        motion=round(pick['mrank'], 3)))
    return edl


# ---------------------------------------------------------------- render
def render_slot(e, workdir):
    out = os.path.join(workdir, f"s{e['slot']:04d}.ts")
    if os.path.exists(out): return out
    n = e['frames']
    vf = [f'scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos', f'crop={W}:{H}', 'setsar=1']
    if e['speed'] != 1.0:
        vf.insert(0, f"setpts=PTS/{e['speed']}")
    vf.append(f'fps={FPS}')
    if e['flash']:
        vf.append("drawbox=c=white@0.9:t=fill:enable='lt(n,2)'")
    # tiny punch-in on every third high slot for extra energy
    if e['level'] == 'high' and e['slot'] % 3 == 0:
        vf.append(f'scale={int(W*1.06)}:{int(H*1.06)},crop={W}:{H}')
    src_dur = n / FPS * e['speed'] + 0.6

    def run(extra_vf):
        cmd = ['ffmpeg', '-v', 'error', '-y', '-ss', f"{e['src_t0']:.3f}", '-t', f'{src_dur:.3f}', '-i', e['file'],
               '-vf', ','.join(vf + extra_vf), '-frames:v', str(n), '-an', '-c:v', 'libx264', '-preset', 'veryfast',
               '-crf', '15', '-pix_fmt', 'yuv420p', '-f', 'mpegts', out]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(out):
            raise RuntimeError(f"slot {e['slot']} failed: {r.stderr[-400:]}")
        p = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v', '-show_entries',
                            'stream=nb_read_frames', '-of', 'csv=p=0', out], capture_output=True, text=True)
        return int((p.stdout.split() or ['0'])[0])

    got = run([])
    if got != n:
        # the source ran out (shot shorter than its metadata): hold the last frame
        os.remove(out)
        got = run([f'tpad=stop_mode=clone:stop_duration={(n - got + 4) / FPS:.3f}'])
        if got != n:
            raise RuntimeError(f"slot {e['slot']}: wanted {n} frames, got {got}")
    return out


def credits_card(path, lines, seconds):
    if os.path.exists(path): return path
    dt = []
    y = 300
    for text, size, bold in lines:
        safe = text.replace("'", r"\'").replace(':', r'\:')
        dt.append(f"drawtext=fontfile={FONT if bold else FONT_REG}:text='{safe}':fontsize={size}:fontcolor=white:x=(w-text_w)/2:y={y}")
        y += int(size * 1.7)
    vf = ','.join(dt) + f',fade=t=in:st=0:d=0.8,fade=t=out:st={seconds-1.2}:d=1.2,fps={FPS}'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=black:s={W}x{H}:r={FPS}:d={seconds}',
                    '-vf', vf, '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '15', '-pix_fmt', 'yuv420p', '-f', 'mpegts', path], check=True)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--audio', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--seed', type=int, default=7); ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--title', default='CUT AND RUN')
    a = ap.parse_args()
    rng = random.Random(a.seed)
    m = analyse_music(a.audio)
    print(f"tempo {m['tempo']:.1f} bpm, {len(m['bars'])-1} bars, {m['dur']:.1f}s")
    slots = make_slots(m, rng)
    pool = load_pool()
    print(f'{len(slots)} slots, pool of {len(pool)} shots from {len({p["slug"] for p in pool})} films')
    edl = assign(slots, pool, rng)
    workdir = os.path.join(ROOT, 'out', 'work_' + os.path.splitext(os.path.basename(a.out))[0]); os.makedirs(workdir, exist_ok=True)
    json.dump(dict(audio=a.audio, tempo=m['tempo'], seed=a.seed, slots=edl), open(os.path.join(ROOT, 'out', os.path.splitext(os.path.basename(a.out))[0] + '.edl.json'), 'w'), indent=1)
    from concurrent.futures import ThreadPoolExecutor
    parts = [None] * len(edl)
    with ThreadPoolExecutor(a.jobs) as ex:
        for i, p in enumerate(ex.map(lambda e: render_slot(e, workdir), edl)):
            parts[i] = p
            if i % 25 == 0: print(f'rendered {i}/{len(edl)}', flush=True)
    total_frames = sum(e['frames'] for e in edl)
    films = sorted({(e['title'], e['year']) for e in edl}, key=lambda t: (t[1] or 0, t[0]))
    years = [e['year'] for e in edl if e['year']]
    card = credits_card(os.path.join(workdir, 'credits.ts'), [
        (a.title, 96, True),
        (f'{len(edl)} shots from {len(films)} public-domain films, {min(years)}-{max(years)}', 40, False),
        ('Footage: Prelinger Archives, U.S. National Archives, Internet Archive', 34, False),
        ('via movingimagearchive.com', 34, False),
        ('Music: "Cut and Run" by Kevin MacLeod (incompetech.com)', 34, False),
        ('Licensed under Creative Commons: By Attribution 4.0', 34, False),
    ], 7.0)
    lst = os.path.join(workdir, 'concat.txt')
    with open(lst, 'w') as f:
        for p in parts: f.write(f"file '{os.path.abspath(p)}'\n")
        f.write(f"file '{os.path.abspath(card)}'\n")
    vid_len = total_frames / FPS
    title_safe = a.title.replace("'", r"\'")
    final_vf = (f"noise=alls=6:allf=t+u,vignette=PI/5,eq=contrast=1.06:saturation=1.05,"
                f"drawtext=fontfile={FONT}:text='{title_safe}':fontsize=110:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:"
                f"enable='between(t,0.6,{m['bars'][2]:.2f})':alpha='if(lt(t,1.0),(t-0.6)/0.4,1)',"
                f"fade=t=in:st=0:d=0.6,fade=t=out:st={vid_len-1.5:.2f}:d=1.5")
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-i', a.audio,
           '-filter_complex', f"[0:v]{final_vf}[v];[1:a]apad=pad_dur=7,afade=t=out:st={vid_len-1.2:.2f}:d=1.2[a]",
           '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-maxrate', '14M', '-bufsize', '28M', '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-shortest', a.out]
    subprocess.run(cmd, check=True)
    print('wrote', a.out, f'{vid_len:.1f}s of picture + 7s credits;', len(edl), 'cuts')


if __name__ == '__main__':
    main()
