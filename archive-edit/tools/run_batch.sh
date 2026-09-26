#!/bin/sh
# scrape shot lists + identifiers, download the films, analyse motion — for one slug list
cd "$(dirname "$0")/.." || exit 1
python3 tools/source_clips.py < "$1" && python3 tools/batch_get.py < "$1" && \
for f in sources/*; do case "$f" in *.log|*.part) ;; *) python3 tools/analyze_motion.py "$f";; esac; done
