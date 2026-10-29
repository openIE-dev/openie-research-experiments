# The edit landscape: H11 and RJ-F4 on a checker-outcome energy (2026-10-29)

This study was preregistered in `PREREG.json`, committed at `47f5f98`
before the first run. The checker binary `rce` was built in release mode
from openIE-dev/rce `main` at `8ce91cea`. The script is
`scripts/edit-landscape.py` at commit `0cb1a2a7` on the branch
`claude/gate-measures`. It was run as
`scripts/edit-landscape.py --rce ... --out results/ --jobs 4`, under the seed
`0x5eedc0de0004`. The checker used 2,190.6 s of CPU time.

## The claims tested

Critique 4 says the latent search is not smooth: a one-character change
flips the verdict, so a search guided by an energy score over edits may
not converge. The RCE-JEPA page at research.openie.dev states two items
this bears on:

- **H11.** "Energy is monotone in edit distance". The metric is the share
  of test families in which the energy E rises with edit distance 1 to k
  from an accepted fit. H11 is supported at 80% of families or more, and
  goes against at less than 80%.
- **RJ-F4.** "H11 fails and search does not reach accepted Forms within
  the beam budget". This falsifier is aimed at energy-guided planning in
  Form space.

The RCE project has no energy head today. This study therefore measures a
hand-defined energy built from the checker's outcomes. Such a score is the
most direct one available, and it bounds what a score built from outcomes
alone can do.

## Terms

- **Family**: one admitted program with example lines, with duplicate
  shapes removed. There are 59 such programs. 3 are excluded because
  `rce trace` cannot trace them: they `use` library modules, and
  `rce trace` does not link those, although `rce check` does. The excluded
  programs are `programs/ecosystem/hpke.rce`,
  `programs/ecosystem/mls_key_schedule.rce` and
  `programs/network/notes_http.rce`. That leaves **56 families**.
- **Edit**: a typed single-token change on a code line, of one of four
  kinds. A *rename* replaces an identifier with another name of the same
  program. An *operator* edit swaps an operator for another of its class.
  A *literal* edit moves an integer by ±1 or swaps true and false. A
  *type* edit swaps one of u64/i64/f64 for another, or text for bool. Every
  edit has an inverse in the same set.
- **Chain**: 5 successive edits, each drawn uniformly from all edits of the
  current text. Each family has 6 chains, which gives 1,680 points at
  nominal distance d = 1 to 5.
- **Probe**: one of the original's example event lists, or two of them
  concatenated. Each family has between 2 and 272 probes.
- **Energy**: E = R + B. R is the number of distinct rule ids that
  `rce check` names (0 when the program is admitted). B is the share of
  probes on which the trace differs from the original's. The original has
  E = 0.
- **Descent**: greedy best-improvement on E, starting from chain points at
  distance k = 1, 3 and 5. Each step evaluates up to 64 sampled
  neighbours. The descent stops at E = 0, when no neighbour improves E, or
  after k + 3 steps. *Success* means the descent ends at an admitted
  program that equals the original on every probe.

## Results

### Verdict flips

| d | admitted, same behaviour | admitted, behaviour differs | requires change: W-INT-1 only | requires change: other rules |
|---|---|---|---|---|
| 1 | 9 | 4 | 17 | 306 |
| 2 | 2 | 0 | 3 | 331 |
| 3 | 0 | 0 | 1 | 335 |
| 4 | 0 | 0 | 0 | 336 |
| 5 | 0 | 0 | 0 | 336 |

- **96.1%** of single edits from an admitted program require change
  (323 of 336).
- Over all 1,680 transitions along the chains, 20.0% flip the verdict.
  Every flip runs from admitted to requires change: there are 336 such
  flips and none in the other direction. No chain walked back into
  admission once it had left it.
- 17 of the 336 single edits were caught only by the examples (W-INT-1).
  Most of the rest are caught by name, type and step rules: W-NAME-1,
  W-TY-1, W-STEP-1, W-STEP-2 and W-UNUSED-1 are the most frequent.

### Is the energy monotone in edit distance?

| d | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| mean E | 0 | 2.82 | 3.75 | 4.35 | 4.74 | 5.13 |

- Pooled over all families, the mean E is monotone (non-decreasing) in d.
- The Spearman rank correlation of E with d over all points is **0.560**.
- The per-family Spearman correlation is above 0 in **56 of 56** families
  (secondary metric).
- **H11 primary metric: 43 of 56 families (76.8%)** have a mean-E profile
  that is non-decreasing over d = 0 to 5. The other 13 have a profile
  that falls at least once between d = 1 and d = 5, by 0.17 to 1.17. Each family has
  only 6 chains, and two edits can cancel each other's rules, so these
  dips are within the noise of the measurement.

**H11 as registered: against (76.8% < 80%)**, and only narrowly. The
energy does rise with distance: pooled, per family by rank, and in every
family on average. But a family's profile is not reliably monotone
point by point. With 6 chains per family the primary metric sits close to
its threshold, so a run with more chains could land on either side of it.

### Does greedy descent on E get back?

| start distance k | descents | success (admitted, same behaviour) | reached any admitted program | ended at the original text |
|---|---|---|---|---|
| 1 | 336 | **81 (24.1%)**, of which 9 started there | 85 | 65 |
| 3 | 336 | **7 (2.1%)** | 9 | 5 |
| 5 | 336 | **2 (0.6%)** | 4 | 1 |

Most descents stop after 1 or 2 steps because no sampled neighbour
improves E. A point that requires change has hundreds to millions of
neighbours, so the one edit that repairs it is rarely among the 64
sampled.

**RJ-F4 as registered: observed.** H11 fails, and descent from k = 3
returns to a program equal in behaviour to the original 2.1% of the time,
far below the registered 50%. This goes against energy-guided planning on
a score built only from checker outcomes, under this budget.

## What the result says about RCE, plainly

- **Critique 4 is right about the landscape.** One typed edit almost
  always (96%) moves an admitted program out of admission. Once out, a
  random walk never came back within 5 edits. The verdict is not a smooth
  function of the text.
- **H11 goes against**, narrowly. The energy rises with distance on
  average and by rank in every family. It is not monotone point by point
  in 23% of families.
- **RJ-F4 is observed** for this energy and budget. Greedy descent on a
  count of rules plus a behaviour distance rarely finds the way back from
  more than one edit away.
- What this does not show: the energy here is hand-defined, not a trained
  energy head. The edits are token edits, not moves in a latent space. The
  neighbourhood is sampled, not enumerated, and there is no beam. An
  energy built on a representation in which near programs are near could
  behave differently. This result is the baseline such an energy has to
  beat. As registered, it does not support the planning claim.

## Limits

- Renames make up 96% of the drawn edits (1,616 of 1,680), because a
  program has far more identifier and name pairs than operators,
  literals or types. This follows the registration (uniform over all
  edits). Edits of the other kinds behave differently. Of the 15 drawn at
  d = 1, 5 were admitted and 7 more required change on W-INT-1 only (the
  examples caught them). Of the 321 renames at d = 1, 8 were admitted and
  10 required change on W-INT-1 only. A study that draws edit kinds
  uniformly would show a gentler first step than this one.
- B is measured on probes built from the examples, not on all inputs.
- The 13 non-monotone families each rest on 6 chains.

## Deviations from the preregistration

- The first run was stopped by its 30-minute background time limit before
  it wrote any result. The script then gained a per-family result file,
  so that a run can resume (commit `1027c3b8`). The measurement did not
  change.
- The second run spent over an hour on `apps/chat.rce`. With about
  2.1 million single renames, the script built every edited text to draw
  one. That run was stopped, and partial results from 58 families were
  seen. Commit `0cb1a2a7` now indexes the edits and draws by rejection.
  This samples from the same distributions the registration names:
  uniform over edits with a new result, and a uniform sample without
  replacement for the descent neighbours. It uses the seeded generator
  differently, so the recorded run reran every family from the start.
  The numbers above come only from that run.
- The metrics, energy, edits, budget and thresholds are as registered.

## Files

- `results/summary.json`: every number above, with a per-family profile
  and Spearman correlation under `families_detail`.
- `results/points.jsonl`: one row per chain point (d, edit kind, outcome,
  rules, B, E, and the SHA-256 of the text).
- `results/descents.jsonl`: one row per descent.
- `results/run.log`: per-family evaluation counts and checker time, and the
  summary.
