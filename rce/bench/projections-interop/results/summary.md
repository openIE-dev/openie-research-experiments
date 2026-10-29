## M1 lines of code (counted lines: not blank, not only a comment)

| program | python emitted total / runtime / program / driver | python hand | python ratio program:hand | js emitted total / runtime / program / driver | js hand | js ratio program:hand | rust emitted total / runtime / program / driver | rust hand | rust ratio program:hand |
|---|---|---|---|---|---|---|---|---|---|
| counter | 2056 / 2017 / 33 / 6 | 11 | 3.0 | 2004 / 1955 / 37 / 12 | 9 | 4.1 | 2120 / 2004 / 109 / 7 | 19 | 5.7 |
| bank | 2074 / 2017 / 51 / 6 | 12 | 4.2 | 2026 / 1955 / 59 / 12 | 12 | 4.9 | 2142 / 2004 / 131 / 7 | 30 | 4.4 |
| multi_region | 2088 / 2017 / 66 / 5 | 16 | 4.1 | 2044 / 1955 / 79 / 10 | 10 | 7.9 | 2160 / 2004 / 151 / 5 | 23 | 6.6 |
| traffic_light | 2080 / 2017 / 58 / 5 | 9 | 6.4 | 2039 / 1955 / 73 / 11 | 5 | 14.6 | 2155 / 2004 / 145 / 6 | 18 | 8.1 |
| door | 2103 / 2017 / 80 / 6 | 18 | 4.4 | 2067 / 1955 / 100 / 12 | 11 | 9.1 | 2186 / 2004 / 175 / 7 | 23 | 7.6 |
| inventory | 2077 / 2017 / 55 / 5 | 13 | 4.2 | 2029 / 1955 / 64 / 10 | 12 | 5.3 | 2146 / 2004 / 137 / 5 | 29 | 4.7 |
| rcedb | 2130 / 2017 / 106 / 7 | 19 | 5.6 | 2095 / 1955 / 127 / 13 | 16 | 7.9 | 2214 / 2004 / 202 / 8 | 29 | 7.0 |
| float_keys | 2070 / 2017 / 47 / 6 | 19 | 2.5 | 2022 / 1955 / 55 / 12 | 11 | 5.0 | 2137 / 2004 / 126 / 7 | 23 | 5.5 |
| all eight | program 496 | 117 | 4.2 | program 594 | 86 | 6.9 | program 1176 | 194 | 6.1 |

Hand-written shared lines (preamble + tail of programs file): python 5, js 2, rust 19.

## M2 glue (counted lines)

| language | file | lines |
|---|---|---|
| python | examples/interop/python/fastapi_app.py | 34 |
| python | examples/interop/python/numpy_drive.py | 18 |
| python | examples/interop/python/rce_host.py | 80 |
| python | examples/interop/python/service.py | 52 |
| python (hand) | examples/interop/hand/python/drive.py | 51 |
| js | examples/interop/js/Program.mjs | 36 |
| js | examples/interop/js/browser_drive.mjs | 22 |
| js | examples/interop/js/rce_host.mjs | 77 |
| js | examples/interop/js/react_drive.mjs | 16 |
| js | examples/interop/js/service.mjs | 40 |
| js (hand) | examples/interop/hand/js/drive.mjs | 32 |
| rust | examples/interop/rust/src/adapter.rs | 100 |
| rust | examples/interop/rust/src/bench.rs | 25 |
| rust | examples/interop/rust/src/main.rs | 98 |
| rust (hand) | examples/interop/hand/rust/src/main.rs | 79 |

Glue lines that name one of the eight programs: js 0, python 0, rust 2.

## M3 per-call cost (ns, median of the repetitions of the mean per call)

### python (3.13.16, 300 passes x 5 repetitions)

| program | emitted decode | emitted step | emitted encode | boundary share | hand decode | hand step | hand encode | step ratio emitted:hand |
|---|---|---|---|---|---|---|---|---|
| counter | 4638 | 10819 | 6712 | 51% | 1006 | 1139 | 5590 | 9.5 |
| bank | 3202 | 14406 | 8293 | 44% | 1364 | 981 | 6224 | 14.7 |
| multi_region | 3236 | 17587 | 21281 | 58% | 3978 | 1915 | 10634 | 9.2 |
| traffic_light | 1799 | 7283 | 9649 | 61% | 1140 | 1093 | 6404 | 6.7 |
| door | 1874 | 8469 | 9388 | 57% | 1147 | 3691 | 4971 | 2.3 |
| inventory | 7636 | 32019 | 19800 | 46% | 1311 | 791 | 11019 | 40.5 |
| rcedb | 6545 | 36633 | 17979 | 40% | 3517 | 1774 | 9750 | 20.6 |
| float_keys | 4082 | 34844 | 29154 | 49% | 1556 | 1123 | 16372 | 31.0 |

### js (v22.22.0, 3000 passes x 5 repetitions)

| program | emitted decode | emitted step | emitted encode | boundary share | hand decode | hand step | hand encode | step ratio emitted:hand |
|---|---|---|---|---|---|---|---|---|
| counter | 1566 | 6954 | 2115 | 35% | 1352 | 878 | 975 | 7.9 |
| bank | 2661 | 5312 | 2444 | 49% | 2493 | 1132 | 1660 | 4.7 |
| multi_region | 2695 | 2528 | 5256 | 76% | 1701 | 459 | 1711 | 5.5 |
| traffic_light | 1332 | 777 | 2116 | 82% | 1434 | 428 | 625 | 1.8 |
| door | 1713 | 4656 | 3206 | 51% | 1615 | 1226 | 1086 | 3.8 |
| inventory | 3783 | 16984 | 5057 | 34% | 3938 | 2162 | 2655 | 7.9 |
| rcedb | 4290 | 20490 | 11476 | 43% | 3224 | 2320 | 3585 | 8.8 |
| float_keys | 4181 | 21742 | 7796 | 36% | 4754 | 1564 | 7446 | 13.9 |

### rust (rustc 1.97.0 (2d8144b78 2026-07-07), 20000 passes x 5 repetitions)

| program | emitted decode | emitted step | emitted encode | boundary share | hand decode | hand step | hand encode | step ratio emitted:hand |
|---|---|---|---|---|---|---|---|---|
| counter | 170 | 262 | 530 | 73% | 169 | 21 | 73 | 12.5 |
| bank | 402 | 841 | 620 | 55% | 524 | 25 | 143 | 33.6 |
| multi_region | 704 | 2966 | 2470 | 52% | 223 | 29 | 311 | 102.3 |
| traffic_light | 215 | 567 | 794 | 64% | 192 | 23 | 288 | 24.7 |
| door | 401 | 458 | 904 | 74% | 154 | 27 | 164 | 17.0 |
| inventory | 778 | 1993 | 920 | 46% | 270 | 161 | 542 | 12.4 |
| rcedb | 734 | 3886 | 1820 | 40% | 342 | 178 | 745 | 21.8 |
| float_keys | 526 | 2720 | 1406 | 42% | 311 | 69 | 935 | 39.4 |

