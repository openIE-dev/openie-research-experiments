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
