#!/bin/sh
# render the final edit and a 720p copy
cd "$(dirname "$0")/.." || exit 1
python3 tools/build_edit.py --audio audio/cut_and_run.mp3 --out out/cut_and_run.mp4 --seed 11 --jobs 4 && \
ffmpeg -v error -y -i out/cut_and_run.mp4 -vf scale=1280:720 -c:v libx264 -preset medium -crf 22 -c:a copy -movflags +faststart out/cut_and_run_720p.mp4 && echo FINAL_DONE
