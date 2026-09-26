# Archive edit

Beat-synced edits cut from public-domain shots in the
[Moving Image Archive](https://www.movingimagearchive.com/).

| Edit | Song | Seed | Files |
|---|---|---|---|
| Cut and Run | "Cut and Run" by Kevin MacLeod | 11 | `out/cut_and_run*.mp4` |
| Hitman | "Hitman" by Kevin MacLeod | 23 | `out/hitman*.mp4` |

Each edit has a 1080p master, a 720p copy and a compact 720p copy. The
renders and songs are stored with Git LFS.

## What is in here

| Path | What it is |
|---|---|
| `tools/ia_get.py` | Downloads the best video file of an Internet Archive item through `archive.org/cors/`, which serves the bytes without redirecting to a per-item mirror host. |
| `tools/batch_get.py` | Runs `ia_get.py` for a list of Moving Image Archive source slugs, four at a time. |
| `tools/source_clips.py` | Fetches every shot (start and end seconds) for a source from its page on movingimagearchive.com and records the film's Internet Archive identifier and rights. Writes `clips_full.json` and `sources.json`. |
| `tools/analyze_motion.py` | Decodes each film once at 96x72 grey, 8 fps, and stores per-frame motion, brightness and contrast in `analysis/`. |
| `tools/build_edit.py` | Beat-tracks the song, turns bars into cut slots, assigns shots, renders frame-exact segments with ffmpeg, concatenates, grades and muxes. Writes the edit and an edit decision list next to it. |
| `tools/run_batch.sh` | Scrape, download, analyse for one slug list. |
| `batch1.txt` … | The source slugs used. |
| `clips_full.json` | Shot boundaries for every film pulled, as published by the archive. |
| `sources.json` | Per-film metadata: title, year, Internet Archive identifier, collection, rights. |
| `out/*.edl.json` | For each rendered edit, one row per cut: song frame range, source film, source timestamp, speed, flash. |

The source films (`sources/`) and the motion analysis (`analysis/`) are not
committed. The songs used and the rendered edits are, through Git LFS.

## How the archive is wired

The site is a Next.js front end over Internet Archive films. Its clip
files live on a Cloudflare R2 bucket. Each source page embeds the full shot
list in its server payload, and links the film's `archive.org/details/`
page. The public JSON at `/api/clips` and `/api/sources` lists clips and
sources with `limit` and `offset`, but only the first ten thousand clips
are reachable there, so the shot lists come from the source pages.

## How the cut works

1. `librosa` beat-tracks the song and picks the downbeat phase with the
   strongest onsets.
2. Each bar gets a level from the percentile rank of its loudness and onset
   density: low, mid or high. The eight bars after a quiet run are forced
   high, which is where the drops land.
3. Low bars hold one shot for one or two bars, often in slow motion. Mid
   bars cut every two beats, sometimes every four or every one. High bars
   cut on every beat, with some two-beat holds, syncopated bars, half-beat
   stutter bars, and a two-frame white flash on the hardest downbeats.
4. Shots are ranked by motion. Loud slots draw from the fastest shots,
   quiet slots from the calmest. No shot is reused, the same film is not
   used twice within four cuts, and in loud sections the cut sometimes
   alternates between two films for four to eight beats.
5. Every slot is rendered to exactly the number of frames its beat span
   covers at 24 fps, so the picture never drifts from the song.

## Reproduce

```sh
pip install librosa numpy yt-dlp
apt-get install ffmpeg
sh tools/run_batch.sh batch1.txt   # and batch2.txt, batch3.txt
curl -o audio/cut_and_run.mp3 "https://archive.org/cors/KevinMacLeod_2019-04_Discography/Kevin%20MacLeod/Hard%20Electronic/Kevin%20MacLeod%20-%2005%20-%20Cut%20and%20Run.mp3"
python3 tools/build_edit.py --audio audio/cut_and_run.mp3 --out out/cut_and_run.mp4 --seed 11
curl -o audio/hitman.mp3 "https://archive.org/cors/KevinMacLeod_2019-04_Discography/Kevin%20MacLeod/Action%20Cuts/Kevin%20MacLeod%20-%2013%20-%20Hitman.mp3"
python3 tools/build_edit.py --audio audio/hitman.mp3 --out out/hitman.mp4 --seed 23 \
  --title HITMAN --music '"Hitman" by Kevin MacLeod (incompetech.com)'
```

`--seed` changes the cut and the shot choice. `--title` sets the opening
title and `--music` the song credit on the closing card.

## Credits

Footage: Prelinger Archives, U.S. National Archives and other Internet
Archive collections, all marked public domain by the archive, found through
movingimagearchive.com.

Music: "Cut and Run" and "Hitman" by Kevin MacLeod (incompetech.com),
licensed under Creative Commons: By Attribution 4.0,
https://creativecommons.org/licenses/by/4.0/
