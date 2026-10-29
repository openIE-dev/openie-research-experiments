# Bounded programs: nested input, a long service, many options, search (2026-10-29)

This benchmark answers critiques 2 and 3 of the RCE critique list with
programs and measurements:

- critique 2, *state explosion*: 40 independent flags give 2^40 states;
- critique 3, *fuel*: bounded loops turn non-termination into a step-count
  failure, so event loops, schedulers, parsers of arbitrarily nested input
  and SAT solvers are said to be out of reach.

Preregistered in `PREREG.json` (sha256 in `PREREG.json.sha256`, committed
at `9ae9503` before the run). Engine: `rce` built in release mode from
openIE-dev/rce main `8ce91cea`. Programs: openIE-dev/rce branch
`claude/bounded-programs` at `4fff2483`. Harness: `tools/run_bench.py`
(hash in the preregistration). One shared Linux container with 4 CPUs; the
load average was between 66 and 370 during the run (`results/load_*.txt`),
so wall times carry contention noise and are upper bounds.

Terms used below. *Fuel* is the reference evaluator's per-evaluation step
budget (6.7, 50,000,000 ticks; a host gives each input its own, HC-7a). A
*kept* step is one whose event does not apply: the state is unchanged and
the log records why (6.4, T8). *Form* is the canonical JSON that `rce emit
form` prints. *dim* is `rce dim`, which counts the reachable states and the
distinct behaviours of a program by exploring them (6.10).

## M1. Nested input without fuel (`programs/text/json_nest.rce`)

A parser of a JSON subset (null, booleans, integers, strings without
escapes, arrays, objects). It writes no loop bound, no recursion bound,
no `decreases` and no `LOOP_LIMIT`: one `for` over the characters makes the
lexemes, one `for` over the lexemes builds the tree with an explicit
stack. The tree is a recursive `kind`; `depth` and `count` over it are
structural recursion (each call takes a field of a matched constructor).
`rce check` of the program (its 15 checks included) took 2.99 s, `rce test`
3.30 s (median of 3).

`rce run` of a driver per input (the program without its checks, plus
`fn main`), median of 3 runs (one above depth 2000):

| input | value | expected | wall s | peak RSS MB |
|---|---|---|---|---|
| depth 1 | 1 | 1 | 0.017 | 11 |
| depth 10 | 10 | 10 | 0.030 | 11 |
| depth 100 | 100 | 100 | 0.050 | 11 |
| depth 1000 | 1000 | 1000 | 2.63 | 15 |
| depth 2000 | 2000 | 2000 | 13.7 | 20 |
| depth 4000 | 4000 | 4000 | 71.9 | 29 |
| malformed (last bracket missing), depth 1, 10, 100, 1000, 2000, 4000 | -3, -21, -201, -2001, -4001, -8001 | the same | 0.022 to 77.9 | 11 to 28 |
| flat array of 1000 numbers | 1 | 1 | 0.59 | 15 |
| flat array of 4000 numbers | 1 | 1 | 16.4 | 27 |
| flat array of 16000 numbers | 1 | 1 | 327 | 78 |
| structural `depth_of`, depth 1, 10, 100 | 1, 10, 100 | the same | 0.017 to 0.077 | 11 to 34 |
| structural `depth_of`, depth 1000 | 1000 | 1000 | 8.52 | 2,096 |
| structural `depth_of`, depth 2000 | (aborted, SIGABRT) | 2000 | 20.6 | 3,928 |

(`-(p + 1)` encodes `Bad(at: p)`; a depth-d input missing its last bracket
fails at lexeme 2d.)

- **H1 (parser without fuel): supported.** Every depth from 1 to 4000 and
  every malformed input gave the right value; no fuel, size or evaluation
  depth trap occurred.
- **H1b (recursive descent): supported.** `change/json_descent.rce`
  requires change: `W-REC-1 recursion through items, value has no
  decreasing measure (6.7)`. A `decreases` clause alone does not admit a
  recursion either (`tools/decreases_alone.rce`, measured after the run:
  W-REC-1 on `decreases n` with no `bound`), so the one rule that admits
  recursive descent is a declared bound. `tools/json_descent_bound.rce`
  (`bound 2000` on both functions) parses depth 1000 and 1999 and stops at
  depth 2000 with `trap: recursion bound`. That cap is the fuel the
  critique describes; the loop parser does not need it.
- **H1c (cost): the depth prediction held, the width prediction failed.**
  Time grows about as d^2.4 in depth (2.63, 13.7, 71.9 s for 1000, 2000,
  4000) and, against the prediction of linear, as about w^2.2 to w^2.4 in
  width (0.59, 16.4, 327 s for 1000, 4000, 16000). The program does a
  fixed amount of work per lexeme; the reference interpreter copies a value
  each time it is moved (`V::clone` of the whole tree in `interp.rs`), so
  moving a subtree, or the list of children built so far, of size k costs
  k. This is a cost of the reference interpreter, measured here, not of the
  language; no emitted target was measured.
- **A defect of the reference checker.** `rce test` of `check
  depth_of(nest(d)) == d` passes at d = 800 and aborts the process from
  d = 807 (bisection probes in `results/m1_json.json`): a native stack
  overflow inside the recursive `V::clone` (gdb, pilot), where 6.7 promises
  the defined `evaluation depth` trap. Under `rce run` the same recursion
  returns at depth 1000 at 2.1 GB peak and aborts at depth 2000 at 3.9 GB
  under the harness's 4 GiB address-space limit. `json_nest.rce` therefore
  checks depth 1000 with the depth its loop counted.

## M2. A long-running service (`programs/systems/accounts.rce`)

An account service with no main loop: `rce host serve` applies one stdin
line as one step and the program answers on Display (`ok`, or `kept SEQ
CAUSE` from the `StepKept` input the host delivers after a kept step,
HC-21). At most 256 accounts exist, and the one loop (a fee charged to
every account) runs over them, so every step is bounded; a transfer writes
the debit before it checks the credit, so a credit over the cap fails half
way through the step. 100,000 events (`tools/gen_events.py`, seed 12345)
were driven in lockstep (`tools/drive.py`) in 549 s.

| block of 10,000 events | median ms | p90 ms | p99 ms | max ms |
|---|---|---|---|---|
| 0 | 4.000 | 7.98 | 14.3 | 65.9 |
| 1 | 3.998 | 4.53 | 12.0 | 25.4 |
| 2 | 4.000 | 7.07 | 12.0 | 47.1 |
| 3 | 4.002 | 8.00 | 16.0 | 48.1 |
| 4 | 4.005 | 8.06 | 19.8 | 64.2 |
| 5 | 4.001 | 7.99 | 16.0 | 52.4 |
| 6 | 4.002 | 8.00 | 16.0 | 56.0 |
| 7 | 4.000 | 7.57 | 12.0 | 46.1 |
| 8 | 3.997 | 4.50 | 12.0 | 44.0 |
| 9 | 3.997 | 4.11 | 12.0 | 38.2 |

The log D holds 235,536 entries (73 MB); 17,766 inputs were kept, each
followed by `host.StepKept` and the delivered `StepKept`.

- **H2: supported.** The last block's median (3.997 ms) is 0.03% below the
  second block's (3.998 ms), and no block median rises: the run grows,
  each step does not. For every one of the 17,766 `host.StepKept` entries,
  the kept entry's `state_hash` equals the state_hash of the entry before
  it (0 violations), so a transfer that failed after its debit left both
  regions (`Ledger` and `Audit`) unchanged. The host's own replay
  validated all 235,536 entries.
- **What the latency measures.** The median is pinned at 4.0 ms in every
  block; the host makes one durable append (`fdatasync`, HS-2) per
  admitted batch, and with one event per batch that barrier, not the step,
  is the likely cost. The registered "pure step" row is void: `rce trace`
  stops at the first kept step (step 257 of these events), so it timed 257
  steps. Measured after the run instead (`tools/host_batch.py`): `rce host
  run` with the events on stdin took 143, 180 and 310 s for 25,000, 50,000
  and 100,000 events (5.7, 3.6 and 3.1 ms per event, falling as start-up
  is spread), with the same final state_hash (`61e8f7eb…`) and the same
  17,766 kept steps as the lockstep run. The cost of δ alone was not
  isolated.

## M3. Many independent options (`programs/money/checkout.rce`)

`tools/gen_checkout.py` writes a checkout with N options in one record
state (in turn: a flag, a refined tax region `u8 where self <= 3`, an
inventory hold count 0 to 3 whose ends keep the state, a promo code that a
second use keeps); `Place` emits a total with one term per option. The
40-option program in the repository equals the generator's output.

| N | source lines | source bytes | Form bytes | `rce check` ms | dim states | dim behaviours | dim s |
|---|---|---|---|---|---|---|---|
| 5 | 56 | 1,393 | 12,326 | 5.2 | 64 | 64 (exact) | 0.01 |
| 10 | 90 | 2,217 | 18,538 | 5.1 | 4,096 | 4,096 (exact) | 1.97 |
| 20 | 167 | 4,111 | 32,612 | 6.0 | 100,000 (bound) | 100,000 (lower bound) | 236 |
| 40 | 312 | 7,706 | 59,487 | 6.9 | 100,000 (bound) | 95,045 (lower bound) | 1,048 |
| 80 | 602 | 14,904 | 113,170 | 23.8 | did not finish in 900 s | | |

- **H3: supported for the Form and the source, not met for check time.**
  Form bytes lie on a line of 1,347 bytes per option (R^2 = 0.99996), and
  form(80)/form(40) = 1.90; source bytes grow by 181 bytes per option
  (R^2 = 0.99996). Check time stays between 5 and 24 ms, nothing like
  2^N, but its least-squares R^2 is 0.87, below the registered 0.95: the
  step from 6.9 ms at N = 40 to 23.8 ms at N = 80 is not on the line of
  the smaller sizes. With five points at millisecond scale under a load
  average above 100 the cause is not separable from noise.
- **dim is exponential, as predicted.** It explores reachable states one
  by one: 2^6 at N = 5 and 2^12 at N = 10 (each hold count adds 4 states,
  each flag 2, the explored region payloads 2), its default bound of
  100,000 states at N = 20 and 40, and no answer within 900 s at N = 80.
  The program and its Form are linear in the options; the explicit-state
  analysis of `rce dim` is not, and the RCE tools have no compositional
  count that would multiply per-option dimensions.
- Deviation: the registered harness kept only the last 600 characters of
  `rce dim --json`, which cut the one-line JSON at N = 20 and 40. Those two
  were rerun with the whole output kept (`tools/dim_rerun.py`,
  `results/m3_dim_rerun.json`); the first rerun of N = 40 printed nothing
  under a load average near 370 and was run once more with its output
  written to a file.

## M4. Search over input (`programs/science/graph.rce`, `dpll.rce`)

| program | bounds written | what they say |
|---|---|---|
| `dijkstra` (array form, O(V^2 + V·E)) | 0 | each loop runs over the input's vertices or edges |
| `bfs` | 1 (`while head < queue.len() bound n`) | each vertex enters the queue at most once |
| `dpll` | 2 (`bound 64` on the split; `while changed bound a0.len()` in propagation) | at most 63 variables; each propagation pass fixes a variable |

`rce test`: 0.12 s (graph.rce, 46 code lines), 0.03 s (dpll.rce, 84 code lines). Dijkstra / BFS on a path of
100, 200, 400 and 800 vertices: 0.067 / 0.028, 0.144 / 0.080, 0.292 /
0.276 and 1.02 / 0.76 s, each giving n - 1. DPLL on the unsatisfiable
pigeonhole formulas PHP(m+1, m) for m = 2, 3, 4, 5: `false` in 0.009,
0.017, 0.088 and 0.99 s. 63 tautological clauses: `true`; 64: `stopped:
trap: recursion bound`.

- **H4: supported.** Dijkstra needs no bound and reads like the textbook
  array version. BFS needs one bound, which states a true invariant and
  reads naturally. DPLL is where the cost lies: the split recurses on an
  assignment, which has no constructor measure, `decreases` does not admit
  it alone, and `bound` takes only an integer literal, so the solver
  carries a fixed cap of 63 variables unrelated to the input. A solver for
  larger formulas would raise the literal or keep an explicit stack of
  decisions in a `while` whose bound is again a literal (a step budget,
  which is the critique's fuel). Also met while writing it: a list literal
  whose inner lists differ in length requires change (W-TY-1: the inner
  literals get different types), so the unit clause [x] is written [x, x].

## Verdict on the two critiques

- **Critique 3 (fuel) is answered for nested input and for services, and
  stands for search whose depth is not a structure of the input.** A
  parser of any nesting depth needs no written bound when it loops over
  its input, and a service runs without end as a stream of bounded steps,
  with every step that does not apply keeping the state (17,766 of
  100,000, 0 violations). Recursive descent, recursion on integers or
  positions, and backtracking search need a literal `bound`, which is the
  step or depth cap the critique describes.
- **Critique 2 (state explosion) is answered for the program and the
  Form, and stands for `rce dim`.** Forty independent options cost 312
  lines and 59 kB of Form, linear in the options; `rce dim` enumerates
  states and reaches its bound from 20 options on.
- **Costs found along the way**, each a defect or limit of the reference
  implementation rather than of the language: the interpreter's copy on
  move makes the linear parser superlinear in depth and in width, and a
  structural recursion of depth about 800 aborts `rce test` with a native
  stack overflow instead of the defined evaluation-depth trap.

## Files

- `results/m1_json.json`, `m1_decreases_alone.txt`: M1.
- `results/m2_service.json`, `m2_latency_us.txt` (one latency per event,
  microseconds), `m2_host_batch.json`: M2.
- `results/m3_checkout.json`, `m3_dim_rerun.json`: M3.
- `results/m4_search.json`: M4.
- `results/env_*.json`, `load_*.txt`: the binary, machine and load.
- `tools/`: the harness and generators; `dim_rerun.py`, `host_batch.py`
  and `decreases_alone.rce` were added after the registered run, as
  stated above.
