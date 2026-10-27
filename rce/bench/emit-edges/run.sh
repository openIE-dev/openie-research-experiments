#!/usr/bin/env bash
# Track T4 (emit-edges): one command from a clean clone of openIE-dev/rce at
# the registered run commit to the summary digest.
#
#   rce/bench/emit-edges/run.sh [OUT_DIR]
#
# Fetches the run commit of PREREG.json into a new temporary directory,
# runs `cargo test --release --test emit_edges` there with
# RCE_EMIT_EDGES_OUT set, and writes the record to OUT_DIR (default
# results/ next to this script): test.log, examples.jsonl, module.rce,
# targets.jsonl, summary.json and summary.json.sha256. It prints the
# summary digest, which equals the one recorded in results/ on a host where
# the same targets run (rustc with wasm32-wasip1, python3, node; no
# scala-cli). CARGO_TARGET_DIR and CARGO_BUILD_JOBS are passed through.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
out="$(mkdir -p "${1:-$here/results}" && cd "${1:-$here/results}" && pwd)"
commit="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_commit"]["commit"])' "$here/PREREG.json")"
(cd "$here" && sha256sum -c PREREG.json.sha256 >/dev/null) || { echo "PREREG.json does not match its sidecar" >&2; exit 2; }
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git init -q "$work/rce"
git -C "$work/rce" fetch -q --depth 1 https://github.com/openIE-dev/rce "$commit"
git -C "$work/rce" checkout -q FETCH_HEAD
test "$(git -C "$work/rce" rev-parse HEAD)" = "$commit"
raw="$work/raw"
status=0
(cd "$work/rce/spec/checker" && RCE_EMIT_EDGES_OUT="$raw" cargo test --release --test emit_edges -- --test-threads 2 --nocapture) >"$out/test.log" 2>&1 || status=$?
echo "cargo test exit $status" >>"$out/test.log"
python3 "$here/summarize.py" "$raw" "$out" "$commit"
exit "$status"
