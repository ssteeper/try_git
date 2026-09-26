#!/bin/sh
cd "$(dirname "$0")/.." || exit 1
while pgrep -f run_batch.sh >/dev/null; do sleep 10; done
echo "analysis done: $(ls analysis | wc -l) films" 
python3 tools/build_edit.py --audio audio/cut_and_run.mp3 --out out/cut_and_run.mp4 --seed 11 --jobs 4 && \
ffmpeg -v error -y -i out/cut_and_run.mp4 -vf scale=1280:720 -c:v libx264 -preset medium -crf 22 -c:a copy -movflags +faststart out/cut_and_run_720p.mp4 && echo FINAL_DONE
