# Track A: track-a-corpus20-2026-10-10

prereg sha256 `e7dbd27f12b8f2f7f9dcdc4b5d75aae2f3637bf26dc94e34d7b450fcd7c75ed0` (registered 2026-10-10)

| task | solver | solved | test exit | ms | diff bytes | measured |
|---|---|---|---|---|---|---|
| strsim-levenshtein-row | none | false | Some(101) | 647 | 0 | rapl-idle 3.105e0 J |
| strsim-levenshtein-row | gold | true | Some(0) | 425 | 367 | rapl-idle 6.078e0 J |
| strsim-levenshtein-row | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 6336 | 1160563 | rapl-idle 3.221e1 J |
| strsim-osa-cost | none | false | Some(101) | 364 | 0 | rapl-idle 6.539e0 J |
| strsim-osa-cost | gold | true | Some(0) | 978 | 606 | rapl-idle 1.575e1 J |
| strsim-osa-cost | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 9316 | 2220713 | rapl-idle -4.749e1 J |
| strsim-jaro-lower-bound | none | false | Some(101) | 443 | 0 | rapl-idle 2.923e0 J |
| strsim-jaro-lower-bound | gold | true | Some(0) | 363 | 518 | rapl-idle 8.092e0 J |
| strsim-jaro-lower-bound | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 8902 | 1669480 | rapl-idle 1.465e2 J |
| strsim-jaro-upper-bound | none | false | Some(101) | 545 | 0 | rapl-idle 8.371e0 J |
| strsim-jaro-upper-bound | gold | true | Some(0) | 425 | 432 | rapl-idle -3.738e-1 J |
| strsim-jaro-upper-bound | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1179 | 227896 | rapl-idle 6.403e0 J |
| strsim-damerau-match | none | false | Some(101) | 407 | 0 | rapl-idle 3.590e0 J |
| strsim-damerau-match | gold | true | Some(0) | 742 | 500 | rapl-idle 2.495e0 J |
| strsim-damerau-match | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(101) | 99302 | 104784 | rapl-idle 4.126e0 J |
| heck-final-sigma | none | false | Some(101) | 323 | 0 | rapl-idle 3.262e0 J |
| heck-final-sigma | gold | true | Some(0) | 323 | 492 | rapl-idle 3.109e0 J |
| heck-final-sigma | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(101) | 18548 | 162541 | rapl-idle 1.077e2 J |
| heck-capitalize-rest | none | false | Some(101) | 323 | 0 | rapl-idle 2.662e0 J |
| heck-capitalize-rest | gold | true | Some(0) | 324 | 446 | rapl-idle 3.432e0 J |
| heck-capitalize-rest | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(101) | 17655 | 102257 | rapl-idle 2.031e2 J |
| shlex-backslash-newline | none | false | Some(101) | 325 | 0 | rapl-idle 1.389e0 J |
| shlex-backslash-newline | gold | true | Some(0) | 289 | 487 | rapl-idle 4.795e0 J |
| shlex-backslash-newline | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(101) | 122510 | 77727 | rapl-idle 1.071e3 J |
| shlex-newline-split | none | false | Some(101) | 262 | 0 | rapl-idle 2.972e0 J |
| shlex-newline-split | gold | true | Some(0) | 263 | 497 | rapl-idle 2.623e0 J |
| shlex-newline-split | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(101) | 111291 | 81341 | rapl-idle 1.714e3 J |
| shlex-error-none | none | false | Some(101) | 243 | 0 | rapl-idle 2.784e0 J |
| shlex-error-none | gold | true | Some(0) | 263 | 486 | rapl-idle 3.334e0 J |
| shlex-error-none | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(101) | 111916 | 77424 | rapl-idle 1.575e3 J |
| shlex-lineno | none | false | Some(101) | 244 | 0 | rapl-idle 4.012e0 J |
| shlex-lineno | gold | true | Some(0) | 265 | 397 | rapl-idle 2.925e0 J |
| shlex-lineno | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 5997 | 1843365 | rapl-idle 7.799e1 J |
| packaging-minor | none | false | Some(1) | 101 | 0 | rapl-idle 8.139e-1 J |
| packaging-minor | gold | true | Some(0) | 62 | 441 | rapl-idle 7.144e-1 J |
| packaging-minor | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 363 | 441 | rapl-idle 4.513e0 J |
| packaging-micro | none | false | Some(1) | 82 | 0 | rapl-idle 1.276e0 J |
| packaging-micro | gold | true | Some(0) | 62 | 433 | rapl-idle 5.729e-1 J |
| packaging-micro | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 1626 | 433 | rapl-idle 2.120e1 J |
| packaging-postrelease | none | false | Some(1) | 82 | 0 | rapl-idle 1.037e0 J |
| packaging-postrelease | gold | true | Some(0) | 62 | 415 | rapl-idle 5.885e-1 J |
| packaging-postrelease | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 283 | 415 | rapl-idle 3.794e0 J |
| packaging-dev-of-post | none | false | Some(1) | 82 | 0 | rapl-idle 1.007e0 J |
| packaging-dev-of-post | gold | true | Some(0) | 62 | 669 | rapl-idle 5.271e-1 J |
| packaging-dev-of-post | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(1) | 31498 | 0 | rapl-idle 4.373e2 J |
| packaging-sdist-dash | none | false | Some(1) | 82 | 0 | rapl-idle 1.180e0 J |
| packaging-sdist-dash | gold | true | Some(0) | 81 | 578 | rapl-idle 7.142e-1 J |
| packaging-sdist-dash | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 36831 | 578 | rapl-idle 4.197e2 J |
| packaging-wheel-build | none | false | Some(1) | 82 | 0 | rapl-idle 1.010e0 J |
| packaging-wheel-build | gold | true | Some(0) | 82 | 441 | rapl-idle 7.630e-1 J |
| packaging-wheel-build | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(1) | 43328 | 0 | rapl-idle 6.603e2 J |
| packaging-canonical-lower | none | false | Some(1) | 82 | 0 | rapl-idle 1.079e0 J |
| packaging-canonical-lower | gold | true | Some(0) | 82 | 544 | rapl-idle 6.709e-1 J |
| packaging-canonical-lower | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | false | Some(1) | 24718 | 0 | rapl-idle 3.464e2 J |
| idna-label-length | none | false | Some(1) | 82 | 0 | rapl-idle 1.264e0 J |
| idna-label-length | gold | true | Some(0) | 81 | 327 | rapl-idle 7.449e-1 J |
| idna-label-length | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 322 | 328 | rapl-idle 4.170e0 J |
| idna-string-length | none | false | Some(1) | 82 | 0 | rapl-idle 1.021e0 J |
| idna-string-length | gold | true | Some(0) | 82 | 436 | rapl-idle 5.936e-1 J |
| idna-string-length | cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | true | Some(0) | 43214 | 601 | rapl-idle 1.048e3 J |

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
| cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py" | 11 | 20 | 29 | 2.64 | G1-rules 9, G2-local-llm 2 |
| gold | 20 | 20 | 0 | 0.00 | n/a 20 |
| none | 0 | 20 | 0 | n/a |  |

cmd:python3 "$RCE_ROOT/scripts/track_a_solver.py": reported_j per solved task (rapl-idle): 712.373 J (11 solved)

gold: reported_j per solved task (rapl-idle): 2.907 J (20 solved)

none: reported_j per solved task (rapl-idle): no task solved (5.129e1 J spent)

Hypotheses (written before the run):
- H1: all 20 tasks are valid: gold solves, none does not.
- H2: the RCE solver resolves at least 10 of 20.
- H3: G1 rules resolve the single-site comparison, None-test and literal regressions with zero LLM calls; the local model is reached only when G1 fails.
