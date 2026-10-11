# Track A: track-a-corpus20-2026-10-11b

prereg sha256 `44394fc6bdced379c4127689440b1a6984e0e5b676a69b5a31065b4623842458` (registered 2026-10-11)

| task | solver | solved | test exit | ms | diff bytes | measured |
|---|---|---|---|---|---|---|
| strsim-levenshtein-row | none | false | Some(101) | 766 | 0 | — |
| strsim-levenshtein-row | gold | true | Some(0) | 566 | 367 | — |
| strsim-levenshtein-row | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 23987 | 728858 | — |
| strsim-osa-cost | none | false | Some(101) | 484 | 0 | — |
| strsim-osa-cost | gold | true | Some(0) | 485 | 606 | — |
| strsim-osa-cost | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 46511 | 1946445 | — |
| strsim-jaro-lower-bound | none | false | Some(101) | 504 | 0 | — |
| strsim-jaro-lower-bound | gold | true | Some(0) | 504 | 518 | — |
| strsim-jaro-lower-bound | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1009 | 99341 | — |
| strsim-jaro-upper-bound | none | false | Some(101) | 503 | 0 | — |
| strsim-jaro-upper-bound | gold | true | Some(0) | 528 | 432 | — |
| strsim-jaro-upper-bound | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 20278 | 938815 | — |
| strsim-damerau-match | none | false | Some(101) | 504 | 0 | — |
| strsim-damerau-match | gold | true | Some(0) | 524 | 500 | — |
| strsim-damerau-match | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1913 | 277718 | — |
| heck-final-sigma | none | false | Some(101) | 504 | 0 | — |
| heck-final-sigma | gold | true | Some(0) | 605 | 492 | — |
| heck-final-sigma | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 4723 | 1001282 | — |
| heck-capitalize-rest | none | false | Some(101) | 423 | 0 | — |
| heck-capitalize-rest | gold | true | Some(0) | 464 | 446 | — |
| heck-capitalize-rest | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 8237 | 1037662 | — |
| shlex-backslash-newline | none | false | Some(101) | 323 | 0 | — |
| shlex-backslash-newline | gold | true | Some(0) | 425 | 487 | — |
| shlex-backslash-newline | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 9443 | 976057 | — |
| shlex-newline-split | none | false | Some(101) | 423 | 0 | — |
| shlex-newline-split | gold | true | Some(0) | 344 | 497 | — |
| shlex-newline-split | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 8392 | 1001236 | — |
| shlex-error-none | none | false | Some(101) | 343 | 0 | — |
| shlex-error-none | gold | true | Some(0) | 363 | 486 | — |
| shlex-error-none | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 4456 | 815502 | — |
| shlex-lineno | none | false | Some(101) | 344 | 0 | — |
| shlex-lineno | gold | true | Some(0) | 383 | 397 | — |
| shlex-lineno | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 53695 | 2154022 | — |
| packaging-minor | none | false | Some(1) | 43 | 0 | — |
| packaging-minor | gold | true | Some(0) | 62 | 441 | — |
| packaging-minor | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 183 | 441 | — |
| packaging-micro | none | false | Some(1) | 42 | 0 | — |
| packaging-micro | gold | true | Some(0) | 63 | 433 | — |
| packaging-micro | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1249 | 433 | — |
| packaging-postrelease | none | false | Some(1) | 42 | 0 | — |
| packaging-postrelease | gold | true | Some(0) | 63 | 415 | — |
| packaging-postrelease | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 183 | 415 | — |
| packaging-dev-of-post | none | false | Some(1) | 42 | 0 | — |
| packaging-dev-of-post | gold | true | Some(0) | 62 | 669 | — |
| packaging-dev-of-post | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 4484 | 669 | — |
| packaging-sdist-dash | none | false | Some(1) | 62 | 0 | — |
| packaging-sdist-dash | gold | true | Some(0) | 83 | 578 | — |
| packaging-sdist-dash | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 243 | 578 | — |
| packaging-wheel-build | none | false | Some(1) | 82 | 0 | — |
| packaging-wheel-build | gold | true | Some(0) | 83 | 441 | — |
| packaging-wheel-build | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1752 | 441 | — |
| packaging-canonical-lower | none | false | Some(1) | 63 | 0 | — |
| packaging-canonical-lower | gold | true | Some(0) | 82 | 544 | — |
| packaging-canonical-lower | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1047 | 544 | — |
| idna-label-length | none | false | Some(1) | 62 | 0 | — |
| idna-label-length | gold | true | Some(0) | 62 | 327 | — |
| idna-label-length | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 224 | 328 | — |
| idna-string-length | none | false | Some(1) | 42 | 0 | — |
| idna-string-length | gold | true | Some(0) | 62 | 436 | — |
| idna-string-length | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1369 | 436 | — |

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

## Solver patches against gold

18 of 20 solver patches leave the edited file byte-identical to gold.
idna-label-length writes `>= 64` for `> 63`. It is equal on integers.
packaging-dev-of-post puts the added conjunct first. It is equal.
shlex-lineno now restores `line_no += 1` in `next_char`.
