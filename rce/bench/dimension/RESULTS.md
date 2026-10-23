# dim-r1: the frozen run (2026-10-23)

Engine: openIE-dev/rce tag `dim-run-1` (commit `22a5992`), binary sha256 prefix
in every row of `results/dim-r1.jsonl`; rustc 1.97 with the 1.98.1 pin ignored.
Registered in `PREREG.json` (amendment of 2026-10-23, hash sidecar) before
the run. Command: `rce dim --json --fuel 100000 --control FILE`. Population:
`spec/examples/*.rce` (60) and every `.rce` of `rce-examples` that `rce check`
accepts standalone (17). Total cpu 252.7 s; est_j = cpu_s × 10 W per row,
labeled estimate; no joules measured.

## Rows

77 programs: 49 commands or without an explorable event (refused, reason
recorded); 28 stateful; 13 bounded within 100,000 states (10 of them not
written for `rce dim`); 15 capped.

| corpus | program | states | capped | behaviours | redundancy bits | control states | cpu s |
|---|---|---|---|---|---|---|---|
| rce-examples | ring_buffer | 12,500 | | 781 | 4.00 | 5 | 0.8 |
| rce-examples | cellular_automaton | 41 | | 1 | 5.36 | 1 | 0.0 |
| rce-examples | reconcile | 4 | | 1 | 2.00 | 1 | 0.0 |
| rce-examples | thermostat | 2 | | 1 | 1.00 | 1 | 0.0 |
| rce-examples | word_count | 2 | | 1 | 1.00 | 1 | 0.0 |
| rce-examples | server | 1 | | 1 | 0.00 | 1 | 0.0 |
| spec-examples | 30_state_machine_guarded | 3 | | 3 | 0.00 | 3 | 0.0 |
| spec-examples | 17_traffic_light | 3 | | 1 | 1.58 | 1 | 0.0 |
| spec-examples | 52_context_text | 3 | | 1 | 1.58 | 1 | 0.0 |
| spec-examples | 51_refined_input | 4 | | 1 | 2.00 | 1 | 0.0 |
| spec-examples | 57_float_vectors | 8 | | 1 | 3.00 | 1 | 0.0 |
| spec-examples | 15_actor, 56_utf8 | 1 | | 1 | 0.00 | 1 | 0.0 |
| spec-examples | 16_multi_region | 100,000 | yes | 102 | 9.94 (lower bound) | 102 | 10.1 |
| spec-examples | 58_float_keys | 100,000 | yes | 2,466 | 5.34 | 2,466 | 10.7 |
| spec-examples | 31_inventory, 55_rcedb | 100,000 | yes | 99,554 / 99,990 | 0.01 / 0.00 | | 17–20 |
| both | account, arm, handshake, ledger, queue_sim, 01_counter, 04_bank_account, 53_capability | 100,000 | yes | 99,999–100,000 | 0.00 | | 9–39 |
| spec-examples | 59, 60, 61 (written for rce dim) | 8 / 6 / 3 | | 4 / 2 / 3 | 1.00 / 1.58 / 0.00 | 1 / 1 / 3 | 0.0 |

## Strata and hypotheses

**Observable** (some explored step emits or refuses): 2 of the 13 bounded
programs (`30_state_machine_guarded`, `ring_buffer`). **Unobservable**: 11
of 13. This is the result of the run: on both corpora, most bounded state
machines have no output, and their intent is carried by `example` lines that
read internal state. By 6.10 each has one behaviour; by 6.9 its examples
still hold. The two readings are consistent and the gap between them is
what `rce dim` measures.

- **H0** (≥ half of bounded programs have redundancy > 0.5 bit): within the
  observable stratum, 1 of 2 (`ring_buffer` 4.00 bits; the guarded state
  machine 0). Not testable at N = 2; recorded, not claimed.
- **H1**: not testable (no multi-emit-site bounded program in the stratum).
- **H2** (per-region attribution ≥ 80% when redundancy > 1): holds on the one
  observable row that qualifies (`ring_buffer`: one region carries all 4.00
  bits). N = 1.
- Capped programs are data-distinguished (counters, ledgers, accounts): every
  explored state is its own behaviour, as expected for unbounded numeric
  state; `16_multi_region` and `58_float_keys` are the exceptions, with
  behaviours far below states (a lower bound on dim, so a lower bound on
  redundancy too).

**`ring_buffer`** is the first real measurement of the quantity: 12,500
reachable states, 781 behaviours, 5 control states. Four bits of its state
change no output; the control view says the buffer is, as a machine of
which steps fire, a five-state thing.

## What the run changes

1. The dimension benchmark's primary population must be observable programs.
   The next run adds the stratum to sampling, not only to reporting, and
   draws from rce-stdlib Forms and the brownfield lifts, which emit.
2. The corpora themselves: a state machine whose examples read state it
   never emits is a program whose intent is not in its Form. That is a
   finding for the examples, and a candidate rule (proposal): an `example`
   that reads a field no step ever emits or refuses on is reported by
   `rce check` as unobservable intent.
3. `rce dim` cost: 100,000 states in 10–40 s with Hopcroft refinement; the
   earlier Moore iteration did not finish the first capped program.

Falsifier status: the PREREG's falsifier (median redundancy < 0.1 bit over
bounded programs) is not triggered and not confirmed; the stratum was too
small to decide it.

# dim-r2: the observable stratum sampled by rule (2026-10-23)

Engine: openIE-dev/rce commit `1107442b` (merged to main as `c83f9e5d`,
PR #5), binary sha256 prefix `c304324798ebf582` in every row of
`results/dim-r2.jsonl`. Registered as the amendment of 2026-10-23T12:40 in
`PREREG.json` (hash sidecar; committed at `dc9a513` before the run).
Command: `rce dim --json --fuel 100000 --control FILE`. Population, by the
registered rule: every `.rce` of the monorepo under `spec/examples`,
`programs`, `apps` and `book/listings` that `rce check` accepts standalone,
has a state region and contains an `emit` or `fail` statement: 25 programs.
The stratum is read from the `observable` key that `rce dim` reports since
this commit (true when some explored step emits or refuses). Total cpu
569.1 s; est_j = cpu_s × 10 W per row, labelled estimate; no joules measured.

## Rows

25 programs: 24 observable, 1 not (`arm`: its `emit` is in `fn main`, not
in a step). 14 observable programs are bounded within 100,000 states; 10
are capped.

| corpus | program | states | capped | behaviours | redundancy bits | control states | emit sites | cpu s |
|---|---|---|---|---|---|---|---|---|
| apps | chat | 100,000 | yes | 176 | 9.15 (lower bound) | 69 | 15 | 347.6 |
| apps | sfu | 40,218 | | 7,038 | 2.51 | 5,095 | 2 | 51.7 |
| apps | terminal | 3,390 | | 270 | 3.65 | 128 | 15 | 31.5 |
| programs | ring_buffer | 12,500 | | 781 | 4.00 | 5 | 1 | 0.6 |
| programs | reconcile | 4 | | 1 | 2.00 | 1 | 0 | 0.0 |
| programs | thermostat | 2 | | 1 | 1.00 | 1 | 0 | 0.0 |
| spec | 52_context_text | 3 | | 1 | 1.58 | 1 | 1 | 0.0 |
| spec | 30_state_machine_guarded | 3 | | 3 | 0.00 | 3 | 0 | 0.0 |
| book | ch05/door | 3 | | 3 | 0.00 | 3 | 0 | 0.0 |
| book | ch10/cart | 100,000 | yes | 27,575 | 1.86 (lower bound) | 27,575 | 0 | 4.4 |
| spec, book | 59/counter_flag, 60/phase, 61/door (written for rce dim; ch18 repeats them) | 8 / 6 / 3 | | 4 / 2 / 3 | 1.00 / 1.58 / 0.00 | 1 / 1 / 3 | 2 / 1 / 0 | 0.0 |
| spec | 31_inventory, 55_rcedb | 100,000 | yes | 99,554 / 99,990 | 0.01 / 0.00 | | 1 | 11.6 / 14.2 |
| both | 04_bank_account, ch06/account, account, ledger, handshake, queue_sim | 100,000 | yes | 99,999–100,000 | 0.00 | | 0–1 | 7–20 |
| programs | arm (not observable) | 100,000 | yes | 100,000 | 0.00 | | 0 | 25.5 |

## Hypotheses

The summary excludes, as the preregistration says, the three programs
written for `rce dim` (59, 60, 61) and their chapter 18 copies, which are
the same programs. That leaves 8 bounded observable programs.

- **H0** (at least half have redundancy above 0.5 bit): 6 of 8 (Wilson 95%
  0.41 to 0.93); over all 14 bounded observable rows, 10 of 14 (0.45 to
  0.88). Median redundancy 1.79 bits (interquartile range 0.25 to 3.37);
  over all 14, 1.29 bits (0.00 to 2.13). The falsifier (median below 0.1
  bit) is not triggered. The interval's lower end is below one half, so H0
  is supported but not established at this size.
- **H1** (one emit site carries more redundancy than several): not
  supported. The two single-site programs have 1.58 and 4.00 bits; the two
  multi-site programs have 2.51 and 3.65 bits; four programs observe only
  through refusals (no emit site). N is too small for an interval, and the
  operationalisation (emit statements in the text) counts a site in a
  function once however many steps call it.
- **H2** (one region carries at least 80% of the redundancy when it exceeds
  1 bit): holds on 8 of 9 rows, but trivially, since 8 of them have one
  state region. The one two-region program, `ch10/cart`, attributes 62% to
  its larger region (`Stats` 1.16 of 1.86 bits, a lower bound), below the
  threshold. H2 is untested until the population has multi-region programs.

## What the run adds

1. **Three application-sized measurements.** `chat` explores 100,000
   states with 176 behaviours and 69 control states: at least 9.15 bits of
   its state change no output, the largest redundancy measured so far, and
   a lower bound. `sfu` (40,218 states, 7,038 behaviours, 2.51 bits) and
   `terminal` (3,390 states, 270 behaviours, 3.65 bits) are exact. These
   are the first measurements of the quantity on programs that were written
   as applications rather than as examples.
2. **The stratum needs a finer rule.** The tool's `observable` is true for
   a program whose every observation is the same (`52_context_text`,
   `thermostat`, `reconcile`: one behaviour, observable only by a constant
   output or a refusal that every state gives). dim-r1 classed such programs
   as unobservable by hand. A third run should register the distinction
   (observable, and more than one observed label) before sampling.
3. **Control states separate the applications.** `chat` has 69 control
   states for 176 behaviours; `ring_buffer` 5 for 781; `sfu` 5,095 for
   7,038. The ratio of control states to behaviours is a measure of how
   much of a program's behaviour is which-steps-fire against which-values-
   flow, and it varies by an order of magnitude across this population.
4. **Cost.** `chat` took 347.6 s of the 569.1 s total: a capped 100,000-state
   exploration of a program with 15 event types. The fuel is the right
   control for a benchmark; a profile of `rce dim` on such programs is
   worth having before the population grows.

# dim-r3: the strict stratum and the multi-region programs (2026-10-23)

Engine: openIE-dev/rce main `690ca9be` (the checker of `929bdeb1`, which
reports distinct observations), binary sha256 prefix `a1443e72be33c29f`.
Registered as the amendment of 2026-10-23T16:05 in `PREREG.json` before
the run (hash sidecar). Population: the dim-r2 rule population plus every
program of the same directories accepted standalone with two or more
state regions: 28 programs (`results/dim-r3.population.txt`; the three
added are `16_multi_region`, `51_refined_input`, `53_capability`). Total
cpu 610.1 s. The dim-r2 rows reproduce exactly (same states, behaviours
and bits for all 25).

## The strict stratum

Strictly observable means observable with at least two distinct
non-silent observations (`distinct_labels` ≥ 2). Of 28 programs: 22 are
strictly observable, 3 observable by a constant only (`thermostat`,
`reconcile`, `cart`, each with one observation), 3 not observable
(`arm`, `16_multi_region`, `51_refined_input`: no explored step emits or
refuses). 12 strictly observable programs are bounded within 100,000
states; 6 of those are not the programs written for `rce dim` or their
chapter 18 copies.

| set | n | median bits (IQR) | redundancy > 0.5 bit | Wilson 95% |
|---|---|---|---|---|
| strict, bounded | 12 | 1.29 (0.00 to 2.28) | 8 of 12 | 0.39 to 0.86 |
| strict, bounded, not written for the tool | 6 | 2.05 (0.00 to 3.74) | 4 of 6 | 0.30 to 0.90 |

- **H0**: supported in direction on both sets (two thirds above 0.5 bit;
  median 1.29 and 2.05 bits) and not established: both intervals include
  one half. RCE-F6 (median below 0.1) is not triggered.
- **H1**: as in dim-r2, not supported and not testable at this size (the
  strict set has the same two single-site and two multi-site programs).
- **H2**, now tested where it can be: over multi-region programs with more
  than 1 bit of redundancy in the strict stratum there is one row,
  `ch10/cart`, whose larger region carries 62% (a lower bound at the cap),
  below the 80% threshold. The two other multi-region rows above 1 bit
  are outside the stratum: `16_multi_region` (9.94 bits, 91% in one
  region, unobservable) and `51_refined_input` (2.00 bits split evenly over
  two of three regions, unobservable). H2 is not supported on n = 1 and
  remains open; the population still has too few observable multi-region
  programs to decide it.

## What the finer rule changed

The strict rule moved three programs out of the stratum (`thermostat`,
`reconcile`, `cart`), each observable only by a constant and each
carrying 1 to 2 bits of redundancy: the constant-observation programs
were inflating dim-r2's count of bits that "change no output" with
programs whose output never changes at all. The medians over the strict
sets are the ones to cite from now on. The observation counts themselves
are a new column: `chat` has 428 distinct observations over 176
behaviours, `ring_buffer` 7 over 781, and the capped counters have one
observation per state (`account` 100,001), which is the data-distinguished
regime seen from the output side.

## Next

The population is the limit on every hypothesis here. Multi-region
observable programs are the shortage (one in the strict stratum). The
next run should draw from the standard library's state-bearing modules
and from the host-contract conformance programs, which declare several
regions and emit, and should be registered with the strict rule from the
start rather than as an amendment.
