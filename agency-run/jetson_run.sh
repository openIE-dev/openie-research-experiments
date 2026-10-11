#!/bin/bash
# v2 on jetson-hub (PREREGISTRATION_v2_jetson.md). Run as root: sudo -n bash jetson_run.sh
# 1 save frequency settings, pin (turbo off, min = max = base on every CPU), trap restores on exit
# 2 load sampler as its own process on CPU 19; probes for a quiet window (others <= 0.5 cores),
#   every 90 s, at most MAXP probes, then runs anyway with quiet_window=no
# 3 part A (RAPL per read): pilot on CPU 4; waits for pilot_jetson/COMMITTED (written after the pilot is
#   committed in git); main run on CPU 4; analysis
# 4 part B (amendment 1, RAPL-calibrated cycle meter): same, pilot_jetson_cyc/, results_jetson_cyc/
# 5 frequency restored; files chowned to dcharlot
# Never stops, pauses or renices another process.
set -u
cd "$(dirname "$0")"
OWNER=${OWNER:-dcharlot}
MAXP=${MAXP:-40}
mkdir -p results_jetson pilot_jetson
[ -f results_jetson/freq_orig.json ] || python3 run2_jetson.py freqsave results_jetson/freq_orig.json
restore() {
  python3 run2_jetson.py freqrestore results_jetson/freq_orig.json > results_jetson/freq_restored.json
  touch results_jetson/STOP_PS; sleep 1; kill "${PSPID:-0}" 2>/dev/null
  chown -R "$OWNER": results_jetson pilot_jetson results_jetson_cyc pilot_jetson_cyc 2>/dev/null
  echo "RESTORED $(date '+%H:%M:%S')"
}
trap restore EXIT
python3 run2_jetson.py freqpin > results_jetson/freq_pinned.json
echo "PINNED $(date '+%H:%M:%S')"
rm -f results_jetson/STOP_PS
taskset -c 19 python3 run2_jetson.py ps & PSPID=$!
QUIET=no
for i in $(seq 1 "$MAXP"); do
  if taskset -c 18 python3 run2_jetson.py probe >> results_jetson/load_probe.jsonl; then QUIET=yes; break; fi
  echo "probe $i not quiet $(date '+%H:%M:%S')"
  [ "$i" -lt "$MAXP" ] && sleep 90
done
echo "QUIET=$QUIET start $(date '+%Y-%m-%d %H:%M:%S')"
echo "$QUIET" > results_jetson/quiet_window.txt
run_part() {  # $1 = A or B, $2 = pilot dir, $3 = results dir
  export JETSON_PART=$1; mkdir -p "$3" "$2"
  if [ ! -f "$2/locked.json" ]; then
    taskset -c 4 python3 run2_jetson.py pilot > "$3/pilot.log" 2>&1 || { echo "PILOT_FAILED $1"; return 1; }
  fi
  chown -R "$OWNER": "$2" "$3"
  echo "PILOT_DONE $1 $(date '+%H:%M:%S')"
  for i in $(seq 1 180); do [ -f "$2/COMMITTED" ] && break; sleep 10; done
  [ -f "$2/COMMITTED" ] || { echo "NO_PILOT_COMMIT $1"; return 1; }
  echo "PILOT_COMMIT $1 $(cat "$2/COMMITTED")"
  if [ ! -f "$3/env_main.json" ]; then
    taskset -c 4 python3 run2_jetson.py main "$QUIET" > "$3/main.log" 2>&1 || { echo "MAIN_FAILED $1"; return 1; }
  fi
  echo "MAIN_DONE $1 $(date '+%H:%M:%S')"
  taskset -c 19 python3 analyze2_jetson.py > "$3/analyze.log" 2>&1 || echo "ANALYZE_FAILED $1"
  chown -R "$OWNER": "$2" "$3"
}
run_part A pilot_jetson results_jetson || exit 1
run_part B pilot_jetson_cyc results_jetson_cyc || exit 1
echo "DONE QUIET=$QUIET $(date '+%Y-%m-%d %H:%M:%S')"
