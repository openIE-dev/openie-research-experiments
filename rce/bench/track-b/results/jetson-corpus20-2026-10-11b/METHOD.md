# Track B on jetson-hub, corpus20 2026-10-11b

Host: jetson-hub, Ubuntu, Intel i9-13900H. Forgejo CI runners stayed up and busy.
Command: `rce bench track-b bench/track-a/corpus20-2026-10-11b.prereg.json --meter rapl-idle:10`, see run_b2.sh.
Pinning: the benchmark and the model server ran on CPUs 2-5 under taskset. The server ran with 4 threads.
Meter: RAPL package-0. Before each run the meter samples the package for 10 s with nothing of ours running and takes that as idle power. reported_j is the run's counter delta less idle power times the run's duration.
The counter covers the whole chip. The CI load moved the idle sample between 25.7 W and 57.8 W.
Solver: commit 40a4434. Model: Qwen2.5-Coder-1.5B Q4, sha256 cc324af0. No task reached it.
These are reported_j figures. measured_j is kept for a wall meter. Per-run logs and diffs are in out/.

| solver | solved | raw J | reported_j | reported_j per solved | seconds |
|---|---|---|---|---|---|
| RCE solver | 20 / 20 | 7613.0 | 1684.0 | 84.2 | 154 |
| gold | 20 / 20 | 254.3 | 39.2 | 2.0 | 5 |
| none | 0 / 20 | 253.3 | 14.6 | none solved | 5 |

Against the 2026-10-10 run (11 solved at 712.4 reported_j per solved task) the solver resolves 20 tasks at 84.2.
