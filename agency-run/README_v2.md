# Agency run 2

Read `PREREGISTRATION_v2.md` first. Run 1 files (`PREREGISTRATION.md`, `run.py`, `analyze.py`, `pilot/`, `results/`) are unchanged.

- Unit test of the guard: `python3 -m unittest tests.test_guard -v`
- Full run: `./quiet_run.sh` (load probes, v2 pilot and its commit, idle baselines, main run in a powermetrics window, analysis). Needs `sudo -n /usr/bin/powermetrics` without a password.
- Outputs: `pilot2/locked.json`, `pilot2/pilot_rows.jsonl`, `results2/episodes.jsonl`, `results2/runs.json`, `results2/crosscheck.json`, `results2/load_probe.jsonl`, `results2/load_ps.jsonl`, `results2/summary.{json,md}`, powermetrics plists.

All joules are `reported_j` (kernel per-process energy model, or powermetrics). `est_j` is the cycle model. `measured_j` is empty: no wall meter.
