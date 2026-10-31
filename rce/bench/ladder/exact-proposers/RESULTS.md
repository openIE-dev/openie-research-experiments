# Exact-proposer ladder: registered run

Registration: `PREREG.json` (SHA-256 in `PREREG.json.sha256`), committed on
this branch before the run. Ladder: openIE-dev/rce `6d04a096`
(`rce repair`, spec 10.13), `rce` SHA-256 `eb762772...502d`, bound 2000.
Task set: 120 tasks, `tasks.jsonl` SHA-256 `78b82b00...d26e`, listed in
`tasks.list.tsv`. Command: `python3 scripts/ladder-run.py RCE tasks.jsonl
results` at the ladder commit, one machine.

## Closed per rung

| Rung | Closed |
|---|---:|
| a reuse | 4 |
| b lookup by type | 0 |
| c altered rules | 0 (skipped: not in this checker) |
| d bounded enumeration | 114 |
| not closed | 2 |

118 of 120 tasks (98.3%) closed with zero model calls; `rce repair` reported
0 model calls on every task. Candidates judged by the checker: a 303, b 79,
d 2216 (2598 in all). Wall time 411.9 s for the run, median 2.61 s per task,
most of it the parsing of the built-in library for rung a; the longest task
took 41.0 s.

By mutation operator: operator 64 of 64 closed, literal 54 of 55, rename 0
of 1; the generator drew no guard mutant that met the task rule.

## Equivalence split of the 118 closed tasks

| Repair compared with the original | Tasks |
|---|---:|
| restored (same program hash, `rce hash`) | 96 |
| behaviour-equal (`rce equiv` exit 0) | 1 |
| examples only (`rce equiv` found a distinguishing sequence) | 9 |
| undecided (`rce equiv` fuel bound) | 1 |
| not compared (no Form to explore: a program of functions only) | 11 |

97 of the 118 closed repairs (82.2%) are the original program or have its
behaviour. 9 (7.6%) pass every example and check and are not the original:
for instance a state field initialised to 1 instead of 0
(`programs/systems/ring_buffer.rce#operator1`), `a + balance` in place of
`a / balance` (`spec/examples/04_bank_account.rce#operator0`), and a
negated guard (`programs/body/thermostat.rce#operator0`). For the 11 not
compared, passing the checks is all that is known; 4 of them are the rung a
closures, where a function's body became the body of another function of the
same signature that also passes the program's checks (`far_hops` becomes
`far`; `sqrt_newton` becomes the library's `math.sqrt`; `close` becomes
`math.odd_on`). The last of these is not the function that was meant: the
program's checks do not pin it down.

## Not closed

- `programs/data/totals.rce#literal1`: no single edit of rung d, and no
  donor of rungs a and b, satisfies the check on line 21.
- `programs/multi/climate.rce#rename2`: a name replaced by another; rung d
  has no rename edit.

## Against the registration

- P1 (at least 90% close, nearly all at rung d): holds, 98.3%, 114 of 118
  at rung d.
- P2 (at least 5% of the closed are examples only): holds, 7.6%.
- Falsifier 1 (fewer than 50% close): not met.
- Falsifier 2 (restored plus behaviour-equal below 80% of the closed): not
  met, 82.2%; 12 closed repairs (undecided and not compared) are of unknown
  equivalence, so the share of non-original repairs could be up to 17.8%.

## What this does not show

119 of the 120 tasks are operator and integer-literal mutations, which rung d
inverts by construction (the known bias stated in the registration). The
result shows that the public ladder closes these with zero model calls and
how often the first admitted edit is not the original; it is not evidence
about real defects. Rung b closed nothing here, and rung c does not exist in
this checker.

## Files

- `results/summary.json`: the runner's totals.
- `results/REPORT.md`: the runner's tables.
- `results/runs.compact.tsv`: one row per task (closed, rung, candidates,
  wall time, equivalence, the edit). The full log with every attempt
  (`runs.jsonl`, 776 KB) is reproduced by the command above.
