#!/bin/bash
# v2 orchestrator. Polls for a quiet window, then runs pilot2 and main2 in it.
# Quiet: package CPU <= 5 W, GPU <= 3 W, other processes' total %CPU <= 200.
# Probes every 180 s, at most MAXP probes (60 = about 3 hours), then runs
# anyway and records quiet_window=no. Never stops or pauses another process.
set -u
cd "$(dirname "$0")"
export PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
MAXP=${MAXP:-60}
REPO=$(git rev-parse --show-toplevel)
mkdir -p results2 pilot2
QUIET=no
for i in $(seq 1 "$MAXP"); do
  if python3 run2.py probe >> results2/load_probe.jsonl; then QUIET=yes; break; fi
  echo "probe $i not quiet $(date '+%H:%M:%S')"
  [ "$i" -lt "$MAXP" ] && sleep 180
done
echo "QUIET=$QUIET start $(date '+%Y-%m-%d %H:%M:%S')"
python3 run2.py pilot2 > results2/pilot2.log 2>&1 || { echo PILOT_FAILED; exit 1; }
git -C "$REPO" add experiments/agency-run/pilot2
git -C "$REPO" commit -q -m "agency-run v2: pilot output, locked calibration, refusal quantile and guard sizes (before main run)" -- experiments/agency-run/pilot2
echo "PILOT_COMMIT $(git -C "$REPO" rev-parse --short HEAD)"
python3 run2.py main2 "$QUIET" > results2/main.log 2>&1 || { echo MAIN_FAILED; exit 1; }
python3 analyze2.py > results2/analyze.log 2>&1 || { echo ANALYZE_FAILED; exit 1; }
echo "DONE QUIET=$QUIET $(date '+%Y-%m-%d %H:%M:%S')"
