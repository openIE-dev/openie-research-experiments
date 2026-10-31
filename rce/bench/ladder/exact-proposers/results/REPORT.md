# Ladder run: 120 tasks

Checker commit `6d04a0968c9994c691cc959a10b4d5e0e74182a9`, `rce` SHA-256 `eb76277200528fcd1f85714537279bcc7b5fa8d04a8aeb084a38a68d4829502d`, bound 2000 candidates for rung d, task set SHA-256 `78b82b00fb4df9b80420614029a4c8886ec8cd9753bbe2639157ec46e3ebd26e`.

| Rung | Closed |
|---|---:|
| a reuse | 4 |
| b lookup by type | 0 |
| c altered rules (not in this checker) | 0 |
| d bounded enumeration | 114 |
| not closed | 2 |

Closed with zero model calls: 118 of 120 (98.3%).

| Closed repair compared with the original | Tasks |
|---|---:|
| restored | 96 |
| behaviour-equal | 1 |
| examples only | 9 |
| undecided | 1 |
| not compared | 11 |

| Mutation operator | Tasks | Closed |
|---|---:|---:|
| literal | 55 | 54 |
| operator | 64 | 64 |
| rename | 1 | 0 |

Candidates judged by the checker: a 303, b 79, c 0, d 2216 (total 2598).
Wall time: 411.9 s in all, median 2.61 s per task.
