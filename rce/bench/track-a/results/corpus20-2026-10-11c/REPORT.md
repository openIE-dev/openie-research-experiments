# Track A: track-a-corpus20-2026-10-11c

prereg sha256 `1f0509b784bade4a2c85d28b90d9a4099ac33470d3d8538b918b31ee84a84462` (registered 2026-10-11)

| task | solver | solved | test exit | ms | diff bytes | measured |
|---|---|---|---|---|---|---|
| strsim-levenshtein-row | none | false | Some(101) | 605 | 0 | — |
| strsim-levenshtein-row | gold | true | Some(0) | 699 | 367 | — |
| strsim-levenshtein-row | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 26552 | 1022706 | — |
| strsim-osa-cost | none | false | Some(101) | 605 | 0 | — |
| strsim-osa-cost | gold | true | Some(0) | 587 | 606 | — |
| strsim-osa-cost | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 50585 | 980953 | — |
| strsim-jaro-lower-bound | none | false | Some(101) | 564 | 0 | — |
| strsim-jaro-lower-bound | gold | true | Some(0) | 589 | 518 | — |
| strsim-jaro-lower-bound | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1953 | 99343 | — |
| strsim-jaro-upper-bound | none | false | Some(101) | 564 | 0 | — |
| strsim-jaro-upper-bound | gold | true | Some(0) | 547 | 432 | — |
| strsim-jaro-upper-bound | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 71936 | 938817 | — |
| strsim-damerau-match | none | false | Some(101) | 544 | 0 | — |
| strsim-damerau-match | gold | true | Some(0) | 545 | 500 | — |
| strsim-damerau-match | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 2101 | 103104 | — |
| heck-final-sigma | none | false | Some(101) | 446 | 0 | — |
| heck-final-sigma | gold | true | Some(0) | 504 | 492 | — |
| heck-final-sigma | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 4819 | 819194 | — |
| heck-capitalize-rest | none | false | Some(101) | 444 | 0 | — |
| heck-capitalize-rest | gold | true | Some(0) | 464 | 446 | — |
| heck-capitalize-rest | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 10542 | 1146918 | — |
| shlex-backslash-newline | none | false | Some(101) | 385 | 0 | — |
| shlex-backslash-newline | gold | true | Some(0) | 384 | 487 | — |
| shlex-backslash-newline | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 19687 | 141117 | — |
| shlex-newline-split | none | false | Some(101) | 385 | 0 | — |
| shlex-newline-split | gold | true | Some(0) | 384 | 497 | — |
| shlex-newline-split | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 26441 | 177470 | — |
| shlex-error-none | none | false | Some(101) | 363 | 0 | — |
| shlex-error-none | gold | true | Some(0) | 364 | 486 | — |
| shlex-error-none | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 2299 | 109128 | — |
| shlex-lineno | none | false | Some(101) | 403 | 0 | — |
| shlex-lineno | gold | true | Some(0) | 465 | 397 | — |
| shlex-lineno | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 61545 | 440876 | — |
| packaging-minor | none | false | Some(1) | 42 | 0 | — |
| packaging-minor | gold | true | Some(0) | 63 | 441 | — |
| packaging-minor | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 204 | 441 | — |
| packaging-micro | none | false | Some(1) | 42 | 0 | — |
| packaging-micro | gold | true | Some(0) | 63 | 433 | — |
| packaging-micro | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1134 | 433 | — |
| packaging-postrelease | none | false | Some(1) | 42 | 0 | — |
| packaging-postrelease | gold | true | Some(0) | 63 | 415 | — |
| packaging-postrelease | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 203 | 415 | — |
| packaging-dev-of-post | none | false | Some(1) | 42 | 0 | — |
| packaging-dev-of-post | gold | true | Some(0) | 63 | 669 | — |
| packaging-dev-of-post | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1591 | 669 | — |
| packaging-sdist-dash | none | false | Some(1) | 62 | 0 | — |
| packaging-sdist-dash | gold | true | Some(0) | 83 | 578 | — |
| packaging-sdist-dash | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 364 | 578 | — |
| packaging-wheel-build | none | false | Some(1) | 62 | 0 | — |
| packaging-wheel-build | gold | true | Some(0) | 83 | 441 | — |
| packaging-wheel-build | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 2294 | 441 | — |
| packaging-canonical-lower | none | false | Some(1) | 62 | 0 | — |
| packaging-canonical-lower | gold | true | Some(0) | 83 | 544 | — |
| packaging-canonical-lower | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 2413 | 544 | — |
| idna-label-length | none | false | Some(1) | 63 | 0 | — |
| idna-label-length | gold | true | Some(0) | 62 | 327 | — |
| idna-label-length | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 264 | 328 | — |
| idna-string-length | none | false | Some(1) | 62 | 0 | — |
| idna-string-length | gold | true | Some(0) | 63 | 436 | — |
| idna-string-length | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 3770 | 436 | — |

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
| cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | 20 | 20 | 0 | 0.00 | G1-rules 20 |
| gold | 20 | 20 | 0 | 0.00 | n/a 20 |
| none | 0 | 20 | 0 | n/a |  |

Hypotheses (written before the run):
- H1: all 20 tasks are valid: gold solves, none does not.
- H2: the RCE solver resolves 20 of 20, each with a patch equal to gold.
- H3: no task reaches the local model, so LLM calls per resolved task is 0.
