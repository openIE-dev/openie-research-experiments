# Track A: track-a-corpus20-2026-10-11b

prereg sha256 `44394fc6bdced379c4127689440b1a6984e0e5b676a69b5a31065b4623842458` (registered 2026-10-11)

| task | solver | solved | test exit | ms | diff bytes | measured |
|---|---|---|---|---|---|---|
| strsim-levenshtein-row | none | false | Some(101) | 729 | 0 | rapl-idle -1.077e0 J |
| strsim-levenshtein-row | gold | true | Some(0) | 364 | 367 | rapl-idle 2.048e0 J |
| strsim-levenshtein-row | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 14449 | 2390078 | rapl-idle 2.010e2 J |
| strsim-osa-cost | none | false | Some(101) | 342 | 0 | rapl-idle 4.403e0 J |
| strsim-osa-cost | gold | true | Some(0) | 343 | 606 | rapl-idle 2.875e0 J |
| strsim-osa-cost | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 28642 | 1966333 | rapl-idle 6.206e2 J |
| strsim-jaro-lower-bound | none | false | Some(101) | 342 | 0 | rapl-idle 1.148e0 J |
| strsim-jaro-lower-bound | gold | true | Some(0) | 342 | 518 | rapl-idle 4.047e0 J |
| strsim-jaro-lower-bound | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1683 | 100793 | rapl-idle 3.284e1 J |
| strsim-jaro-upper-bound | none | false | Some(101) | 342 | 0 | rapl-idle 2.805e-1 J |
| strsim-jaro-upper-bound | gold | true | Some(0) | 507 | 432 | rapl-idle 6.464e0 J |
| strsim-jaro-upper-bound | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 16257 | 948647 | rapl-idle 8.141e1 J |
| strsim-damerau-match | none | false | Some(101) | 383 | 0 | rapl-idle 6.491e-1 J |
| strsim-damerau-match | gold | true | Some(0) | 403 | 500 | rapl-idle 9.814e0 J |
| strsim-damerau-match | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1470 | 280846 | rapl-idle 7.197e0 J |
| heck-final-sigma | none | false | Some(101) | 303 | 0 | rapl-idle -7.545e-1 J |
| heck-final-sigma | gold | true | Some(0) | 302 | 492 | rapl-idle 4.995e0 J |
| heck-final-sigma | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 8510 | 968011 | rapl-idle 8.999e1 J |
| heck-capitalize-rest | none | false | Some(101) | 705 | 0 | rapl-idle -8.777e-1 J |
| heck-capitalize-rest | gold | true | Some(0) | 716 | 446 | rapl-idle -7.676e-2 J |
| heck-capitalize-rest | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 10479 | 1003152 | rapl-idle -9.789e0 J |
| shlex-backslash-newline | none | false | Some(101) | 383 | 0 | rapl-idle 1.149e0 J |
| shlex-backslash-newline | gold | true | Some(0) | 472 | 487 | rapl-idle -1.823e0 J |
| shlex-backslash-newline | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 6919 | 976563 | rapl-idle 1.801e0 J |
| shlex-newline-split | none | false | Some(101) | 244 | 0 | rapl-idle 2.595e0 J |
| shlex-newline-split | gold | true | Some(0) | 283 | 497 | rapl-idle 2.789e0 J |
| shlex-newline-split | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 5875 | 1026918 | rapl-idle 9.568e1 J |
| shlex-error-none | none | false | Some(101) | 262 | 0 | rapl-idle 4.466e-1 J |
| shlex-error-none | gold | true | Some(0) | 325 | 486 | rapl-idle 2.751e0 J |
| shlex-error-none | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 5020 | 816008 | rapl-idle 1.263e2 J |
| shlex-lineno | none | false | Some(101) | 304 | 0 | rapl-idle 7.977e-1 J |
| shlex-lineno | gold | true | Some(0) | 282 | 397 | rapl-idle 1.435e0 J |
| shlex-lineno | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 34841 | 2154528 | rapl-idle 2.811e2 J |
| packaging-minor | none | false | Some(1) | 104 | 0 | rapl-idle 9.814e-1 J |
| packaging-minor | gold | true | Some(0) | 61 | 441 | rapl-idle 7.073e-1 J |
| packaging-minor | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 222 | 441 | rapl-idle -4.878e0 J |
| packaging-micro | none | false | Some(1) | 81 | 0 | rapl-idle 1.377e0 J |
| packaging-micro | gold | true | Some(0) | 62 | 433 | rapl-idle 2.758e-2 J |
| packaging-micro | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 2891 | 433 | rapl-idle 1.991e1 J |
| packaging-postrelease | none | false | Some(1) | 81 | 0 | rapl-idle 1.543e-1 J |
| packaging-postrelease | gold | true | Some(0) | 85 | 415 | rapl-idle -8.775e-3 J |
| packaging-postrelease | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 264 | 415 | rapl-idle 3.973e-1 J |
| packaging-dev-of-post | none | false | Some(1) | 168 | 0 | rapl-idle 1.755e-1 J |
| packaging-dev-of-post | gold | true | Some(0) | 72 | 669 | rapl-idle -3.061e-1 J |
| packaging-dev-of-post | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 10301 | 669 | rapl-idle 3.220e1 J |
| packaging-sdist-dash | none | false | Some(1) | 81 | 0 | rapl-idle 1.042e-1 J |
| packaging-sdist-dash | gold | true | Some(0) | 81 | 578 | rapl-idle 7.015e-1 J |
| packaging-sdist-dash | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 242 | 578 | rapl-idle 5.854e0 J |
| packaging-wheel-build | none | false | Some(1) | 81 | 0 | rapl-idle 1.318e0 J |
| packaging-wheel-build | gold | true | Some(0) | 102 | 441 | rapl-idle 6.487e-1 J |
| packaging-wheel-build | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 2228 | 441 | rapl-idle 3.623e1 J |
| packaging-canonical-lower | none | false | Some(1) | 81 | 0 | rapl-idle 6.363e-1 J |
| packaging-canonical-lower | gold | true | Some(0) | 81 | 544 | rapl-idle 8.990e-1 J |
| packaging-canonical-lower | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1425 | 544 | rapl-idle 3.169e1 J |
| idna-label-length | none | false | Some(1) | 82 | 0 | rapl-idle 1.117e0 J |
| idna-label-length | gold | true | Some(0) | 81 | 327 | rapl-idle 8.523e-1 J |
| idna-label-length | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 222 | 328 | rapl-idle 3.881e0 J |
| idna-string-length | none | false | Some(1) | 82 | 0 | rapl-idle -1.965e-2 J |
| idna-string-length | gold | true | Some(0) | 81 | 436 | rapl-idle 4.065e-1 J |
| idna-string-length | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 2187 | 436 | rapl-idle 3.054e1 J |

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

cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py": reported_j per solved task (rapl-idle): 84.198 J (20 solved)

gold: reported_j per solved task (rapl-idle): 1.962 J (20 solved)

none: reported_j per solved task (rapl-idle): no task solved (1.461e1 J spent)

Hypotheses (written before the run):
- H1: all 20 tasks are valid: gold solves, none does not.
- H2: the RCE solver resolves 20 of 20, each with a patch equal to gold.
- H3: no task reaches the local model, so LLM calls per resolved task is 0.
