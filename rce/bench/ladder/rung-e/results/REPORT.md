# Ladder run 3: rungs a to e on the frozen tasks of run 2

`rce` SHA-256 `f7a8f301569ffc83ecba059be65d0abbc6ce673ed186df0b18ed2e02dd0743d1`; task set SHA-256 `6ae255a32211f620364ef713b1a36f7daac6ab46f22ac318b45acb2a6da9af50` (151 tasks); bound 2000; cap 900 s per `rce repair` call.

- plain arm: `rce repair json FILE`
- known arm: `rce repair json known ORIGINAL FILE` (ORIGINAL is the task's original text)

## Closed per rung

### plain arm

| Rung | history-admit (33) | history-fix (8) | guard (27) | rename (83) | all (151) |
|---|---:|---:|---:|---:|---:|
| a | 0 | 0 | 0 | 0 | 0 |
| b | 0 | 0 | 0 | 0 | 0 |
| c | 0 | 1 | 0 | 0 | 1 |
| d | 0 | 0 | 27 | 3 | 30 |
| e | 0 | 0 | 0 | 80 | 80 |
| e by the renaming onto GOOD | 0 | 0 | 0 | 0 | 0 |
| e by search | 0 | 0 | 0 | 80 | 80 |
| closed | 0 | 1 | 27 | 83 | 111 |
| not closed | 33 | 7 | 0 | 0 | 40 |
| of which admitted as given | 0 | 0 | 0 | 0 | 0 |
| of which time cap | 0 | 0 | 0 | 0 | 0 |

| Closed repair compared with the original | history-admit | history-fix | guard | rename | all |
|---|---:|---:|---:|---:|---:|
| restored | 0 | 1 | 25 | 77 | 103 |
| behaviour-equal | 0 | 0 | 0 | 1 | 1 |
| examples only | 0 | 0 | 0 | 3 | 3 |
| undecided | 0 | 0 | 1 | 0 | 1 |
| not compared | 0 | 0 | 1 | 2 | 3 |
| behaves the same (restored + behaviour-equal) | 0 | 1 | 25 | 78 | 104 |

| Candidates judged | history-admit | history-fix | guard | rename | all |
|---|---:|---:|---:|---:|---:|
| a | 2302 | 74 | 171 | 319 | 2866 |
| b | 629 | 72 | 54 | 116 | 871 |
| c | 0 | 1 | 0 | 13 | 14 |
| d | 4402 | 178 | 790 | 4216 | 9586 |
| e | 8589 | 360 | 0 | 877 | 9826 |
| total | 15922 | 685 | 1015 | 5541 | 23163 |

Model calls reported: 0. Originals the pinned checker admits: 149 of 151; mutants it reports as requiring change: 151 of 151. Tasks ended by a signal: 0. Wall time 1072.4 s, median 2.366 s per task, longest 266.67 s.

### known arm

| Rung | history-admit (33) | history-fix (8) | guard (27) | rename (83) | all (151) |
|---|---:|---:|---:|---:|---:|
| a | 0 | 0 | 0 | 0 | 0 |
| b | 0 | 0 | 0 | 0 | 0 |
| c | 0 | 0 | 0 | 0 | 0 |
| d | 0 | 0 | 27 | 0 | 27 |
| e | 0 | 6 | 0 | 83 | 89 |
| e by the renaming onto GOOD | 0 | 6 | 0 | 83 | 89 |
| e by search | 0 | 0 | 0 | 0 | 0 |
| closed | 0 | 6 | 27 | 83 | 116 |
| not closed | 33 | 2 | 0 | 0 | 35 |
| of which admitted as given | 0 | 0 | 0 | 0 | 0 |
| of which time cap | 0 | 0 | 0 | 0 | 0 |

| Closed repair compared with the original | history-admit | history-fix | guard | rename | all |
|---|---:|---:|---:|---:|---:|
| restored | 0 | 6 | 25 | 83 | 114 |
| behaviour-equal | 0 | 0 | 0 | 0 | 0 |
| examples only | 0 | 0 | 0 | 0 | 0 |
| undecided | 0 | 0 | 1 | 0 | 1 |
| not compared | 0 | 0 | 1 | 0 | 1 |
| behaves the same (restored + behaviour-equal) | 0 | 6 | 25 | 83 | 114 |

| Candidates judged | history-admit | history-fix | guard | rename | all |
|---|---:|---:|---:|---:|---:|
| a | 2302 | 2 | 171 | 0 | 2475 |
| b | 629 | 0 | 54 | 0 | 683 |
| c | 0 | 0 | 0 | 0 | 0 |
| d | 4402 | 22 | 790 | 0 | 5214 |
| e | 8589 | 40 | 0 | 83 | 8712 |
| total | 15922 | 64 | 1015 | 83 | 17084 |

Model calls reported: 0. Originals the pinned checker admits: 149 of 151; mutants it reports as requiring change: 151 of 151. Tasks ended by a signal: 0. Wall time 697.6 s, median 0.007 s per task, longest 260.622 s.

## Against run 2 (registered, rungs a to d)

| Source | Run 2 closed | Run 3 plain closed | Run 3 known closed | Run 2 restored | Run 3 plain restored | Run 3 known restored | Run 2 behaves the same | Run 3 plain behaves the same | Run 3 known behaves the same |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| history (41) | 1 | 1 | 6 | 1 | 1 | 6 | 1 | 1 | 6 |
| guard (27) | 27 | 27 | 27 | 25 | 25 | 25 | 25 | 25 | 25 |
| rename (83) | 3 | 83 | 83 | 0 | 77 | 83 | 0 | 78 | 83 |
| guard+rename (110) | 30 | 110 | 110 | 25 | 102 | 108 | 25 | 103 | 108 |
| all (151) | 31 | 111 | 116 | 26 | 103 | 114 | 26 | 104 | 114 |

Tasks whose outcome (closed, rung, equivalence) differs between run 2 and the run 3 plain arm: 80 (history 0, guard 0, rename 80).


Rename tasks closed in the plain arm and not restored:

- `spec/examples/30_state_machine_guarded.rce#rename1` (examples only, rung d): in `Door`, line 7: `false` becomes `true`
- `spec/examples/44_device_region.rce#rename1` (not compared, rung d): in `dot4`, line 5: `a * b` becomes `a + b`
- `spec/examples/61_dim_minimal.rce#rename1` (examples only, rung d): in `DimDoor`, line 7: `false` becomes `true`
- `programs/ecosystem/pqxdh.rce#rename0` (behaviour-equal, rung e): in `step Pqxdh on Forge`, line 79: `ss_i` becomes `f`
- `programs/money/checkout.rce#rename0` (examples only, rung e): in `step Checkout on Place`, line 308: `region9` becomes `promo39`
- `programs/text/json_nest.rce#rename0` (not compared, rung e): in `lex`, line 46: `in_str` becomes `c`

Rename tasks not closed in the plain arm:


## Known arm against plain arm

Tasks whose outcome differs: 12 (rename 6, other 6). Rename tasks whose original the pinned checker admits: 83 of 83.

- `spec/examples/11_arena.rce@013e21ed`: plain ('false', '', ''), known ('true', 'e', 'restored')
- `spec/examples/29_nested_kind.rce@013e21ed`: plain ('true', 'c', 'restored'), known ('true', 'e', 'restored')
- `spec/examples/41_arena_bound_wrapping.rce@013e21ed`: plain ('false', '', ''), known ('true', 'e', 'restored')
- `spec/examples/45_byte_text.rce@013e21ed`: plain ('false', '', ''), known ('true', 'e', 'restored')
- `spec/examples/56_utf8.rce@013e21ed`: plain ('false', '', ''), known ('true', 'e', 'restored')
- `programs/text/edit_distance.rce@29c21674`: plain ('false', '', ''), known ('true', 'e', 'restored')

## Predictions and falsifiers (rules in PREREG.json, evaluated by report.py)

| Prediction | Holds |
|---|---|
| P1 | yes |
| P2 | yes |
| P3 | yes |
| P4 | yes |
| P5 | yes |
| P6 | no |
| P7 | yes |

P5 input: candidates judged on guard and rename tasks, plain arm: 6556.

| Falsifier | Met (claim false on this set) |
|---|---|
| F1 | no |
| F2 | no |
| F3 | no |
| F4 | no |
| F5 | no |
| F6 | no |
