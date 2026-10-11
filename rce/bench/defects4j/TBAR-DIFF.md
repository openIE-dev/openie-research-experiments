# G1-J vs TBar PerfectFL, per bug

Plausible counts include correct. TBar partial = its separate partial patches, not counted as fixed here.

| project | bugs | TBar correct | ours correct | TBar plausible | ours plausible |
|---|---|---|---|---|---|
| Lang | 61 | 13 | 3 | 17 | 14 |
| Chart | 26 | 11 | 9 | 13 | 14 |
| Math | 13 | 3 | 1 | 5 | 3 |
| total | 100 | 27 | 13 | 35 | 31 |

| bug | TBar | ours | gap |
|---|---|---|---|
| Lang-6 | correct | correct |  |
| Lang-7 | correct | plausible | WEAKER |
| Lang-10 | correct | plausible | WEAKER |
| Lang-13 | plausible | plausible |  |
| Lang-15 | partial-correct | partial |  |
| Lang-20 | partial-plausible | plausible | OURS ONLY |
| Lang-21 | plausible | - | MISS |
| Lang-22 | correct | plausible | WEAKER |
| Lang-24 | correct | - | MISS |
| Lang-26 | correct | plausible | WEAKER |
| Lang-27 | plausible | - | MISS |
| Lang-30 | partial-plausible | - |  |
| Lang-33 | correct | plausible | WEAKER |
| Lang-39 | correct | plausible | WEAKER |
| Lang-47 | correct | plausible | WEAKER |
| Lang-50 | partial-plausible | - |  |
| Lang-51 | correct | - | MISS |
| Lang-57 | correct | correct |  |
| Lang-58 | plausible | plausible |  |
| Lang-59 | correct | correct |  |
| Lang-63 | correct | plausible | WEAKER |
| Chart-1 | correct | correct |  |
| Chart-4 | correct | correct |  |
| Chart-7 | plausible | plausible |  |
| Chart-8 | correct | correct |  |
| Chart-9 | correct | plausible | WEAKER |
| Chart-11 | correct | correct |  |
| Chart-12 | correct | correct |  |
| Chart-13 | plausible | plausible |  |
| Chart-14 | correct | plausible | WEAKER |
| Chart-16 | partial-plausible | partial |  |
| Chart-18 | partial-correct | partial |  |
| Chart-19 | correct | correct |  |
| Chart-20 | correct | correct |  |
| Chart-22 | partial-plausible | partial |  |
| Chart-24 | correct | correct |  |
| Chart-25 | partial-correct | plausible | OURS ONLY |
| Chart-26 | correct | correct |  |
| Math-1 | partial-plausible | partial |  |
| Math-2 | - | plausible | OURS ONLY |
| Math-3 | plausible | - | MISS |
| Math-4 | correct | correct |  |
| Math-5 | correct | - | MISS |
| Math-8 | plausible | - | MISS |
| Math-11 | correct | plausible | WEAKER |
