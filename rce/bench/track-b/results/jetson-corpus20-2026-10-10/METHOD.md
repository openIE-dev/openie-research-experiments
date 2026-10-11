# Track B on jetson-hub, corpus20 2026-10-10

Host: jetson-hub, Ubuntu, Intel i9-13900H. Forgejo CI runners stayed up and busy.
Command: `rce bench track-b bench/track-a/corpus20.prereg.json --meter rapl-idle:10`, see run_b.sh.
Pinning: the benchmark and the model server ran on CPUs 2-5 under taskset. The server ran with 4 threads.
Meter: RAPL package-0 (`intel-rapl:0/energy_uj`). Before each run the meter samples the package for 10 s with nothing of ours running and takes that as idle power. reported_j is the run's counter delta less idle power times the run's duration.
The package counter covers the whole chip. The CI load moved the idle sample between 24.8 W and 54.8 W, so each figure carries that load.
Sandbox: this host forbids unprivileged user namespaces. shim/unshare gets the network namespace from sudo and drops back to the user.
Solver: the 2026-10-10 solver (commit 01f4c4d). Model: Qwen2.5-Coder-1.5B Q4, sha256 cc324af0.
These are reported_j figures. measured_j is kept for a wall meter. Per-run logs and diffs are in out/.

| solver | solved | raw J | reported_j | reported_j per solved | seconds |
|---|---|---|---|---|---|
| RCE solver | 11 / 20 | 33950.6 | 7836.1 | 712.4 | 695 |
| gold | 20 / 20 | 277.2 | 58.1 | 2.9 | 5 |
| none | 0 / 20 | 219.6 | 51.3 | none solved | 5 |
