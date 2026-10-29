# Lift of Python 3.13 into RCE: corpus and real-world coverage (2026-10-29)

Preregistered in `PREREG.json` (hash sidecar), committed at `45dcdd3`
before the run; one amendment, committed at `80b825a` before the second
run. The critique this answers is critique 8 of the RCE project's list
(real code, with dynamic dispatch, exceptions and unbounded retry loops,
cannot be lifted, and no lifter exists) and the falsifier RJ-F1 of the
RCE-JEPA page: "Lift coverage plateaus below 80% on any of the five target
languages after the construct list is exhausted".

## Terms

- **Lift**: a translation of a program of another language into RCE text
  that keeps what the program does; route T of `spec/proposals/rce-form.md`
  section 16 in openIE-dev/rce.
- **Case**: one program of `lang/python3.13/corpus` with its input (no
  arguments, no standard input); the corpus holds 92, each with the record
  of its run on CPython 3.13.16 (its exit status, standard output as bytes,
  and class of standard error).
- **Requires change**: the lift reported a construct outside the lifted
  subset, with a rule id and the line; such a program is not lifted.
- **Rule**: one of the 25 ids `L-PY-*` that `lift_py.py rules` prints, each
  naming one family of constructs outside the subset (for example
  `L-PY-EXC`, exceptions; `L-PY-POLY`, a function whose parameter types no
  call fixes; `L-PY-UNBOUNDED`, a while loop with no derivable count bound).
- **i64**: RCE's 64-bit signed integer, whose overflow traps; the lift
  maps Python's unbounded `int` to it.

## What was built

In openIE-dev/rce, branch `claude/lift-python`: `spec/lift/python/lift_py.py`
(Python's own `ast`, no other dependency), the runtime library
`spec/lift/python/runtime.rce`, the harness `verify_lift.py` (whole
programs against the recorded observations) and `coverage.py` (functions
of one module), positive fixtures with CPython's recorded output, one
negative fixture per rule family, `test_lift_py.py` and
`tests/lift_py.rs`.

The subset: integers as i64 (an overflow traps, so a result that leaves
the range is never a wrong number but a stopped run), text of code points,
lists, dictionaries in insertion order, tuples, functions with recursion
(`bound 1000`), `print` with `sep` and `end`, f-strings with int and str
format specs, `for` over ranges and collections, `while` loops whose count
bound one rule of a closed list derives (rule B4 of section 17), list
comprehensions with one `for`. Types are found by unification, one static
type per name. A list or dictionary that a function mutates is passed
`&mut`; aliasing that the copy semantics of RCE could not carry exactly
requires change (`L-PY-ALIAS`).

## Runs

| run | rce commit | instrument | when |
|---|---|---|---|
| registered | `5583974e95cd9d968e913de10b627cf2273695ee` | `rce` of main 8ce91cea (the lift changes no Rust) | after `45dcdd3` |
| second (amendment) | `eb2cd4e5` | the same | after `80b825a` |

The registered run's files are `results/verify.txt`,
`results/coverage-*.txt` and `results/corpus-functions.txt`; the second
run's are under `results/v2/`. The amendment fixed one defect the
registered run found (below); it changed no outcome of a registered
metric.

## Corpus: 92 whole programs

| outcome | registered | second |
|---|---|---|
| MATCH (status, stdout bytes and stderr class equal the record) | 5 | 5 |
| MATCH-RESOURCE (class `resource`: the lifted program stops at the recursion bound) | 1 | 1 |
| DIFFERS (lifted, another observation: a lifter defect) | 0 | 0 |
| KEPT-RESOURCE (lifted, stops at an i64 overflow where CPython answers) | 3 | 3 |
| INTERNAL (`rce run` did not end within 120 s) | 1 | 1 |
| REQUIRES-CHANGE | 82 | 82 |

**Primary metric: 6 of 92 cases hold (6.5%).** The prediction (at most
15) holds. MATCH: `basics/hello`, `algorithms/brackets`,
`algorithms/edit_distance`, `algorithms/knapsack`, `algorithms/quicksort`;
MATCH-RESOURCE: `boundaries/recursion_limit`. KEPT-RESOURCE:
`basics/recursion` (`fact(25)` is 15,511,210,043,330,985,984,000,000),
`algorithms/fib_big` and `algorithms/lcg` (both compute `2 ** 64`).
INTERNAL: `algorithms/hanoi` lifts and passes `rce check`, but its
2^20 list pushes through a recursive function that takes the list `&mut`
did not end within 120 s: on this host the reference interpreter takes
0.24 s for 2^10 pushes in that shape, 2.7 s for 2^12 and 36 s for 2^14,
about n^1.9, so the cost is in `rce run`, not in the lifted text.

No lifted program gave a different result, so the three outcomes the lift
can be wrong in (DIFFERS) are empty; the 4 lifted programs that do not
hold stop, they do not print something else.

Rules of the 82 cases that require change (a case can need several; the
median case names 3), registered run:

| rule | cases naming it | cases whose first reported line names it | cases whose only rule it is |
|---|---|---|---|
| L-PY-TYPE | 30 | 0 | 0 |
| L-PY-CALL | 37 | 10 | 1 |
| L-PY-IMPORT | 32 | 31 | 2 |
| L-PY-EXC | 26 | 4 | 3 |
| L-PY-FLOAT | 22 | 9 | 2 |
| L-PY-CLOSURE | 16 | 0 | 0 |
| L-PY-UNBOUNDED | 14 | 7 | 5 |
| L-PY-POLY | 14 | 7 | 0 |
| L-PY-SYNTAX | 12 | 2 | 1 |
| L-PY-NONE | 11 | 3 | 1 |
| L-PY-DYN | 9 | 2 | 0 |
| L-PY-BYTES | 8 | 2 | 0 |
| L-PY-CLASS | 8 | 1 | 0 |
| L-PY-SET | 8 | 1 | 0 |
| L-PY-INT | 7 | 0 | 0 |
| L-PY-GEN | 5 | 0 | 0 |
| L-PY-ALIAS | 4 | 1 | 0 |
| L-PY-FORMAT | 4 | 0 | 0 |
| L-PY-GLOBAL | 3 | 1 | 0 |
| L-PY-MATCH | 1 | 0 | 0 |
| L-PY-TEXT | 1 | 1 | 0 |

The table is the registered run. In the second run the same 82 cases
require change; 6 of them name other rules: the four `generated/float_*`
programs and `algorithms/bfs_grid` (L-PY-CALL 39, L-PY-TYPE 26): the
second walk of type resolution types a parameter (`bits.to_bytes` is now
`int.to_bytes()`, L-PY-CALL, where the first run could only say the type
was not fixed, L-PY-TYPE), and in `bfs_grid` it gives the `deque` the
program imports the type of the list it is built from, so a second line
`list.popleft()` (L-PY-CALL) stands beside the import that keeps the
program out (noise; the outcome is the same).

Number of distinct rules per case that requires change (registered run):
1 rule, 15 cases; 2, 16; 3, 14; 4, 17; 5, 10; 6, 6; 7, 3; 8, 1. So 15 cases are one
construct family away from lifting, and those families are bounds (5:
`basics/loops`, `algorithms/collatz`, `algorithms/kmp`,
`algorithms/lcs`, `algorithms/prime_factors`), exceptions (3), floats (2),
imports (2), and one each of a call, None and a syntax form.

The corpus was written to exercise one construct family per program,
including the families the subset leaves out (exceptions, classes,
floats, sets, generators, Unicode data, the standard library), so it is a
hard population for a first lifter by design; the function-level count
below and the real-world module are the other two views.

## Function level

**Primary metric (real world): heapq.py of the pinned CPython 3.13.16
standard library (sha256 `6d43277e…`), 0 of 15 functions lift (0%).**
The prediction (below 20%) holds. Every function but `merge` names
`L-PY-POLY`: `heappush(heap, item)` and its siblings work on a list of
any comparable item, and nothing in the module calls them, so the lift
has no type for the item; RCE text needs one (a generic RCE function with
an `Ord` bound would carry them, and the lift does not write one). The
four sift functions also name `L-PY-UNBOUNDED`: `while pos > startpos:`
with `pos = parentpos` moves the variable by a computed amount, which no
rule of the closed list derives a bound for, though the loop does halve
the distance every time. `merge`, `nsmallest` and `nlargest` use
generators, exceptions, `key=` functions and `None`. Second run: the same
0 of 15; 8 functions name `L-PY-POLY` as their only rule (6 in the
registered run, where two also carried a noise line `L-PY-TYPE` on the
receiver of `.pop()` that the amendment folds into `L-PY-POLY`).

Secondary modules of the same library (not a registered threshold):

| module | functions | lifted | what blocks |
|---|---|---|---|
| bisect.py | 4 | 0 | the defaults `lo=0, hi=None, *, key=None` (L-PY-CALL, L-PY-NONE), raise, the binary search `while lo < hi` whose two ends both move (L-PY-UNBOUNDED), calls of `key`, polymorphism |
| colorsys.py | 7 | 0 | float arithmetic in every function (L-PY-FLOAT) |
| graphlib.py | 0 module-level (11 methods in 3 classes) | 0 | all code is in classes (L-PY-CLASS); methods are not counted as functions by the registered definition |
| textwrap.py | 5 (14 defs with methods) | 0 | defaults and keyword-only parameters, the `TextWrapper` object that `wrap`, `fill` and `shorten` build (reported as L-PY-CLOSURE, a call of a value; L-PY-CLASS would be the better id), the module's compiled regular expressions (L-PY-GLOBAL), a lambda, assert |

Descriptive, not registered: the 67 functions of the corpus programs,
lifted one by one with their callees: 16 lift and 1 was INTERNAL in the
registered run (`algorithms/matrix:mul`, whose text `rce check` did not
accept: the defect below); 17 lift (25.4%) and none is INTERNAL in the
second run.

## The defect the run found

The registered run's descriptive function count printed text for
`algorithms/matrix:mul` (`sum(a[i][k] * b[k][j] for k in ...)` inside a
nested comprehension) that `rce check` does not accept: the lift bound
the generator's list to a temporary before the statement, outside the
names of the comprehension. Reading the code for it found three more of
the same family that no case had reached (a temporary bound once for a
`while` test, a temporary evaluated for a branch that does not run, an
`elif` test that discarded the `if` test's temporaries) and an order
dependence of type resolution. `eb2cd4e5` fixes all of them; the amendment
registered the second run before it ran.

## RJ-F1

**Measured lift coverage of Python is far below 80%: 6.5% of the corpus
programs, 25% of the corpus functions, 0% of heapq.py's functions.** The
falsifier is worded for a plateau "after the construct list is
exhausted". This is the first lifter and the construct list is not
exhausted: the rules above are that list, each a family the lift has not
built (exceptions are transform B2, closures B3, generators B5, classes
and the heap B4's heap threading, unbounded integers a runtime of wide
integers, which `stdlib/lib/core/exact.rce` has and the lift does not
call). So RJ-F1 is neither met nor refuted by this run, as the
registration predicted. What the run does establish:

- A lift can be exact where it applies: 10 programs lifted, and none of
  them printed anything CPython did not print; the 4 that do not hold
  stop at a limit (i64, a 120 s limit), which the outcomes count apart
  from holding.
- The single largest real-world blocker is not exceptions or dynamic
  dispatch but **types**: library code is polymorphic, and route T needs a
  type per name. On heapq.py, 8 of 15 functions are blocked by nothing
  else. The second is **bounds**: loops whose progress is a computed
  amount (binary search, heap sifts, Euclid, Collatz, KMP) have no bound
  from the closed rule list.
- The critique holds for the constructs it names, as measured: dynamic
  dispatch (L-PY-CLASS, L-PY-DYN), exceptions (L-PY-EXC, 26 of 82) and
  unbounded loops (L-PY-UNBOUNDED, 14 of 82) each block programs today.

## Limits

- One oracle, one host; the lifted programs run on the reference
  interpreter `rce run`, not on an emitted program.
- The corpus is the acceptance suite the lifter was developed against
  (section 20 has no held-out part; a case that differs is fixed in the
  lifter). heapq.py and the secondary modules were not tuned for: heapq.py
  was run once before registration (0 lifted) and only diagnostic wording
  changed after.
- Function-level coverage counts module-level functions; methods of
  classes are not counted (they would all require change, L-PY-CLASS).
- A rule's count is an upper bound on its weight: when a construct cannot
  be typed, the names that depend on it can carry a second rule; the
  "only rule" column is the firm one.
- No energy or time claim beyond the 120 s limit and the push timings
  above (wall clock on this host, one run each).
