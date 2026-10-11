# Ladder results, 2026-10-11 (snapshot 12:10 ET; runs continue resumably)

The numbers below come from frozen engines on TEST splits only (PREREG.json `splits`). DEV tasks (the first 2000 of each
shuffle, plus the three L0 pilot repositories) were used for tuning and are not reported. Model calls: 0 on every row.
Energy: est_j = cpu_s × 10 W, an estimate. The RAPL check on jetson-hub (results/jetson-rapl-2026-10-11) measured 2.5 to 7 J
per CPU-second at package level, idle-subtracted: on L0 it gave 0.056 reported_j per solved task, on L1 0.026.
Full per-stratum tables: results/tables-2026-10-11-1210.md.

| rung | corpus (TEST) | engine | N | solved | rate | Wilson 95% CI | median search bits | est_j / solved |
|---|---|---|---|---|---|---|---|---|
| L0 one token | 9 real repos at pinned commits (Java: commons-math, commons-collections, jsoup, joda-time, gson; Python: click, attrs, pydantic, sympy), PIT-style mutants, valid-token rule | 65571d0 (G0-T, G1-J) | 189,623 (of 547,448; running) | 189,513 | 0.9994 | [0.9993, 0.9995] | 2.3 | 0.45 |
| L1 one statement, Java | ManySStuBs4J 2.0 sstubsLarge, single-hunk fixes | 9ce790e (G0 T/V/M/U/S) | 24,072 (all TEST) | 9,287 | 0.386 | [0.380, 0.392] | 3.5 | 0.08 |
| L1 one statement, Java | same | f2701b7 (+G0-W) | 24,072 | 9,288 | 0.386 | [0.380, 0.392] | 3.5 | 0.10 |
| L1 one statement, Python | TSSB-3M v1.0.0 file-14 | f2701b7 | 72,692 (of 98,592; running) | 12,566 | 0.173 | [0.170, 0.176] | 4.8 | 0.25 |
| L2-L4 | Defects4J | G1-J, run by the Defects4J worker (bench/defects4j) | 100 dev + 288 held-out (FROZEN-heldout-v1) | see bench/defects4j | | | | |
| L5 | HumanEval 164, MBPP | not run yet: work to do | | | | | | |
| L6 | SWE-bench Lite 300, Verified 500 | not run yet: work to do | | | | | | |
| L7 | APPS, Codeflaws programs | not run yet: work to do | | | | | | |

Distinct TEST tasks with a result row: 286,387 (L0 189,623 + L1 ManySStuBs4J 24,072 + L1 TSSB-3M 72,692). The f2701b7 rerun of ManySStuBs4J is not counted twice.

## What the rungs show, read as intent bits

- L0: 99.94% under a token-identity gate (stricter than test-passing). The 110 unsolved are 108 mutated digits inside
  floating literals (1e-6 to 1e-5, hex floats), which G0-T does not enumerate yet, and 2 inside Python set literals.
  Next mechanism: float-literal digit and exponent neighbourhood.
- L1 Java: solved where the bits are on the line or in the hunk: CHANGE_OPERATOR 91%, SWAP_BOOLEAN_LITERAL 84%,
  SWAP_ARGUMENTS 82%, OVERLOAD_METHOD_DELETED_ARGS 79%. Open where the bits are outside the 7-line hunk: method names
  (22%), identifiers (37%), new conjuncts (3-7%). The harness gives RCE only the hunk. A full-file and type-indexed API
  index is the next gear.
- L1 Python: CHANGE_BOOLEAN_LITERAL 98.8%, SAME_FUNCTION_SWAP_ARGS 99.4%, SAME_FUNCTION_LESS_ARGS 91%; open on
  SINGLE_STMT rewrites (1.2%, 34% of the corpus) and new string literals (4%). That is new intent, which a supplier
  (spec, test, person, local model) has to provide once before it is compiled into the index.
- G0-W (f2701b7) gained 61 of 2000 on TSSB DEV and 1 task on ManySStuBs TEST. Its moves are Python-shaped.

Baselines: ManySStuBs4J and TSSB-3M have no repair leaderboard under this gate (hunk only, token identity, location given), so no like-for-like number is quoted here. Learned-repair papers on ManySStuBs4J use other inputs and splits. Defects4J is compared with TBar PerfectFL in bench/defects4j.
