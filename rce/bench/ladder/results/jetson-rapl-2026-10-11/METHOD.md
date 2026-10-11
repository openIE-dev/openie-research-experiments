# RAPL subsample, jetson-hub, 2026-10-11 (11:51 ET)

Engine f2701b7, binary sha256 prefix ec601d8bb0320502 (built on the box, glibc symbols <= 2.39; runs unmodified on Ubuntu 24.04).
Host: jetson-hub, Intel i9-13900H; Forgejo CI runners were up (idle sample 40-44 W). CPUs 2-5 via taskset, 4 workers.
Meter: RAPL package-0 over the whole harness run (Python driver included), less the idle power from a 10 s sample taken just before, times the run's duration. These are reported_j, package-level, not wall-meter measured_j.

| run | tasks (TEST) | solved | raw J | reported_j | reported_j per task | reported_j per solved | s |
|---|---|---|---|---|---|---|---|
| L1 ManySStuBs4J shuffle positions 2000-3999 | 2000 | 690 | 377.2 | 17.9 | 0.009 | 0.026 | 8.2 |
| L0 gson mutants (seeded, first 3000) | 3000 | 3000 | 648.3 | 167.5 | 0.056 | 0.056 | 11.8 |

The L1 subsample builds its project index from these 2000 tasks only (the full run builds it from all 26,072), so its solve rate (34.5%) is lower than the full TEST run's rate.
With the idle baseline at 40-44 W and runs of 8-12 s, the uncertainty on reported_j is about ±1 W × duration, i.e. ±10 J on these totals.
