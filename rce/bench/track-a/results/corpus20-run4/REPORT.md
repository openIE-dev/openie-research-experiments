# Track A: track-a-corpus20-2026-10-10

prereg sha256 `e7dbd27f12b8f2f7f9dcdc4b5d75aae2f3637bf26dc94e34d7b450fcd7c75ed0` (registered 2026-10-10)

| task | solver | solved | test exit | ms | diff bytes | measured |
|---|---|---|---|---|---|---|
| strsim-levenshtein-row | none | false | Some(101) | 526 | 0 | — |
| strsim-levenshtein-row | gold | true | Some(0) | 650 | 367 | — |
| strsim-levenshtein-row | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 10019 | 1148638 | — |
| strsim-osa-cost | none | false | Some(101) | 505 | 0 | — |
| strsim-osa-cost | gold | true | Some(0) | 469 | 606 | — |
| strsim-osa-cost | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 15875 | 1736555 | — |
| strsim-jaro-lower-bound | none | false | Some(101) | 817 | 0 | — |
| strsim-jaro-lower-bound | gold | true | Some(0) | 511 | 518 | — |
| strsim-jaro-lower-bound | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 12205 | 1568571 | — |
| strsim-jaro-upper-bound | none | false | Some(101) | 464 | 0 | — |
| strsim-jaro-upper-bound | gold | true | Some(0) | 526 | 432 | — |
| strsim-jaro-upper-bound | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1879 | 225189 | — |
| strsim-damerau-match | none | false | Some(101) | 463 | 0 | — |
| strsim-damerau-match | gold | true | Some(0) | 505 | 500 | — |
| strsim-damerau-match | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(101) | 70259 | 103329 | — |
| heck-final-sigma | none | false | Some(101) | 423 | 0 | — |
| heck-final-sigma | gold | true | Some(0) | 444 | 492 | — |
| heck-final-sigma | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(101) | 11783 | 895709 | — |
| heck-capitalize-rest | none | false | Some(101) | 407 | 0 | — |
| heck-capitalize-rest | gold | true | Some(0) | 425 | 446 | — |
| heck-capitalize-rest | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(101) | 10711 | 869395 | — |
| shlex-backslash-newline | none | false | Some(101) | 364 | 0 | — |
| shlex-backslash-newline | gold | true | Some(0) | 344 | 487 | — |
| shlex-backslash-newline | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(101) | 113867 | 77225 | — |
| shlex-newline-split | none | false | Some(101) | 324 | 0 | — |
| shlex-newline-split | gold | true | Some(0) | 344 | 497 | — |
| shlex-newline-split | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(101) | 134318 | 78958 | — |
| shlex-error-none | none | false | Some(101) | 309 | 0 | — |
| shlex-error-none | gold | true | Some(0) | 324 | 486 | — |
| shlex-error-none | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(101) | 287084 | 76921 | — |
| shlex-lineno | none | false | Some(101) | 323 | 0 | — |
| shlex-lineno | gold | true | Some(0) | 344 | 397 | — |
| shlex-lineno | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 8589 | 1842861 | — |
| packaging-minor | none | false | Some(1) | 42 | 0 | — |
| packaging-minor | gold | true | Some(0) | 63 | 441 | — |
| packaging-minor | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 223 | 441 | — |
| packaging-micro | none | false | Some(1) | 42 | 0 | — |
| packaging-micro | gold | true | Some(0) | 62 | 433 | — |
| packaging-micro | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 806 | 433 | — |
| packaging-postrelease | none | false | Some(1) | 42 | 0 | — |
| packaging-postrelease | gold | true | Some(0) | 63 | 415 | — |
| packaging-postrelease | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 203 | 415 | — |
| packaging-dev-of-post | none | false | Some(1) | 42 | 0 | — |
| packaging-dev-of-post | gold | true | Some(0) | 62 | 669 | — |
| packaging-dev-of-post | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(1) | 62800 | 0 | — |
| packaging-sdist-dash | none | false | Some(1) | 62 | 0 | — |
| packaging-sdist-dash | gold | true | Some(0) | 83 | 578 | — |
| packaging-sdist-dash | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 21933 | 578 | — |
| packaging-wheel-build | none | false | Some(1) | 62 | 0 | — |
| packaging-wheel-build | gold | true | Some(0) | 84 | 441 | — |
| packaging-wheel-build | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(1) | 27396 | 0 | — |
| packaging-canonical-lower | none | false | Some(1) | 62 | 0 | — |
| packaging-canonical-lower | gold | true | Some(0) | 83 | 544 | — |
| packaging-canonical-lower | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(1) | 16618 | 0 | — |
| idna-label-length | none | false | Some(1) | 61 | 0 | — |
| idna-label-length | gold | true | Some(0) | 62 | 327 | — |
| idna-label-length | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 243 | 328 | — |
| idna-string-length | none | false | Some(1) | 41 | 0 | — |
| idna-string-length | gold | true | Some(0) | 62 | 436 | — |
| idna-string-length | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(1) | 15505 | 0 | — |

## Task validity (gold solves, none does not)

- strsim-levenshtein-row: valid
- strsim-osa-cost: valid
- strsim-jaro-lower-bound: valid
- strsim-jaro-upper-bound: valid
- strsim-damerau-match: valid
- heck-final-sigma: valid
- heck-capitalize-rest: valid
- shlex-backslash-newline: valid
- shlex-newline-split: valid
- shlex-error-none: valid
- shlex-lineno: valid
- packaging-minor: valid
- packaging-micro: valid
- packaging-postrelease: valid
- packaging-dev-of-post: valid
- packaging-sdist-dash: valid
- packaging-wheel-build: valid
- packaging-canonical-lower: valid
- idna-label-length: valid
- idna-string-length: valid

## Resolved and LLM calls

| solver | resolved | of | LLM calls | LLM calls per resolved | by gear |
|---|---|---|---|---|---|
| cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | 10 | 20 | 31 | 3.10 | G1-rules 9, G2-local-llm 1 |
| gold | 20 | 20 | 0 | 0.00 | n/a 20 |
| none | 0 | 20 | 0 | n/a |  |

Hypotheses (written before the run):
- H1: all 20 tasks are valid: gold solves, none does not.
- H2: the RCE solver resolves at least 10 of 20.
- H3: G1 rules resolve the single-site comparison, None-test and literal regressions with zero LLM calls; the local model is reached only when G1 fails.
