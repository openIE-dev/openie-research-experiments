# Agency run 2, second fabric (jetson-hub): preregistration addendum

Committed before any jetson pilot and before the jetson main run. It adds a second machine and meter to `PREREGISTRATION_v2.md` (commit 610dd4c). Everything not named here is as in `PREREGISTRATION_v2.md` and, through it, `PREREGISTRATION.md`. The Mac v2 run is separate and unaffected; its files (`results2/`, `pilot2/`) are not touched. Nothing below changes after this commit.

## Why

An external review asked for the v2 comparison on a second compute fabric with an energy counter on an idle, frequency-pinned Linux machine. Run 1 and the Mac v2 run use the macOS per-process kernel energy model; this run uses Intel RAPL.

## Unchanged

- Task sets: `tasks/calib.json` and `tasks/test.json` (30 test puzzles), the completeness predicate, coupled bits, gears g0 g1 g2.
- Arms: sigma-law, Mixture of Limits, goal-blind. H(a) = p(a passes | tried gears failed) x b, Laplace rule, THETA = 0.5; sigma value H(a) - lambda J(a) with the bin median cost; refusal quantile r chosen by the same replay on the calibration split.
- The v2 budget guard (`agents2.py`, `guard_ok`), its pilot sizing (step_floor = largest in-act step seen in the pilot, close_reserve = largest close, rising to 1.5 x any larger close) and its open threshold 2 step_floor + close_reserve.
- Budgets: B in {0.5, 1.0, 2.0} x J_g2(q), J_g2(q) the median of 5 pilot g2 runs per test puzzle, from the jetson pilot. A level binds if at least 20% of jetson pilot g2 runs exceed it.
- 40 seeds; per seed the 9 conditions in seeded random order; task order shuffled by seed; one unrecorded warm-up pass; garbage collector off inside each metered block. 10,800 episodes.
- Falsifiers R-F1 to R-F8 with the same thresholds; the paired-by-seed analysis (sigma minus Mixture of Limits, tasks closed and run iota, mean, 95% bootstrap interval of the mean with 10,000 resamples and seed 1, seeds where sigma closes more, ties). The analysis code is `analyze2.py`, unchanged, pointed at the jetson directories by `analyze2_jetson.py`.

## Machine

jetson-hub: Ubuntu 24.04, kernel 7.0, Intel Core i9-13900H (6 P-cores with 2 threads, 8 E-cores; 20 logical CPUs), intel_pstate active. The NVIDIA RTX 4050 Laptop GPU is not used; its nvidia-smi power reading (590 W) is implausible for this part and is not used anywhere.

## Energy source and labels

- Primary: `/sys/class/powercap/intel-rapl:0/energy_uj` (package-0). Subdomains logged per episode and per block: `intel-rapl:0:0` (core) and `intel-rapl:1` (psys); an uncore subdomain `intel-rapl:0:1` is logged if present (it is not exposed on this machine). `intel-rapl-mmio:0` is not readable without root and is not used.
- Wraparound: the counter wraps at `max_energy_range_uj` (262,143,328,850 uJ); every read accumulates the delta modulo that range.
- Label: every RAPL figure is `reported_j`, the processor's on-chip energy model/sensor, not a wall meter. `est_j` = cycles x c (c = median pilot reported_j per cycle). `measured_j` is empty.
- Cycles: user-space core cycles of the agent thread from `perf_event_open` on the `cpu_core` PMU (raw event 0x3c). perf_event_paranoid is 4 on this machine, so the harness runs as root. If perf is unavailable, cycles = thread CPU time x pinned frequency, and the run records which.

## Per-act attribution

RAPL is package-level: it counts every process on the chip. Attribution: one episode at a time, the agent process pinned with `taskset -c 4` (one P-core thread), and every metered interval charged

$$ J(a,b) = (E_b - E_a) - P_\text{idle}\,(t_b - t_a), $$

with P_idle the package power over the idle baseline taken just before the current block (agent sleeping). The guard, budgets, J*, iota and every falsifier use this idle-subtracted J. Gross package, core and psys joules are logged alongside. Consequences stated in advance: the counter updates about every 1 ms, so intervals shorter than that read 0 or one whole update, and the idle-subtracted value of a short interval can be negative; other processes' power that changes between the baseline and the block lands in the agent's joules. Other processes are not confined away from CPU 4 (they are not touched); their load is recorded.

## Frequency and power settings

Before the pilot: intel_pstate `no_turbo` = 1 and, on every CPU, scaling_min_freq = scaling_max_freq = base_frequency (2.6 GHz P-cores, 1.9 GHz E-cores). Governor and energy_performance_preference are left as found and recorded. The original settings are saved and restored after the run (also on failure). The agent CPU's average frequency (`cpuinfo_avg_freq`) is recorded before and after each block.

## Load window, gate and baselines

- David's and other users' processes (including the Forgejo CI runner and its containers) are never stopped, paused or reniced. The top CPU users are recorded every 10 s by a separate sampler process on CPU 19 (`results_jetson/load_ps.jsonl`).
- Quiet window: probes every 90 s, at most 40 (about one hour): 5 s of RAPL package power and the other processes' CPU from /proc/stat. Quiet means other processes use at most 0.5 cores. The pilot and run start at the first quiet probe, else after the last probe with `quiet_window = no`.
- Per-block gate: before each block the harness waits, polling 1 s windows for at most 5 s, until other processes use at most 0.5 cores; then the block runs whether or not the gate was met, and the outcome is recorded.
- Idle baseline: 2 s before every block (sets P_idle for that block), 10 s before and after the pilot, 60 s before and after the main run. A block is `quiet_block` when the gate was met and other processes stayed at or below 0.5 cores during the baseline and the block.

## Cross-check (replaces the powermetrics cross-check)

- Block level: block gross package joules minus the block baseline power x block seconds, against the sum of the block's episode reported_j (the gap is harness work between episodes).
- Core subdomain net (same subtraction with the core baseline) over package net; core and psys shares of package gross.
- Drift: idle_post minus idle_pre package power, x main-run seconds.
- Declared not achievable when quiet_window = no or net package joules are not positive; then the load numbers are reported instead.

## Reported, firing nothing

Per-act joules (all acts and confirmed acts), joules per bit and multiples of k_B T ln 2 (300 K), the number of episodes and acts at or below zero after idle subtraction, the share of episodes whose gross package delta is zero (quantisation), a quiet-blocks-only sensitivity table, and a side-by-side with Mac run 1 (`results/summary.json`). Every falsifier outcome is reported, fired or not, with the same prominence.

## Code

`agency_run/meter_rapl.py` (RAPL backend, same interface as `agency_run/meter.py`), `run2_jetson.py` (backend switch: binds `agency_run.meter` to the RAPL backend before any agent module is imported, as `tests/test_guard.py` binds its fake meter; reuses `run2.pilot2` and `run2.replay` unchanged), `jetson_run.sh` (pinning, probes, pilot, wait for the pilot commit, main run, analysis, restore) and `analyze2_jetson.py`, committed together after this file and before the pilot. `agents.py`, `agents2.py`, `sudoku.py`, `run2.py` and `analyze2.py` are not modified. The jetson pilot output (`pilot_jetson/`) is committed before the main run starts; the harness waits for that commit.

## Prediction 1

Not run, for the reasons in `PREREGISTRATION_v2.md`.

## Amendment 1 (committed before any jetson pilot): part B, a RAPL-calibrated cycle meter

Added after the commit above and before any pilot or run. Reason: a software test of the harness (scratch directory `/tmp/agency-smoke` on jetson-hub, unpinned frequency, CI load present, two seeds; its numbers are discarded and used for nothing below) showed that on this machine a gear act lasts about 0.01 to 6 ms (median episode about 0.07 ms) while RAPL package-0 updates about every 1 ms in steps of about 5 to 60 mJ. Two thirds of episodes saw no counter update. The per-read design above (now **part A**) therefore cannot resolve single acts: idle-subtracted pilot medians for J_g2 come out near zero or negative, the guard's open threshold exceeds most budgets, and R-F2 is expected to fire from quantisation alone. Part A runs exactly as written above; its outcome is reported as the meter-resolution result it is.

**Part B** runs the same protocol a second time with a different agent meter, so the selection comparison is tested on this fabric at all:

- The agent's meter (guard, budgets, J*, iota, every falsifier) is `est_j` = the agent thread's user cycles (perf, cpu_core 0x3c) x c. Selection code is unchanged; only the bound meter differs (`meter_rapl.MODE = 'cyc'`).
- c is calibrated on RAPL in the part B pilot, before the gear pilot: 8 rounds of 3 s active (every gear on every calibration puzzle in a loop, agent pinned to CPU 4) alternating with 2 s idle; c = sum over rounds of (package joules minus the mean of the idle power before and after the round x seconds) / sum of cycles. Up to 3 tries if the sum is not positive; else part B stops. c is locked with the part B pilot (`pilot_jetson_cyc/env.json`) and committed before its main run.
- Labels: every part B joule figure is `est_j` (RAPL-calibrated cycle model), not `reported_j`. RAPL figures logged per episode and per block stay `reported_j`. `measured_j` stays empty.
- R-F4 in part B: analyze2's act-level test would compare the cycle model with itself, so it is replaced by Kendall's tau-b between each episode's est_j and the same episode's RAPL package net (harness reads around the episode minus that block's idle baseline x seconds), same threshold 0.8. All other falsifiers, thresholds and the paired-by-seed analysis are unchanged.
- Block-level validation: sum of a block's episode est_j against the block's RAPL package net (idle-subtracted), and core net over package net.
- Outputs: `pilot_jetson_cyc/`, `results_jetson_cyc/`. Same 40 seeds, budgets method (B in {0.5, 1, 2} x the part B pilot median g2 est_j per test puzzle), per-block gate and 2 s baseline, frequency pinning.

Order: probes, part A pilot, part A pilot commit, part A main run, part B pilot, part B pilot commit, part B main run, frequency restored. The load sampler of both parts writes to `results_jetson/load_ps.jsonl`; the quiet-window probes are taken once, before part A.
