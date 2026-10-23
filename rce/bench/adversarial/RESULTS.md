# H7 on the fuzzed arm: accepted mutants against five invariants (2026-10-23)

Preregistered in `PREREG.json` (hash sidecar, committed at `d905b37` with
the script before the run). Engine: openIE-dev/rce `929bdeb1` (the
checker of PR #10, merged as `690ca9be`), release build. Input: the 560
mutants of `bench/form-space/results/negatives.jsonl` (v2) that the
checker accepted. Command: `run.py RCE negatives.jsonl results/`. Checker
cpu 60.9 s.

## Result

| invariant | violations |
|---|---|
| I1 chain (seq, prev_hash, state_hash over `hashed.state`, hash over the body with `hashed.event`) | 0 |
| I2 atomicity (a refused step keeps the state and ends the trace) | 0 |
| I3 determinism (`rce check` and `rce trace --json` twice, identical) | 0 |
| I4 the gate (every row re-checks as accepted) | 0 |
| I5 fuel (no fuel trap on the examples' events) | 0 |

560 mutants by operator: literal 252, operator 182, rename 65, type 54,
token 5, guard 2. 468 belong to programs with no example lines, so they
have no trace: I3 and I4 were checked on them and I1, I2 and I5 could not
be. The 92 traced mutants gave 0 violations over every step of every
example trace.

**H7 as registered: supported on the fuzzed arm, 0 violations.** No
model-generated arm exists yet; H7's disproof condition names adversarial
Forms "fuzzed and model-generated", and only the first kind was run.

## A correction made during the run

The first execution of the script reported 12 I1 violations, all on
mutants of `57_float_vectors`. They were the script's, not the
checker's: its canonical JSON used Python's float text, which differs
from the shortest round-trip text of 6.1 N3 for some values. The script
now uses the project's own canonical writer (`scripts/canonical-json-vectors.py`
in openIE-dev/rce) for floats and text, and the 12 disappear. The
preregistration names the invariant, not the implementation of the
writer, so this is a fix of the instrument and is reported as such; the
first summary was not committed.

## Limits

- The arm is small: 560 accepted mutants from ten operators over 180
  programs, 92 of them traceable. A stronger fuzzed arm needs mutants of
  programs with example lines, or streams over the mutants as in
  `bench/determinism`.
- The invariants are those the trace exposes. Invariants of the host
  contract (durable append, verify-on-open) and of the type system
  (ownership, refinement) are checked by the checker's own tests, not
  here.
- "Accepted" means accepted by `rce check` at this commit; the checker's
  rules are the gate, and a rule it lacks is a gap this run cannot see.
