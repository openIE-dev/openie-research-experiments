# Specification cost in the RCE corpus (critique 10, 2026-10-29)

RCE is the Reality Code Engine (openIE-dev/rce). The critique: stating
intent precisely is as hard as writing the code. In the RCE-JEPA paper
(research.openie.dev/papers/rce-jepa/, Section 5; JEPA is a Joint
Embedding Predictive Architecture) this is falsifier RJ-F2: "Writing
σ(ι) for the 7 reference applications costs more person-hours than
writing their Forms by hand", where σ(ι) is the written specification of
an intent ι (required traces, contracts, tests, prose).

Preregistered in `PREREG.json` (sha256 sidecar `PREREG.json.sha256`,
committed at `01d7782` before the harness existed). The harness
`measure.py` was committed at `009a69a` before the full run; its sha256
is `056627386ccf11883befb77727b8f72defbd163207bc0519fe20ff75a4afdaff`.
Engine: openIE-dev/rce `a82a0348` (main). The `rce` binary was built from
`8ce91cea`; `git diff 8ce91cea a82a0348 -- spec/checker` changes only
`spec/checker/tests/lift_py.rs`, so the checker is the same. The emitter
stamps `8ce91cea` in its provenance line. Rows are in `results/files.jsonl`
(106 files) and `results/mutants.jsonl` (1,581 mutants). The summary is
in `results/summary.json`.

Run notes. A first launch of the frozen harness was stopped by the
session's background time limit before it wrote any output. It was
started again, unchanged and detached, and that second run (20:13 to
23:05 UTC) is the one reported here. The pilot on
`programs/body/thermostat.rce` was used to fix one fault before freezing:
the emitter now writes a one-line `rce-program` provenance header before
the runtime prelude, and the harness strips that line before checking
the prelude prefix.

## What this does and does not test

**RJ-F2 as registered is not tested here.** It is stated in person-hours
over the 7 reference applications. A timed authoring study needs people
who write both halves, a timing protocol, and the 7 applications written
as Forms. None of these exists in this environment: `apps/` holds 4
programs, and no timing record exists. This run measures two proxies
instead:

- **(A) Written size:** how large the specification is next to the
  program it specifies.
- **(B) Behavioural sufficiency:** whether the written obligations
  determine the program's behaviour, measured with mutants of the program
  while the obligations stay fixed.

Size is not effort: one example line can take longer to decide than ten
lines of code, or the other way round. Every program was written by the
RCE project, often with its examples written alongside the code, so the
corpus is not a sample of outside authors or of specifications written
before the code.

## Population

The `scripts/corpus.py` population rule gives 367 candidate files. Of
these, 91 are not admitted standalone, 145 carry no obligation and 25
duplicate a shape already counted. That leaves 106 files:

- **60 in the primary subset** (an intent block or at least one example
  line): 59 state machines and 1 library.
- **46 with only check lines or contracts:** 43 libraries (mostly
  `spec/examples` and `stdlib/lib`) and 3 commands.

Two files have a bare program (all obligations removed) that requires
change: `spec/examples/32_comptime_block.rce` and
`spec/examples-0.9/ok/11_contracts_ghost.rce`. They are missing only from
the emitted-size columns.

Definitions (registered):

- **Intent text:** the `intent "..."` line and the STRING lines of its
  block.
- **Obligations:** the `example` lines, the `check` lines, and the
  `requires`, `ensures`, `decreases` and `ghost` lines.
- **Body:** every other non-blank, non-comment line.

Bytes are counted with leading indentation and trailing comments removed
on both sides.

## Part A: size of the specification against the program

Primary subset, 60 files. Medians, with the interquartile range (IQR,
first to third quartile) in brackets:

| quantity | bytes | lines |
|---|---|---|
| intent text | 78 [59, 138] | 1 |
| obligations | 153 [105, 208] | 3 [2, 4] |
| body | 423 [291, 597] | 21 [14, 31] |
| bare program, nameless Form (`rce fmt --nameless`) | 484 [306, 654] | |
| emitted Python, program part (registered) | 18,282 [17,314, 19,867] | |
| emitted Python, without the `DISPLAY_ESCAPE` table (secondary) | 3,174 [2,206, 4,759] | 86 [60, 115] |
| emitted Rust, program part (registered) | 21,193 [19,522, 23,529] | |
| emitted Rust, without the table (secondary) | 6,065 [4,394, 8,401] | 182 [142, 222] |

Every emitted program carries a constant `DISPLAY_ESCAPE` table of about
15 kB that is not part of the shared runtime prelude. The registered
column includes it. The secondary column, added after the pilot showed
the table and not registered, leaves it out, and it is the fairer size of
the code.

Ratio of obligations to program:

| ratio | median [IQR] | min to max | files above 1 |
|---|---|---|---|
| obligation bytes / body bytes | **0.37** [0.26, 0.51] | 0.04 to 2.00 | 3 of 60 |
| obligation lines / body lines | 0.13 [0.09, 0.18] | 0.007 to 0.84 | 0 |
| (intent text + obligations) / body, bytes | 0.60 [0.46, 0.79] | 0.05 to 3.23 | |
| (intent text + obligations) / body, lines | 0.19 [0.13, 0.25] | | |
| obligation bytes / emitted Python bytes (no table) | 0.046 [0.026, 0.062] | | |
| body bytes / emitted Python bytes (no table) | 0.125 [0.106, 0.136] | | |

Pooled over the primary subset, there are 16,345 obligation bytes and
7,200 intent-text bytes against 85,173 body bytes.

By class (obligation bytes / body bytes, median):

| class | files | median | above 1 |
|---|---|---|---|
| programs/ | 26 | 0.45 | 1 (`programs/ecosystem/mls_key_schedule.rce`, 2.0: three example lines carrying long hex vectors) |
| spec/examples | 16 | 0.44 | 2 (`57_float_vectors`, 1.40; `60_dim_hidden_period`, 1.05) |
| conformance accepts | 10 | 0.14 | 0 |
| book/listings | 5 | 0.39 | 0 |
| apps/ | 3 | 0.14 (`chat` 0.04, `terminal` 0.14, `sfu` 0.58) | 0 |
| kind: machine | 59 | 0.37 | 3 |
| check-or-contract-only files (libraries and commands) | 46 | 0.23 [0.09, 0.42] | 5 (`42_f32`, `45_byte_text`, `46_u64`, `sizes`: test vectors for built-in types; `11_contracts_ghost`, 1.12) |

**Reading (registered rule).** The median obligation/body byte ratio over
the primary subset is 0.37, which is at or below 1. In this corpus the
written obligations are smaller than the programs they constrain: about
a third of the body in bytes and an eighth in lines. They are smaller
still against emitted Python (about 1/20) and Rust. The files where the
specification is larger than the code are vector tests: their expected
values are long literals, such as hex digests or float bit patterns.

## Part B: do the obligations pin down the behaviour?

Subsample: the 59 state-machine files of the primary subset with example
lines. This meets the registered minimum of 20. The registered secondary
arm (command programs with check lines) is empty: no command in the
population has check lines. The 43 libraries with check lines have no
behaviour oracle under the registration and are not scored.
`apps/terminal.rce` could not be scored because its base trace failed.

Mutants come from the five typed operators of `scripts/corpus.py`
(rename, operator, literal, guard, type) under seed `0x5eed_c0de_0010`.
Only mutants whose changed lines are all body lines are used, so the
obligations stay as written. Of the 1,581 mutants:

- 964 are not a program: the bare mutant requires change (rename 560,
  type 211, guard 123, operator 65, literal 5).
- 156 show no difference under the oracle.
- **461 are behaviour-changing**, in 54 files.

The oracle does not use the obligations. It traces the bare programs on
the example event lists plus 64 random streams drawn from a payload pool
of boundary values and program literals, and it also runs `rce equiv`.

The tests under W-INT-1 (the admission rule: every `example` and every
`check` must hold) catch these behaviour-changing mutants:

| measure | caught / behaviour-changing | share | Wilson 95% |
|---|---|---|---|
| all obligations (mutant with its obligations requires change, bare mutant admitted) | 327 / 461 | **0.709** | 0.666 to 0.749 |
| of which by W-INT-1 itself (an example or check does not hold) | 319 / 461 | 0.692 | 0.648 to 0.732 |
| example lines only (check lines removed) | 326 / 461 | 0.707 | 0.664 to 0.747 |
| scripts/corpus.py's definition (behaviour change judged on the example streams only) | 318 / 368 | 0.864 | 0.825 to 0.895 |

The other 8 catches are W-TY-1 (6), W-TY-3 (1) and W-NAME-1 (1). In 7 of them a payload type changed in an `event`
line, and in 1 a variant was renamed; an example then no longer type-checks.

- **Per file:** the median catch share is 0.75 [0.50, 0.92], ranging from
  0 to 1. Every behaviour-changing mutant is caught in 12 of 54 files
  (22%): `01_counter`, `17_traffic_light`, `53_capability`, `54_secret`,
  `58_float_keys`, `arm`, `handshake`, `word_count`,
  `cellular_automaton`, `queue_sim`, `apps/chat` (1 mutant) and the
  book's `counter`.
- **By operator:** operator swaps are caught in 166 of 201 (0.83), literal
  changes in 147 of 236 (0.62), type swaps in 8 of 15 and renames in 6 of
  9. No guard mutant produced an admitted program with a different
  behaviour.
- **Uncaught (134):** 89 are literal changes and 35 are operator swaps,
  such as `a > balance` to `a >= balance` in `04_bank_account`, or a
  threshold moved by one. They are the same kind the RCE-JEPA page
  reports: a constant or boundary that no example exercises.
- **Example lines against check lines:** removing the check lines lowers
  the catch by 1 mutant. In the state-machine programs the example lines
  carry almost all the obligation.

**Reading (descriptive, as registered).** Against an oracle that does not
use the obligations, the program's own obligations catch 0.71 of the
behaviour-changing mutants. Judged only by the example streams, as
`scripts/corpus.py` judges, the share is 0.86. The earlier page figure,
317 of 392 (0.81), used that weaker definition with a different seed and
operator mix. About a fifth of the behaviour changes the oracle finds
(93 of 461) are visible only to the random streams or to `rce equiv`. So
the example-based figure overstates how fully the obligations pin
behaviour. The obligations are small (Part A) and they do not pin
behaviour down: in 42 of 54 files at least one single-point change to the
program is admitted with a different behaviour. The two findings are consistent
with each other. Small obligations here are partial specifications, and closing
the gap would make them larger: an example per boundary, or a property
over all inputs.

## Limits

- The oracle is bounded: 64 streams of at most 6 events, plus `rce
  equiv` on its boundary alphabet. `rce equiv` hit the 60 s per-call limit
  on 149 of the 617 admitted mutants, which were then judged by the
  streams alone. "No difference found" is therefore not equivalence, and
  every catch share is over the changes the oracle can see.
- In 15 mutants the obligations catch a change that the oracle did not
  see. In these programs the example's outcome expression calls a pure
  function (for example `mls_key_schedule`, `notes_http`, `ledger`) whose
  result is not in the traced state. These are not in the denominator.
- The operators make single local edits. A person who writes the wrong
  formula makes a different kind of error. Critique 5 (Goodhart: a
  predicate made of examples can be met by a lookup table) is the
  stronger version, and it is not tested here.
- Bytes and lines measure writing, not deciding what to write.

## Part two: Jevons-type and "good enough" economics (note, no measurement)

The critique has two parts. The first is Jevons-type: cheaper code
generation raises total demand rather than closing it, as cheaper coal
raised coal use (Jevons 1865). The second is "good enough": unchecked
generated code is cheap and adequate, so precise specification is not
worth its cost. The site papers in research-openie-web
`src/content/papers/` address the critique as follows. There is no
`rce-economics` paper in `src/content/papers/` or `src/pages/`.

- **`satiation.md`, "Task Satiation vs. Aggregate Rebound in AI Demand."**
  - *Claim, in Sections 1 and 5.1:* task-level satiation holds by
    definition: once a task's completeness predicate C is true, more
    synthesis on it adds nothing. Aggregate satiation is not implied. The
    paper states that cheaper synthesis can open new tasks (Acemoglu and
    Restrepo 2019) and raise total use (Jevons 1865; Alcott 2005), and
    that "this rebound is the central identification problem".
  - *Rebound taxonomy, in Section 3.7:* direct, indirect and economy-wide
    rebound (Gillingham, Rapson and Wagner 2016; Khazzoom 1980; Brockway
    et al. 2021).
  - *Its own hypothesis:* the paper states H2, "Jevons in tasks", as a
    direct-rebound elasticity of the number of tasks run. It reports no
    estimate: "This paper does not deny global rebound. It refuses to
    treat 'Jevons' as a reason to avoid writing C."
  - *What would settle it, in Sections 5.1 and 5.9:* a panel of accounts
    recording price paid, tasks opened, calls per task and an adjudicated
    completeness label per episode. Measured before and after provider
    price cuts at fixed model quality, it gives a difference-in-differences
    estimate of the task-count elasticity and the per-task spend
    separately.
- **`ai-coding-market.md`, "The Promised Trillion Dollar AI-Coding
  Market."**
  - *Section 6:* quotes the venture forecast ("we believe Jevon's Paradox
    in this case holds", Appenzeller and Li 2025, its [1]). It separates
    per-task demand, which stops at C = 1, from total use, which can grow.
  - *Section 6, the one published elasticity:* Anthropic's Economic Index
    (its [29]) gives ε ≈ −0.29 across tasks. The paper notes this is
    cross-sectional, not a price change over time.
  - *Sections 4 and 5:* a reuse argument, Proposition E0: a task with a
    stored solution that passes its check tends to cost the energy to
    retrieve and check that solution. The expected price per task depends
    on the covered fraction f, which is unmeasured.
  - *What would settle it, in Section 7:* E4 measures f on a random
    sample of merged pull requests, with a Wilson interval. E1 measures
    the task index at which a store-and-reuse method's cost per resolved
    task crosses below generation's, under an external power meter. E3
    measures the token share of task cost by round.
  - *Gap:* it does not address "good enough".
- **`interface-economics.md`, "The Price of the Unexamined Interface."**
  - *This is the closest the site comes to "good enough".* Its claim,
    from the Abstract and Section 6: writing down and checking interface
    assumptions is cheap, but the party who does it pays while others
    benefit, so it is under-supplied. Generated code crosses the same
    interfaces.
  - *Proposition E2 ("checks pay"):* a check of cost c pays when
    c < π Σ L_m, where π is the probability that a crossing violates the
    assumption and L_m is the cost the violation imposes at each level it
    reaches.
  - *Proposition E3:* proposes a two-arm handoff study, prose against a
    machine-checked representation, recording labour hours and interface
    failures in each arm.
  - It states these as hypotheses and measures neither.

**What would settle the economic question.**

- **Jevons:** the satiation H2 panel above (market-level prices and
  quantities, task counts and per-task spend separately), together with
  ai-coding-market E4 for the covered fraction f. None of the papers
  holds that data.
- **"Good enough":** a paired study on one stream of real tasks. One arm
  accepts generated code on review alone. The other writes obligations
  and admits only code that meets them. Each arm records:
  - the person-hours to write the obligations, which RJ-F2's timed study
    would supply;
  - the person-hours and energy to produce accepted code;
  - the defects that escape to later levels, and their cost;
  - the cost of each check, as interface-economics E2 and E3 lay out.

  Part A above gives the size of the obligations in one project-written
  corpus. Part B shows that obligations of that size still miss about 3
  in 10 single-point behaviour changes, which is the escape rate a "good
  enough" comparison would have to price. Neither part gives hours or
  dollars.
