# Exact-proposer ladder on real defects: registered run

Registration: `PREREG.json` (SHA-256 in `PREREG.json.sha256`), committed on
this branch (64e70389) before the run. Ladder: openIE-dev/rce `7dc4eded`
(`rce repair`, spec 10.13, with rung c; pull request #96), `rce` SHA-256
`a620120e...1c55`, bound 2000. Task set: 151 tasks, `tasks.jsonl` SHA-256
`6ae255a3...af50`, listed in `tasks.list.tsv`. Command: `python3 run.py RCE
tasks.jsonl results 900`, one machine.

## One deviation: 20 tasks killed by the machine

In the registered run, 20 consecutive tasks (from
`programs/science/knapsack.rce#guard0` to `programs/text/json_nest.rce#guard1`)
ended with exit -9 after 9 to 50 s: the kernel's out-of-memory killer, acting
on the memory group this run shared with two other build jobs, killed the
`rce repair` processes (the kernel log names the group). No rung judged them
to an end, and the 900 s cap was not reached. Those 20 tasks, and only those,
were run again with the same binary, runner and cap once memory was free
(`results/rerun-killed/`); all 20 completed. `results/runs.compact.tsv` and
`results/summary.json` are the registered run as recorded, with the 20 rows
at exit -9; the tables below use the rerun for those 20 rows and the
registered run for the other 131. Nothing else was run again or excluded.

## Closed per rung

| Rung | history-admit (33) | history-fix (8) | guard (27) | rename (83) | All (151) |
|---|---:|---:|---:|---:|---:|
| a reuse | 0 | 0 | 0 | 0 | 0 |
| b lookup by type | 0 | 0 | 0 | 0 | 0 |
| c altered rules | 0 | 1 | 0 | 0 | 1 |
| d bounded enumeration | 0 | 0 | 27 | 3 | 30 |
| not closed | 33 | 7 | 0 | 80 | 120 |

31 of 151 tasks (20.5%) closed with zero model calls; `rce repair` reported
0 model calls on every task, and no task reached the 900 s cap. Candidates
judged by the checker: a 2866, b 871, c 14, d 9586. Wall time: 899 s for the
registered run and 58 s for the rerun of the 20; median 2.1 s per task, the
longest 110 s.

Without the guard tasks, which rung d inverts by construction, 4 of 124
tasks close (3.2%).

## Equivalence split of the 31 closed tasks

| Repair compared with the original | history | guard | rename | All |
|---|---:|---:|---:|---:|
| restored (same program hash, `rce hash`) | 1 | 25 | 0 | 26 |
| behaviour-equal (`rce equiv` exit 0) | 0 | 0 | 0 | 0 |
| examples only (`rce equiv` found a distinguishing sequence) | 0 | 0 | 2 | 2 |
| undecided (`rce equiv` fuel bound) | 0 | 1 | 0 | 1 |
| not compared (a program of functions only) | 0 | 1 | 1 | 2 |

- **History.** The one closure is `spec/examples/29_nested_kind.rce@013e21ed`,
  whose parent required change only under W-UNUSED-1: rung c wrote what
  `rce fmt` writes, and the result has the program hash of the child commit.
  The other 40 are not closed. 25 parents do not parse today (the retired
  `refuse` syntax), so no rung edits them; the 7 of the retired `#!lib` line
  name functions that no longer exist (W-NAME-1); the 5 W-LEN-1 parents use
  an unqualified `len`; 2 break the extern rules (W-WORLD-1, W-CAP-3); and
  `spec/examples/57_float_vectors.rce@b2b932da`, the one W-INT-1 defect (an
  example that expected 0 where the value is -0), is not closed by any of
  the 24 candidates judged.
- **Guard.** All 27 close at rung d, as its "`not` removed" edit predicts; 25
  are restored. Two are not known to be the original:
  `spec/examples/55_rcedb.rce#guard0` closed by `0` becoming `1` at line 11
  (undecided), and `programs/text/edit_distance.rce#guard1` closed by
  `prev[j] + (1)` becoming `prev[j] % (1)` (not compared; the program's
  checks do not pin that function down).
- **Rename.** 3 of 83 close, none restored. In
  `spec/examples/30_state_machine_guarded.rce#rename1` and
  `spec/examples/61_dim_minimal.rce#rename1` rung d changed a state field's
  initial `false` to `true` elsewhere, which compensates for the wrong name on
  the examples but not on every event sequence (examples only); in
  `spec/examples/44_device_region.rce#rename1` `a * b` became `a + b` (not
  compared). 68 of the 83 mutants fail a static rule, and no rung changes a
  name back. The 8 mutants whose report was only W-UNUSED-1 were not closed:
  rung c named the unread binding as `rce fmt` does, and the checker then ran
  the checks, which do not hold (the static report had stopped `rce check`
  before the checks; it did not mean that the checks hold).

## Against the registration

- P1 (history: at most 4 of 41 close; rung c closes
  `29_nested_kind.rce@013e21ed`): holds, 1 of 41, that one.
- P2 (guard: at least 85% close, nearly all at d, at least 70% of the closed
  restored): holds, 27 of 27 at d, 25 of 27 restored (92.6%).
- P3 (rename: 10% to 40% close; rung c closes the W-UNUSED-1-only mutants,
  none restored): fails. 3 of 83 (3.6%) close, and rung c closes none of the
  8: their report hid failing checks.
- P4 (under 50% of the 151 close): holds, 20.5%.
- F1 (the first run's closure rate carries over to changes from real
  history; false if under 50% of the 41 close): met. 1 of 41 (2.4%) close;
  the claim is false on this set.
- F2 (rung c adds closures; false if it closes none): not met. Rung c closed
  1 task, the history task that only rung c could close.
- F3 (closing restores the program; false if restored plus behaviour-equal is
  under 80% of the closed): not met. 26 of 31 (83.9%) are restored; 2 are
  known not to be the original and 3 are of unknown equivalence, so the share
  that is not the original could be up to 16.1%.

## The bias of this set

- **History is Form migrations, not defects.** 39 of the 41 history tasks are
  changes the programs made because the language changed (a retired syntax,
  a retired line, a renamed builtin, new extern rules), judged by today's
  checker; only 2 are defects of a program, and the ladder closed one of
  them. The git history of openIE-dev/rce at the base holds 41 qualifying
  pairs in all, too few real defects for a set of them alone.
- **Guard negation is rung d's own inverse.** The 27 guard tasks make up 27
  of the 31 closures (87%); like the operator and literal tasks of the first
  run, they show that the ladder undoes the mutation it was built to undo.
- **Renames are mostly caught statically.** 68 of 83 rename mutants fail a
  type, place or name rule, which the checker locates by line; the ladder has
  no edit that changes a name back, so this class measures the gap, not the
  ladder's reach.
- **Small corpus.** The guard and rename tasks come from the same public
  corpus as the first run (spec/examples, programs, stdlib/tests), at most two
  per program and class.

## What this does show

On changes from real history and on renames, the model-free ladder closes
almost nothing (1 of 41 and 3 of 83); its high closure rate on single
mutations (98.3% in the first run, 100% here on guard negations) comes from
mutations its rung d inverts. Rung c closes the case it is built for, a
program that requires change only under an altered rule, and restores it.

## Files

- `PREREG.json`, `PREREG.json.sha256`: the registration.
- `tasks.py`, `list.py`, `run.py`: the generator, the list writer, the runner.
- `tasks.list.tsv`, `tasks.summary.json`: the task set and the generator's
  counts.
- `results/summary.json`, `results/runs.compact.tsv`: the registered run as
  recorded (20 rows at exit -9).
- `results/rerun-killed/summary.json`, `results/rerun-killed/runs.compact.tsv`:
  the rerun of those 20.
- The full logs with every attempt (`runs.jsonl`, 3.6 MB and 0.4 MB) are
  reproduced by the commands above.
