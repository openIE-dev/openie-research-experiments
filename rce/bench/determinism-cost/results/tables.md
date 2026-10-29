Machine: Intel(R) Xeon(R) Processor @ 2.30GHz, 4 logical CPUs, Linux-6.18.44-fc-v185-x86_64-with-glibc2.39; load average at start ['114.21', '236.11', '184.72']; rce ac018204647605986782c72ba3977ef1d9740c17 (tree dirty: False); rustc 1.97.0 (2d8144b78 2026-07-07); 1000 steps per stream, 11 repeats, runs of at least 0.5 s; seed 0x5eedd3ad0007.

### CPU ns per step (median of the repeats)

| program | class | b delta | encode | a chain | chainfast | ckpt64 | a host | host1 | c quiet | c trace quiet | c plain | c trace | d fma | d nofma | d nofma+log |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| bank | arithmetic | 1,148 | 2,236 | 4,880 | 2,838 | 3,660 | 7,016 | 7,452 | 435 | 4,062 | 1,533 | 4,876 | 0.6 | 0.6 | 2,192 |
| ring | arithmetic | 2,753 | 4,189 | 7,016 | 4,737 | 5,664 | 9,291 | 9,291 | 879 | 4,702 | 2,444 | 6,288 | - | - | - |
| automaton | arithmetic | 17,039 | 18,747 | 21,729 | 19,039 | 20,347 | 22,612 | 22,994 | 6,649 | 10,826 | 7,962 | 11,662 | 3.9 | 3.8 | 2,418 |
| inventory | collection | 104,671 | 126,404 | 131,262 | 127,043 | 125,910 | 136,640 | 134,712 | 17,549 | 40,760 | 27,623 | 50,766 | 39.5 | 39.8 | 13,238 |
| rcedb | collection | 76,365 | 95,002 | 98,260 | 91,971 | 96,257 | 103,535 | 107,211 | 25,164 | 49,611 | 36,862 | 60,708 | - | - | - |
| cart | collection | 4,026 | 6,346 | 8,963 | 6,771 | 7,826 | 12,084 | 11,658 | 2,614 | 7,637 | 4,798 | 9,641 | - | - | - |
| arm | float | 1,499 | 5,477 | 8,008 | 5,995 | 6,859 | 11,092 | 10,778 | 555 | 6,331 | 3,549 | 9,641 | 1.7 | 1.1 | 3,009 |
| floatvec | float | 1,385 | 6,759 | 9,745 | 7,513 | 8,204 | 14,628 | 14,470 | 548 | 7,227 | 3,991 | 10,894 | - | - | - |
| fir | float | 23,502 | 38,571 | 41,565 | 39,158 | 40,649 | 46,001 | 46,404 | 9,451 | 27,109 | 22,845 | 39,377 | 159 | 168 | 7,637 |
| elevator | state | 1,634 | 2,609 | 5,240 | 2,986 | 4,088 | 7,323 | 7,490 | 336 | 3,796 | 1,422 | 4,963 | 1.7 | 1.5 | 2,899 |
| lexer | state | 1,365 | 2,648 | 5,397 | 3,129 | 4,047 | 7,640 | 7,395 | 442 | 4,014 | 1,411 | 5,189 | - | - | - |

### Wall ns per step (median of the repeats)

| program | b delta | encode | a chain | chainfast | ckpt64 | a host | host1 | c quiet | c trace quiet | c plain | c trace | d fma | d nofma | d nofma+log |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| bank | 2,263 | 4,313 | 9,786 | 5,001 | 7,541 | 12,143 | 13,610 | 771 | 7,142 | 2,579 | 8,387 | 1.1 | 1.1 | 3,290 |
| ring | 4,144 | 6,076 | 10,876 | 6,888 | 8,394 | 14,347 | 13,605 | 1,368 | 7,153 | 3,645 | 8,842 | - | - | - |
| automaton | 23,494 | 27,049 | 33,586 | 28,994 | 31,005 | 37,841 | 37,530 | 9,764 | 16,556 | 11,683 | 17,609 | 5.7 | 5.6 | 4,156 |
| inventory | 142,452 | 194,428 | 202,254 | 209,378 | 193,087 | 200,989 | 208,509 | 26,444 | 62,883 | 42,547 | 81,769 | 59.4 | 61.7 | 20,143 |
| rcedb | 97,269 | 128,951 | 127,427 | 122,527 | 119,509 | 130,762 | 135,928 | 32,108 | 65,226 | 48,140 | 78,513 | - | - | - |
| cart | 5,131 | 7,964 | 11,821 | 8,809 | 10,086 | 15,665 | 14,958 | 4,183 | 11,576 | 5,286 | 10,951 | - | - | - |
| arm | 2,318 | 9,147 | 12,495 | 8,977 | 10,855 | 17,489 | 17,312 | 831 | 10,468 | 5,711 | 15,497 | 2.6 | 1.7 | 4,969 |
| floatvec | 2,169 | 12,634 | 15,395 | 11,399 | 13,005 | 21,683 | 19,844 | 699 | 9,287 | 6,287 | 16,941 | - | - | - |
| fir | 32,382 | 48,578 | 56,202 | 50,147 | 54,641 | 61,464 | 58,577 | 12,022 | 35,737 | 27,026 | 52,332 | 190 | 210 | 9,403 |
| elevator | 2,068 | 3,139 | 5,738 | 3,257 | 5,218 | 9,568 | 9,808 | 434 | 5,003 | 1,868 | 6,635 | 2.2 | 1.7 | 3,769 |
| lexer | 1,689 | 3,229 | 6,336 | 3,840 | 4,403 | 7,800 | 7,670 | 481 | 4,397 | 1,430 | 5,427 | - | - | - |

### Ratios (CPU)

| program | class | log, checker: a chain / b delta | log, host: a host / b delta | log, emitted: trace quiet / quiet | log, native: nofma+log / nofma | float rule: nofma / fma | emitted / hand: quiet / fma | emitted+log / hand: trace quiet / fma | checker / emitted: b delta / c quiet | chainfast / chain (hex from a table) | ckpt64 / chain |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| bank | arithmetic | 4.25 | 6.11 | 9.33 | 3,583 | 0.99 | 704 | 6,576 | 2.64 | 0.58 | 0.75 |
| ring | arithmetic | 2.55 | 3.37 | 5.35 | - | - | - | - | 3.13 | 0.68 | 0.81 |
| automaton | arithmetic | 1.28 | 1.33 | 1.63 | 632 | 0.98 | 1,699 | 2,766 | 2.56 | 0.88 | 0.94 |
| inventory | collection | 1.25 | 1.31 | 2.32 | 332 | 1.01 | 444 | 1,032 | 5.96 | 0.97 | 0.96 |
| rcedb | collection | 1.29 | 1.36 | 1.97 | - | - | - | - | 3.03 | 0.94 | 0.98 |
| cart | collection | 2.23 | 3.00 | 2.92 | - | - | - | - | 1.54 | 0.76 | 0.87 |
| arm | float | 5.34 | 7.40 | 11.41 | 2,781 | 0.65 | 332 | 3,791 | 2.70 | 0.75 | 0.86 |
| floatvec | float | 7.04 | 10.57 | 13.18 | - | - | - | - | 2.52 | 0.77 | 0.84 |
| fir | float | 1.77 | 1.96 | 2.87 | 45.49 | 1.06 | 59.40 | 170 | 2.49 | 0.94 | 0.98 |
| elevator | state | 3.21 | 4.48 | 11.28 | 1,904 | 0.90 | 199 | 2,241 | 4.86 | 0.57 | 0.78 |
| lexer | state | 3.96 | 5.60 | 9.09 | - | - | - | - | 3.09 | 0.58 | 0.75 |

### Median ratio per class (CPU), classed against the claimed 10x to 100x

| factor | arithmetic | collection | float | state | all |
|---|---|---|---|---|---|
| log, checker: a chain / b delta | 2.55 (below 10x, n=3) | 1.29 (below 10x, n=3) | 5.34 (below 10x, n=3) | 3.58 (below 10x, n=2) | 2.55 (below 10x, n=11) |
| log, host: a host / b delta | 3.37 (below 10x, n=3) | 1.36 (below 10x, n=3) | 7.40 (below 10x, n=3) | 5.04 (below 10x, n=2) | 3.37 (below 10x, n=11) |
| log, emitted: trace quiet / quiet | 5.35 (below 10x, n=3) | 2.32 (below 10x, n=3) | 11.41 (10x to 100x, n=3) | 10.19 (10x to 100x, n=2) | 5.35 (below 10x, n=11) |
| log, native: nofma+log / nofma | 2,107 (above 100x, n=2) | 332 (above 100x, n=1) | 1,413 (above 100x, n=2) | 1,904 (above 100x, n=1) | 1,268 (above 100x, n=6) |
| float rule: nofma / fma | 0.98 (below 10x, n=2) | 1.01 (below 10x, n=1) | 0.85 (below 10x, n=2) | 0.90 (below 10x, n=1) | 0.98 (below 10x, n=6) |
| emitted / hand: quiet / fma | 1,202 (above 100x, n=2) | 444 (above 100x, n=1) | 196 (above 100x, n=2) | 199 (above 100x, n=1) | 388 (above 100x, n=6) |
| emitted+log / hand: trace quiet / fma | 4,671 (above 100x, n=2) | 1,032 (above 100x, n=1) | 1,980 (above 100x, n=2) | 2,241 (above 100x, n=1) | 2,504 (above 100x, n=6) |

### Where the checker's time goes (share of a host, CPU)

| program | delta | JSON encoding | SHA-256 + hex | host bookkeeping | dominant |
|---|---:|---:|---:|---:|---|
| bank | 16% | 16% | 38% | 30% | SHA-256 + hex |
| ring | 30% | 15% | 30% | 24% | SHA-256 + hex |
| automaton | 75% | 8% | 13% | 4% | delta |
| inventory | 77% | 16% | 4% | 4% | delta |
| rcedb | 74% | 18% | 3% | 5% | delta |
| cart | 33% | 19% | 22% | 26% | delta |
| arm | 14% | 36% | 23% | 28% | JSON encoding |
| floatvec | 9% | 37% | 20% | 33% | JSON encoding |
| fir | 51% | 33% | 7% | 10% | delta |
| elevator | 22% | 13% | 36% | 28% | SHA-256 + hex |
| lexer | 18% | 17% | 36% | 29% | SHA-256 + hex |

### est_j per million steps (estimate: CPU seconds x 10 W, paper section 6.3; not measured)

| program | b delta | a chain | a host | c quiet | c trace quiet | d fma | d nofma+log |
|---|---:|---:|---:|---:|---:|---:|---:|
| bank | 11.482 | 48.805 | 70.158 | 4.351 | 40.616 | 0.006 | 21.919 |
| ring | 27.535 | 70.156 | 92.908 | 8.793 | 47.017 | - | - |
| automaton | 170 | 217 | 226 | 66.490 | 108 | 0.039 | 24.182 |
| inventory | 1,047 | 1,313 | 1,366 | 175 | 408 | 0.395 | 132 |
| rcedb | 764 | 983 | 1,035 | 252 | 496 | - | - |
| cart | 40.258 | 89.631 | 121 | 26.139 | 76.369 | - | - |
| arm | 14.987 | 80.080 | 111 | 5.548 | 63.313 | 0.017 | 30.087 |
| floatvec | 13.846 | 97.453 | 146 | 5.484 | 72.272 | - | - |
| fir | 235 | 416 | 460 | 94.512 | 271 | 1.591 | 76.368 |
| elevator | 16.336 | 52.405 | 73.235 | 3.364 | 37.960 | 0.017 | 28.987 |
| lexer | 13.645 | 53.970 | 76.396 | 4.417 | 40.139 | - | - |

### Parity

- bank: chain head `328a2937f39ebce2`; all checks equal
- ring: chain head `7343d29c2f48f189`; all checks equal
- automaton: chain head `09674c487e1c4844`; all checks equal
- inventory: chain head `e622b4d62d4a218f`; all checks equal
- rcedb: chain head `dbcbd00a877f7c12`; all checks equal
- cart: chain head `01136c8b55035b81`; all checks equal
- arm: chain head `74f4f5b23bc87468`; all checks equal
- floatvec: chain head `d34497cb25de5a9c`; all checks equal
- fir: chain head `087c4f46aef5b560`; all checks equal
- elevator: chain head `16de4cca0e70437b`; all checks equal
- lexer: chain head `ca4d688a67ec00f4`; all checks equal
