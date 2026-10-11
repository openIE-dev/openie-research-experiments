#!/bin/sh
# Track B on jetson-hub: CPUs 2-5 (two P-cores, both threads) carry the
# model server and the benchmark; RAPL package-0 less an idle baseline.
set -e
cd ~/rce-bench
export PATH=$HOME/rce-bench/shim:$HOME/.cargo/bin:$PATH RCE_ROOT=$HOME/rce-bench RCE_LOCAL_LLM_URL=http://127.0.0.1:8091
cd llama-b11541 && LD_LIBRARY_PATH=. taskset -c 2-5 ./llama-server -m ../qwen-coder-1.5b-q4.gguf --port 8091 -t 4 -c 4096 > ../server.log 2>&1 &
SRV=$!
until curl -sf 127.0.0.1:8091/health >/dev/null; do sleep 1; done
rm -rf out2
taskset -c 2-5 ./rce bench track-b bench/track-a/corpus20-2026-10-11b.prereg.json --out out2 --meter rapl-idle:10 > run2.log 2>&1 || echo RUN_FAIL >> run2.log
kill $SRV
echo DONE >> run2.log
