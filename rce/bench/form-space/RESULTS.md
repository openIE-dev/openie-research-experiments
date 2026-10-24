# H1: Form space against source space (first measurement, 2026-10-23)

Preregistered in `PREREG.json` (committed at `00c8972` before the run).
Engine: openIE-dev/rce commit `145d2a8a` (the generator's commit, on main
through PR #7), `rce` built from `spec/checker` in release mode. Command:
`scripts/corpus.py --rce ... --out results/`. Total checker cpu 56.9 s.

## The quantity

rho = b(code) / b(P), with b(P) the bits of the nameless canonical source
of the program and b(code) the bits of the program part of the emitted
source (the shared runtime prelude excluded, and checked to be a verbatim
prefix in every row). Under the primary operationalisation both are
tokens times log2 of the side's vocabulary over the population (form
vocabulary 20,912 tokens; python 31,865; rust 32,490; js 31,937; scala
32,309). The rows also carry the two secondary views registered: UTF-8
bytes and gzip-9 bytes.

## Result

n = 173 distinct shapes with an emitted form on every target.

| view | python (primary) | rust | js | scala |
|---|---|---|---|---|
| tokens x log2 vocabulary, median (IQR) | **9.31** (8.42 to 10.91) | 17.33 (13.45 to 23.21) | 11.06 (9.55 to 14.02) | 13.66 (10.68 to 17.89) |
| UTF-8 bytes, median (IQR) | 7.23 (5.80 to 8.99) | 15.0 (11.6 to 20.8) | 8.12 (6.46 to 10.31) | 10.66 (8.06 to 13.86) |
| gzip-9 bytes, median (IQR) | 3.64 (2.87 to 4.86) | 5.73 (4.49 to 7.61) | 4.27 (3.31 to 5.78) | 5.03 (3.90 to 6.71) |

Share of programs with rho (python) at least 5: 171 of 173 (Wilson 95%
0.96 to 1.00). By origin the python median is between 8.8 and 10.2 for
every corpus (spec examples 9.71, book listings 9.73, conformance accept
9.73, 0.9 examples 10.21, standard library 8.98, programs 8.82, apps
8.83), so the ratio is not carried by one kind of program.

**H1 as registered: supported.** The median rho on the primary view is
9.31, above the threshold of 5; it is above 5 on every target and on the
uncompressed byte view, and above 2 (the disproof line) on the compressed
view on every target. The falsifier (median below 2) is not triggered on
any view.

## Reading the three views

The vocabulary view is what the RCE-JEPA page defines, and it is the
largest ratio because the emitted side's vocabulary is 1.5 times the
Form's and its programs are longer. The byte view removes the vocabulary
term and keeps repetition. The gzip view removes most repetition: an
emitted program's type annotations, explicit error handling and runtime
calls compress well, so the ratio falls to 3.6 (python) and 5.7 (rust).
That view is the honest lower bound for "how much more does a generator
have to write": a Form is about a third to a sixth of the compressed
description length of its emitted program, and a tenth of the token
count. H1 is a statement about the space a proposer searches, which is the
token count under the model's vocabulary, so the primary view is the one
that bears on the hypothesis; the gzip view is reported so that the number
is not read as a claim about information content.

## Limits

- The emitted source is the engine's own, generated from the Form; a
  program a person would write in Python may be shorter or longer than the
  emitter's. H1 as the page states it compares the Form with "the
  equivalent emitted source", which is what was measured.
- The runtime prelude is excluded. Including it would add about 86,000
  bytes to every python program and make rho grow without bound for small
  programs, which measures the runtime and not the program.
- 7 programs with no emitted form on any target are excluded.
- The population is the project's own hand-written programs (180 shapes);
  no lifted or model-written program is in it. The next run should add the
  lifted tier when the lift pipeline is public.

# v2: typed negatives, the intent mutation score and the cost of a check (2026-10-23)

Registered as the amendment of 2026-10-23T15:00 (committed at `69b2971`
before the run). Generator `scripts/corpus.py` at openIE-dev/rce commit
`2abed988`; the same population and seed as v1, so the 180 shapes, the
vocabularies and every rho statistic are unchanged (python median 9.31).

## Mutants

2,084 mutants of the 180 programs: 540 whitespace-token mutants (three per
program) and 1,544 typed mutants (two per operator per program where the
operator applies). Outcomes:

| outcome | token | rename | operator | literal | guard | type | all |
|---|---|---|---|---|---|---|---|
| refused, other rule | 535 | 291 | 59 | 15 | 158 | 272 | 1,330 |
| caught by the program's examples (W-INT-1) | 0 | 2 | 103 | 85 | 0 | 4 | 194 |
| accepted, program has no examples | 4 | 52 | 166 | 204 | 2 | 39 | 467 |
| accepted, equivalent (same trace heads) | 0 | 13 | 14 | 30 | 0 | 15 | 72 |
| accepted, behaviour change not caught | 0 | 0 | 2 | 18 | 0 | 0 | 20 |
| accepted, same shape | 1 | 0 | 0 | 0 | 0 | 0 | 1 |

The refusals now span 24 diagnostic codes (v1: 3): W-SYN-1 609, W-TY-1
228, W-INT-1 194, W-NAME-1 142, W-UNUSED-1 99, W-UNUSED-2 90, W-TY-3 89,
W-NAME-3 16, W-STEP-1 10, and 15 codes with fewer rows. The typed operators
produce the typing, naming and hygiene negatives the card's v1 gap asked
for; the token operator still produces syntax errors almost only.

## The intent mutation score

For a program with example lines, a mutant that changes behaviour is
either caught by those lines (the checker refuses it with W-INT-1) or
accepted with different trace heads. Over the 37 programs with at least one
such mutant: median score 1.00 (20 of 37 programs catch every
behaviour-changing mutant); pooled, 89 of 109 behaviour changes are caught
(0.82, Wilson 95% 0.73 to 0.88). The 20 uncaught changes are 18 literal
mutations (a constant moved by one that no example exercises) and 2
operator swaps; the lowest scores are two harvested host-contract tests
(0 of 1 each), whose examples cover the host entries and not the value in
question.

Read with its limits: the operators are two per class per program, so a
score is over at most ten mutants; 467 accepted mutants belong to programs
with no example lines and are unscored; "equivalent" means equal trace
heads on the examples' events, not proved equivalence. The number says
what dim-r2 raised from the other side: the example lines of these
programs pin most, not all, of the behaviour they describe, and the gap is
concentrated in constants. It is the first measurement the RCE-JEPA page
can use for RJ-F2 (what an intent block costs against what it buys) and
for H7's premise that the gate, not the model, decides.

## The cost of a check (the checker side of H2)

`rce check` alone, release build, one program: median 3.0 ms
(interquartile range 2.6 to 3.8 ms; largest 1.19 s for the IDNA tables).
At a stated 10 W that is 0.03 J per candidate, labelled an estimate with
no meter. H2 compares this with the model's energy per candidate on the
same hardware, which cannot be measured here; the checker side is recorded
so that the ratio can be formed when the model side exists.

# v3: ten typed mutants per operator for programs with examples (2026-10-23)

Registered as the amendment of 2026-10-23T16:50 (committed at `bd5c190`
before the run). Generator at openIE-dev/rce `de2b38b6` (PR #11); same
population and seed, so the 180 shapes and every rho statistic are
unchanged (python median 9.31); `rce check` median 3.1 ms.

2,766 mutants (v2: 2,084): 2,051 refused across 29 diagnostic codes, 715
accepted (409 on programs without examples, 240 equivalent on the
examples' events, 66 behaviour changes the examples did not catch, 1 with
the parent's shape). Traceable accepted mutants rose from 92 to 306.

**Intent mutation score, v3.** Over the 41 programs with at least one
scorable mutant: median 0.82 (13 of 41 catch every behaviour change);
pooled, 240 of 306 behaviour changes are caught (0.78, Wilson 95% 0.73 to
0.83). The uncaught 66 are 62 literal moves and 4 operator swaps. With
five times the mutants the pooled estimate moved from 0.82 (v2, 109
changes) to 0.78 and its interval narrowed; the picture is the same: the
example lines of these programs pin about four fifths of the behaviour
changes a one-token edit can make, and almost every miss is a constant
no example exercises. That is the number RJ-F2 and H7 should carry
forward, with its limit: ten mutants per operator over a corpus of 180
programs, 41 of them scorable.

# v4: the twelve two-region programs join the corpus (2026-10-24)

Registered as the amendment of 2026-10-24T00:50 (committed before the run).
Generator at openIE-dev/rce `ffaceec0`, whose `programs/multi/` holds the
twelve programs authored for dim-r5; the population rule is unchanged and
admits them. 192 distinct shapes (v3: 180), 55 with an intent block (v3:
43), split 151 / 17 / 24.

- **H1** on 185 programs with an emitted form: python median 9.34
  (interquartile range 8.45 to 10.81; v3: 9.31 on 173), gzip view 3.57.
  The twelve new programs sit inside the old range (8.1 to 11.0 on
  python). The vocabulary term and the thresholds are unchanged.
- **Negatives**: 3,113 mutants (2,287 refused across 31 diagnostic codes,
  826 accepted: 348 equivalent, 75 uncaught behaviour changes).
- **Intent mutation score**: 54 scorable programs (v3: 41); median 0.91,
  24 programs catch every behaviour change; pooled 317 of 392 (0.81,
  Wilson 95% 0.77 to 0.85). The twelve new programs score 1.00 on ten and
  0.91 and 0.86 on two (`card`: one literal move uncaught; `session`: one),
  with 3 to 13 behaviour-changing mutants each. Their example lines were
  written with refusals in mind, which is where the score comes from.
- `rce check` median 3.2 ms per program.
