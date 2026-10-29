#!/usr/bin/env bash
# The registered run (PREREG.json). Usage:
#   run.sh RCE_TREE RCE RCE_BEFORE WORK [PYTHON]
# RCE_TREE: a checkout of openIE-dev/rce at the run commit; RCE: rce built
# from it; RCE_BEFORE: rce built from the base commit (main before the
# change); WORK: a scratch directory; PYTHON: a python3 with fastapi and
# httpx (default python3). Writes results/.
set -u
TREE=$(cd "$1" && pwd); RCE=$2; BEFORE=$3; WORK=$4; PY=${5:-python3}
HERE=$(cd "$(dirname "$0")" && pwd); R=$HERE/results
mkdir -p "$R" "$WORK"
{ echo "date: $(date -u +%FT%TZ)"; echo "rce tree: $(git -C "$TREE" rev-parse HEAD)"; echo "rce: $("$RCE" --version | head -1)";
  echo "cpu: $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ //') x $(nproc)"; uname -sr;
  echo "python: $("$PY" --version)"; echo "node: $(node --version)"; echo "rustc: $(rustc --version)"; } > "$R/machine.txt"
# M4: every embedding, after the change and before it
RCE=$RCE INTEROP_OUT=$WORK/after "$PY" "$TREE/examples/interop/check.py" > "$R/check-after.txt" 2>&1; echo "exit $?" >> "$R/check-after.txt"
: > "$R/check-before.txt"
for l in python fastapi numpy rust js react browser; do
  echo "== $l" >> "$R/check-before.txt"
  RCE=$BEFORE INTEROP_OUT=$WORK/before "$PY" "$TREE/examples/interop/check.py" $l > "$WORK/before-$l.txt" 2>&1; echo "exit $?" >> "$WORK/before-$l.txt"
  # the summary line and the first failure of each embedding
  grep -E "^(FAIL|[a-z-]+: |cargo build|exit )" "$WORK/before-$l.txt" | head -3 >> "$R/check-before.txt"
  grep -m3 -E "error\[E[0-9]+\]|TypeError|ReferenceError|SyntaxError" "$WORK/before-$l.txt" >> "$R/check-before.txt"
done
# M1, M2
python3 "$HERE/count.py" "$TREE" "$WORK/after" > "$R/loc.json"
# M3
S=$WORK/after/streams
"$PY" "$HERE/bench_py.py" "$TREE" "$WORK/after" "$S" 300 5 > "$R/bench-python.json"
node "$HERE/bench_js.mjs" "$TREE" "$WORK/after" "$S" 3000 5 > "$R/bench-js.json"
python3 "$HERE/bench_rust.py" "$WORK/after/rust-target/release/rce-interop" "$WORK/after/hand-rust-target/release/rce-interop-hand" "$S" 20000 5 > "$R/bench-rust.json"
python3 "$HERE/summarize.py" "$R" > "$R/summary.md"
