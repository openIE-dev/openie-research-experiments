# Lookup-table controls: what example obligations constrain (2026-10-29)

Preregistered in `PREREG.json` (committed at `47f5f98` before the
recorded run). Engine: openIE-dev/rce `main` at `8ce91cea`, `rce` built
from `spec/checker` in release mode; the script is
`scripts/table-control.py` at commit `58ba72de` on the branch
`claude/gate-measures` (the script only; the checker is unchanged at that
commit). Command: `scripts/table-control.py --rce ... --out results/`.
Total checker CPU time: 17.3 s.

The question is critique 5 (Goodhart): if the completeness predicate of a
program is a list of examples, a lookup table over those examples meets
it. It bears on RJ-F2 of the RCE-JEPA page, which concerns the cost of
writing intent specifications: an intent specification made only of
examples does not pin behaviour down, so its cost cannot be weighed
without asking what it constrains.

## Terms

- **Obligation**: a proposition the gate (`rce check`) evaluates before
  it admits a program. For steps, these are the `example` lines (6.9:
  fold the events from the initial state, state the outcome of the last
  step). `check` lines are propositions about comptime values, and
  `requires`/`ensures` contracts (F.6.2) are propositions about functions.
- **Lookup-table control** of a program P: P with one more field per
  region (`tblpos`, the region's position in a trie of the example event
  lists, each list restricted to the events the region has a step for).
  Each step of P applies only at a trie position that has a child for its
  event and moves the position to that child. One more step per event
  moves along the trie without touching P's fields (for an event where P
  selects no step of the region). A last step with no guard fails with the
  new error `TblOff`, so every event off the table keeps the state. In a
  program with one region of one field, arrow steps are written as blocks
  and `-> v` becomes `-> f == (v)` (the same proposition by 6.9).
- **Valid control**: `rce check` admits it or names only W-INT-1, and
  traced on the example event lists it equals P step for step (outcome
  and hashed state, with `tblpos` projected away).
- **Probe**: an event list made of two example lists, one after the other
  (every ordered pair). A probe that is not itself an example list falls
  off the table.

## Result

| | count |
|---|---|
| admitted programs with example lines (shape-deduplicated) | 59 |
| controls built | 59 |
| valid controls | 56 |
| **valid controls the gate admits** | **56 of 56** |
| valid controls the obligations distinguish (W-INT-1) | 0 |
| valid controls that differ from their program on at least one probe | 56 of 56 |
| probes that differ, over all valid controls | 605 of 787 |

The other three controls are also admitted by `rce check`, but they could
not be traced, so their equality with the program on the examples could not
be confirmed: `programs/ecosystem/hpke.rce`,
`programs/ecosystem/mls_key_schedule.rce` and
`programs/network/notes_http.rce`. Each `use`s a library module (`hpke`,
`crypto`, ...). `rce trace` does not link library modules, so every step
traps with "unknown name hpke" (or similar), while `rce check` links them
and evaluates the examples. That is a gap in `rce trace`, recorded here and
not fixed by this study.

Other obligations: 1 valid control's program has a `check` line
(`programs/money/ledger.rce`) and 1 has refined types
(`spec/examples/51_refined_input.rce`). No program in the population has a
`requires` or `ensures` contract. None of these is the reason any control
requires change, because none requires change.

The programs carry between 1 and 16 example lines (median 3). 15 of the 56
valid controls have more than one region and 14 have one region with one
field, so the construction is not limited to the simplest shape.

**The prediction held.** Every valid control is admitted: the obligations
these programs state do not tell any of them from a program that equals
them on the listed event lists and keeps the state on every other list. On
the probes, 77% of off-table lists already show the difference. This is the
limit of the gate, measured: examples are evidence about finitely many
event lists, and no obligation in the language today states behaviour on
lists beyond them.

## What this does and does not say

- It does not say that the programs are wrong or that their examples are
  poor. It says that admission certifies the listed cases (and types,
  ownership, totality and the other rules of section 7), not the general
  behaviour. An admitted program "complies with the Form"; it is not
  thereby the intended program.
- Totality (W-STEP-2) and the type rules do constrain the control: it had
  to keep a step for every event and stay well typed. They constrain its
  shape, not its behaviour off the table.
- A stricter table keyed on payload values as well as event names would be
  admitted for the same reason: it meets every example by construction.

## Change made after the measurement (registered under `after_the_measurement`)

The `claude/gate-measures` branch of openIE-dev/rce adds a recommended change
to `rce check`: **W-INT-2**. A module that has a step and example lines is
admitted as before (exit status 0) and gets one more line after `ok FILE`:

```
recommended FILE: line N: W-INT-2 the K example lines are the only obligations on the steps; their lookup-table control (6.9) meets them, so they do not constrain behaviour beyond the listed examples
```

It is specified in 6.9 (the construction above and why it meets every
example), in section 7 (W-INT-2, recommended, never requires change) and
in 10.2 (the output line). It has the conformance tests
`tooling/int-2-table-control` and `tooling/int-2-no-examples`. The
condition is structural: the measurement shows that the control meets the
examples by construction, so the checker does not need to build the control
to know that it would be admitted. The note will stop applying when the
language gains an obligation on steps that is stronger than a finite list,
such as a property over all event lists of a bounded length. No such
obligation exists today.

## Deviations from the preregistration

Between the registration and the recorded run, the construction was fixed
four times on pilot runs over the same population. Each fix concerned
building the control, not the metrics:

1. The fallback steps used a bare event name for events with payload
   fields (`W-TY-1 ... has fields`). They now use `E(f: _, ...)`.
2. The parser of event declarations did not read `interrupt event ...
   priority p`.
3. `-> v` was rewritten to `-> f == (v)` even when the outcome already
   named the field (a condition), which gave W-TY-1.
4. Traces that trap on an unlinked library module were first compared trap
   against trap, which made the equality check vacuous. They are now
   reported as untraceable and the control is not counted as valid.

Fixes 1 to 3 turned construction failures into built controls. Fix 4 moved
3 programs from valid to untraceable. No pilot run ever produced a control
that requires change on W-INT-1, so no fix turned a control the
obligations distinguish into an admitted one.

## Files

- `results/summary.json`: the counts above.
- `results/controls.jsonl`: one row per program, with its obligations, the
  control's gate result, its equality on the examples and its probe
  differences.
- `results/controls/`: the 59 control programs, which can be checked with
  any `rce`.
