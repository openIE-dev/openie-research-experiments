# Agency run 2: preregistration

Fixed and committed before the v2 pilot and before the v2 main run. The code is `agency_run/agents2.py`, `run2.py`, `analyze2.py`, `quiet_run.sh` and `tests/test_guard.py` as committed with this file. Nothing below changes after the commit. Everything not named here is as in `PREREGISTRATION.md` (run 1): machine, meter, labels, tasks, predicate, coupled bits, gears, arms, feature, Laplace rule, R* and its hash, quantities, J*, rankings.

## Why a second run

Run 1 fired R-F2. 36 of 5,400 episodes ended above budget. 16 were law-arm closes 0.07% to 3.6% over: the comparison C(z), the receipt and the final meter read ran outside the guard. 20 were goal-blind cuts at B = 0.5 J_g2 up to 33% over: no bound applied before the first metered step. Run 1 also fired R-F3: 13.1% of law-arm refusals fell on pairs some arm closed, above the 10% limit. Run 2 fixes the guard, makes one preregistered change to the refusal threshold, adds seeds, declares the paired-by-seed analysis in advance and runs inside a measured load window.

## Change 1: the budget guard (all arms)

Every joule of an episode is charged inside the guard: selection, R* and its hash, every gear step, the comparison C(z), the receipt entry and the final meter read. The agent starts further work only while

$$
\text{spent} + 2\,\text{max\_step} + \text{close\_reserve} < B .
$$

- `max_step` is the largest metered interval between two checks in the episode, floored at `step_floor`, the largest in-act step seen in the v2 pilot.
- `close_reserve` starts at the largest close (comparison, receipt, final read) seen in the v2 pilot and rises during the run to 1.5 times any larger close observed.
- The check runs before every selection and between gear steps. The opening decision uses spent = 0 and no extra meter read.
- A law arm that fails the check refuses with the receipt "no room for another step and a close". The goal-blind arm that fails the check is cut. The same rule binds all three arms.
- The guard holds whenever every interval between checks costs at most 2 max_step, every close costs at most close_reserve and B is at least close_reserve. `tests/test_guard.py` proves the invariant by property test and by running `episode2` over every test task, all arms and budgets from 20 microjoules up, under an adversarial fake meter, with zero overspends allowed. The same harness finds the run 1 overspends.
- Budgets below 2 step_floor + close_reserve cannot be enforced by a metered agent on this machine; every arm stops at open there. The pilot records this threshold.

## Change 2: refusal threshold calibrated on the calibration split

The budget-fit tests of both selectors (does a gear fit the remaining budget) use the r-quantile, over calibration tasks in the bin, of each task's median pilot cost for that gear. Run 1 used the bin median (r = 0.5). The sigma-law value H(a) - lambda J(a) is unchanged and still uses the bin median cost. H(a) = p(a passes | tried gears failed) x b, exactly as run 1.

r is chosen before the main run by replay on the calibration split only (`run2.py`, `replay`). For each calibration task and budget level B in {0.5, 1.0, 2.0} x (that task's median g2 cost), both selectors are simulated with each task's median gear costs and pass records. A pair is infeasible when the guard fails at open or no passing gear costs at most B - close_reserve. Precision is the share of refusals on infeasible pairs; recall is the share of infeasible pairs refused. The grid is r in {0.10, 0.25, 0.50, 0.75, 0.90}. The rule: maximize precision subject to recall at least 0.9 (if no r reaches 0.9, maximize precision over all); break ties toward r = 0.5. The test split is never used.

## Pilot

As run 1, rerun inside the run 2 window: every gear alone on every calibration puzzle, 5 repetitions, unbudgeted, no in-act reads; g2 alone on every test puzzle, 5 repetitions. Then guard sizing: the same gears with the in-act reads the agents use, 2 repetitions, recording every step and every close. Output: `pilot2/locked.json` (cost table, quantile table, r, replay table, J_g2, est_j per cycle, step_floor, close_reserve, open threshold), committed before the main run by `quiet_run.sh`.

## Main run

- Budgets per task: B in {0.5, 1.0, 2.0} x J_g2(q) from the v2 pilot. A level binds if at least 20% of pilot g2 runs exceed it.
- 40 seeds (run 1: 20). Per seed, the 9 conditions in a seeded random order; task order shuffled by seed; one unrecorded warm-up pass; garbage collector off inside each metered run. 10,800 episodes.

## Load window and package cross-check

- David's processes are never stopped, paused or reniced.
- Before the run, `quiet_run.sh` probes every 180 s for up to 60 probes (about 3 hours): three powermetrics samples at 2 s (CPU, GPU and ANE power) and a process list. Quiet means package CPU at most 5 W, GPU at most 3 W and the other processes' total CPU at most 200%. Every probe is logged in `results2/load_probe.jsonl`. If no probe is quiet, the run starts after the last probe and records `quiet_window = no`.
- During pilot and main run a process-list sampler writes the top CPU users every 10 s to `results2/load_ps.jsonl`.
- Idle baseline: 60 s of powermetrics (500 ms samples) before and after the main run, with the agent process idle.
- Main window: 90 s of powermetrics starting with the main run. The per-process meter is read at the window's start and end.
- Cross-check: package joules in the window minus baseline power x window seconds, against the agent's per-process reported_j in the same window; reported for CPU only and for the whole package, with baseline drift (post minus pre). The cross-check is declared not achievable when `quiet_window = no`, when net package joules are not positive, or when baseline drift x window seconds exceeds the agent's process joules. In that case the load numbers are reported instead.
- Labels: powermetrics and per-process figures are `reported_j`. `est_j` = cycles x c. `measured_j` is empty: no wall meter.

## Falsifiers (unchanged from run 1, same thresholds)

| ID | Observation | Claim defeated |
|---|---|---|
| R-F1 | At every binding level, the 95% bootstrap interval of the paired per-task difference in median J*, sigma minus Mixture of Limits, over tasks both close, includes or exceeds zero | The sigma-law selector closes tasks in fewer joules than Mixture of Limits |
| R-F2 | Any episode in any arm ends with J above its budget | That arm's budget enforcement and refusal |
| R-F3 | Refusal recall below 0.9 on task-level pairs no arm ever closes, or more than 10% of law-arm refusals on pairs some arm closes in at least half the seeds | Refusal correctness |
| R-F4 | Kendall's tau-b between est_j and reported_j per act below 0.8 | The cycle-count estimator for any ranking |
| R-F5 | Coefficient of variation of run iota across seeds above 0.25 in any condition | Reading iota at run granularity in that condition |
| R-F6 | Ranking by J* differs from ranking by integrated iota at any level | Ranking by J* equals ranking by integrated iota |
| R-F7 | Any confirmed act with reported joules per bit below k_B T ln 2 | The accounting |
| R-F8 | At a binding level the goal-blind mean run iota is at least the larger of the two selectors' | Prediction first, comparison and refusal raise iota over a goal-blind agent |

Every falsifier outcome is reported, fired or not, with the same prominence, next to its run 1 outcome.

## Paired-by-seed analysis (declared in advance, secondary)

Within a seed, all arms see the same task order. For each level and seed: tasks closed by sigma minus tasks closed by Mixture of Limits, and run iota of sigma minus run iota of Mixture of Limits. Reported per level: mean difference, 95% bootstrap interval of the mean (10,000 resamples, seed 1), the count of seeds where sigma closes more and the count of ties. This analysis fires no falsifier.

## Prediction 1 in software: not run

Prediction 1 needs an act cost that falls with act time tau and a standing cost that rises with tau. This software agent has neither term under the experimenter's control. Its acts are fixed computations; the operating system, not the agent, sets clock frequency and core type, so the per-process act cost does not fall as a declared function of tau. Its per-process standing cost while it waits is near zero, and the machine's standing power lives only in package power, which other load swamps. A dose-response design here would test the scheduler, not Prediction 1. Run 2 therefore runs no software analogue and makes no claim about the k_B T-scale test.
