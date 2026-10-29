# Behaviour index: results

Registered in `PREREG.json` (sha256 in `PREREG.json.sha256`, commit
9dec0dd, amendment 1 in 0f4ab15 before any result was written). Engine:
openIE-dev/rce `claude/behaviour-index` at
`de957edcb62141084ac25423ba15129d2ba4dc08`, `rce` built with
`cargo build --release`; the corpus from `scripts/corpus.py` of that tree
(programs and mutants identical to main 8ce91cea). Run on 29 October 2026
on the shared Linux x86_64 session container, alongside other builds, so
wall times are upper bounds. Files: `results/summary.json`,
`results/pairs.jsonl`, `results/collisions.jsonl`, `results/programs.jsonl`;
`results/collision-witnesses.jsonl` is a post-run classification (below),
not part of the registered metrics.

Terms: the *program hash* is CC-1 (`rce hash`, the last line), computed
over the name-free projection. The *fingerprint* is BF-1
(`rce fingerprint`): a hash of the name-free outputs of every event
sequence of length 1 to d over the alphabet `rce equiv` explores. A pair
is *equivalent* when `rce equiv --fuel 20000` says so (exact, or to the
explored bound).

## Population

1,079 distinct program texts (1,052 admitted standalone): 217 corpus
programs and their name-free projections (set T7), the accepted mutants
of `scripts/corpus.py` paired with their parents (M-eq 89,
M-change 27, M-noex 485, M-same 1), and the 24 hand-written reshapings
(set H).

**Coverage.** 308 programs (28.5%) can be fingerprinted at depths 1 to 4
and 302 at depth 8. Of the rest, 750 have no state region (a command: a
function with `check` lines, one behaviour by 6.10, nothing to explore),
17 have no explorable event, 4 name-free projections do not parse, and
at depth 8 4 reach the fuel bound and 2 exceed 120 s. The fingerprint is
a key for state machines; commands, which are most of this corpus, need
another key (a function's input/output table on its boundary set) that
this work does not build.

The 4 projections that do not parse are a finding about `rce fmt
--nameless` (10.6), outside this measurement: in `stdlib/lib/math/math.rce`,
`num/linalg.rce`, `num/special.rce` and `num/stats.rce` the projection
renames the exponent marker of a float literal when the module declares
a name `e` (`9.332636185032189e-302` becomes `9.332636185032189v10-302`).
`scripts/t7-equiv.sh` counts these as skipped, so CI does not see them.

## Recall: behaviour-equal pairs of different shape

| Set | pairs equivalent and both fingerprinted | same program hash | same fingerprint, depths 1, 2, 4, 8 | of these, distinct program hash and same fingerprint |
|---|---|---|---|---|
| H (hand-written reshapings) | 23 | 0 | 23, 23, 23, 23 | 23 of 23 |
| M-eq (mutants, examples agree) | 66 | 31 | 66 at every depth | 35 of 35 |
| M-change (mutants, trace heads differ) | 19 | 0 | 19 at every depth | 19 of 19 |
| M-noex (mutants, parent without examples) | 17 | 8 | 17 at every depth | 9 of 9 |
| T7 (projection, control) | 62 | 62 | 62 at every depth | none (all share the hash) |

- **P2 holds.** Every pair `rce equiv` judges equivalent and both
  fingerprinted shares the fingerprint at every depth: 187 of 187. None
  is missed, as BF-1 guarantees.
- **The program hash finds none of the reshapings.** Among the 86 pairs
  with distinct program hashes (23 H, 35 M-eq, 19 M-change, 9 M-noex),
  the program hash finds 0 and the fingerprint 86. P1 as registered
  ("at most 10% of M-eq and H pairs share the program hash") is missed:
  31 of 89 equivalent M-eq and H pairs (35%) share it, because a mutant
  that changes only an intent string, a comment or an example line has
  another nameless text (the corpus's "same shape" test) and the same
  program hash. Those 31 are not reshapings; the 58 that are reshapings
  (23 H, 35 M-eq) all have distinct program hashes.
- **M-change is mostly equivalent.** 19 of the 23 decided pairs that
  `scripts/corpus.py` classifies as a behaviour change caught by no
  example have the same behaviour by `rce equiv`: their trace heads
  differ because the state differs, while every output is the same (the
  redundancy that `rce dim` measures).
- **One hand-written pair is equal and not confirmed.** H pair 15 (a
  growing list against a counter mod 3) has the same behaviour, shares
  the fingerprint at every depth (the list program steps 255 states at
  depth 8), and `rce equiv` reports "different (no finite witness within
  the explored graph)" because the list program reaches the fuel bound.

## False positives

Every group of programs with one fingerprint, every pair in it decided by
`rce equiv` (no group reached the 200-pair cap):

| Depth | pairs in shared groups | equivalent | different | undecided (timeout) |
|---|---|---|---|---|
| 1 | 580 | 469 | 86 (14.8%) | 25 |
| 2 | 535 | 469 | 41 (7.7%) | 25 |
| 4 | 504 | 469 | 10 (2.0%) | 25 |
| 8 | 489 | 469 | 10 (2.0%) | 10 |

P3 holds: collisions fall with depth, to 2.0% at depth 8. Every
different pair has distinct program hashes. Among the M-change pairs
`rce equiv` judges different, 1 of 4 shares the fingerprint at depth 1
and 0 at depths 2 to 8.

**Post-run classification (not registered).** Each collision `rce equiv`
calls different was rerun for its distinguishing sequence
(`collision-witnesses.jsonl`). At depth 1, 76 of 86 have one, of length 2
to 4; at depth 2, 31 of 41, of length 3 or 4; at depths 4 and 8, none of
the 10 has one: all 10 are "different (no finite witness within the
explored graph)", two programs whose exploration reached the fuel bound
(`16_multi_region` and its mutants, the `files-accept` and `pty-accept`
host-contract tests and their mutants, and H pair 15). Every witness is
longer than the depth it collided at, as BF-1 requires. 7 of the 10 still
share the fingerprint at depth 16; the other 3 cannot be fingerprinted at
depth 16 within 200,000 states. So at depth 4 and above, no collision in
this population is a behaviour difference that `rce equiv` can exhibit;
the 10 are pairs that bounded `rce equiv` cannot decide, and it reports
them as different. That is a finding about `rce equiv`: under a bound, a
"different" verdict without a witness is not evidence of a difference,
and `rce change` would classify such a change as a meaning change.

## Cost

| Depth | median | p95 | max | states stepped (median, p95, max) |
|---|---|---|---|---|
| 1 | 4.1 ms | 16 ms | 75 ms | 1, 1, 1 |
| 2 | 4.0 ms | 66 ms | 116 ms | 3, 8, 17 |
| 4 | 4.3 ms | 505 ms | 11.7 s | 7, 70, 1,024 |
| 8 | 4.2 ms | 253 ms | 11.3 s | 10, 616, 4,336 |

Wall time of one `rce fingerprint` call, process start included, over the
fingerprinted programs. P4 holds (median under 50 ms at depth 8). One
`rce equiv` call: median 6.4 ms, p95 45.6 s, max 120 s (25 of 1,212
calls exceeded the 120 s bound). The fingerprint is computed once per
program and compared by equality; `rce equiv` runs per pair.

## What this answers and what it does not

Critique 1 says that hashing the name-free Form only reuses programs
identical up to names. On this population that is so for the program
hash (0 of 86 reshaped pairs found) and not for the fingerprint (86 of
86 found, no miss among the 187 equivalent pairs), and at depth 4 and
above every collision is a pair `rce equiv` cannot separate by any
event sequence it explores. Rice's theorem is not contradicted: equality
is up to the bound, in three senses. The alphabet is the boundary set of
6.3 per payload type, so programs that differ only on other payloads
share the fingerprint; the sequences are at most d events long, so
programs that differ only later share it (a depth-1 collision is
resolved at length 2 to 4 here); and `rce equiv`, the confirmation, is
itself to the explored bound. Most of the corpus (750 of 1,079 texts)
are commands that this key does not cover. The 24 reshapings were
written for this measurement and are small state machines; recall on
reshapings found in the wild is not measured.
