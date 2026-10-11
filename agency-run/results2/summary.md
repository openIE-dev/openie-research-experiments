# Summary

Energy label: reported_j (macOS per-process kernel energy model). measured_j: empty, no wall meter.

| arm | B/J_g2 | closed of 30 | X bits | J reported | iota bits/J | CV iota | refused | cut | overspends |
|---|---|---|---|---|---|---|---|---|---|
| sigma | 0.5 | 0.62 ± 0.49 | 113 ± 89 | 0.0595 ± 0.0020 | 1942 ± 1525 | 0.785 | 29.38 | 0.00 | 0 |
| sigma | 1.0 | 2.90 ± 1.74 | 523 ± 314 | 0.1337 ± 0.0138 | 4150 ± 2892 | 0.697 | 27.10 | 0.00 | 0 |
| sigma | 2.0 | 22.73 ± 1.30 | 3980 ± 206 | 0.1973 ± 0.0182 | 20359 ± 2388 | 0.117 | 7.28 | 0.00 | 0 |
| mol | 0.5 | 0.57 ± 0.50 | 104 ± 90 | 0.0601 ± 0.0021 | 1777 ± 1548 | 0.871 | 29.43 | 0.00 | 0 |
| mol | 1.0 | 2.67 ± 1.25 | 483 ± 226 | 0.1403 ± 0.0135 | 3593 ± 1948 | 0.542 | 27.32 | 0.00 | 0 |
| mol | 2.0 | 19.93 ± 1.42 | 3509 ± 227 | 0.2012 ± 0.0204 | 17684 ± 2909 | 0.164 | 10.07 | 0.00 | 0 |
| blind | 0.5 | 0.12 ± 0.33 | 23 ± 61 | 0.0354 ± 0.0116 | 513 ± 1397 | 2.723 | 0.00 | 22.85 | 0 |
| blind | 1.0 | 1.00 ± 0.93 | 181 ± 169 | 0.0720 ± 0.0195 | 2661 ± 2579 | 0.969 | 0.00 | 20.00 | 0 |
| blind | 2.0 | 10.65 ± 2.27 | 1859 ± 400 | 0.0973 ± 0.0301 | 20302 ± 5766 | 0.284 | 0.00 | 8.70 | 0 |

## Binding

{"0.5": {"pilot_frac_exceeding": 0.98, "binding": true}, "1.0": {"pilot_frac_exceeding": 0.4, "binding": true}, "2.0": {"pilot_frac_exceeding": 0.006666666666666667, "binding": false}}

## Ranking

{"0.5": {"by_jstar": ["sigma", "mol", "blind"], "by_iota": ["sigma", "mol", "blind"], "agree": true, "tasks_closed": {"sigma": 1, "mol": 1, "blind": 0}, "common_tasks": 0, "sum_median_jstar_common": {"sigma": 0, "mol": 0, "blind": 0}}, "1.0": {"by_jstar": ["sigma", "mol", "blind"], "by_iota": ["sigma", "mol", "blind"], "agree": true, "tasks_closed": {"sigma": 2, "mol": 1, "blind": 0}, "common_tasks": 0, "sum_median_jstar_common": {"sigma": 0, "mol": 0, "blind": 0}}, "2.0": {"by_jstar": ["sigma", "mol", "blind"], "by_iota": ["sigma", "blind", "mol"], "agree": false, "tasks_closed": {"sigma": 21, "mol": 20, "blind": 8}, "common_tasks": 8, "sum_median_jstar_common": {"sigma": 0.0403423585, "mol": 0.040184971, "blind": 0.039611098}}}

## F1 paired

{"0.5": {"n_tasks": 1, "mean_diff_j": -8.2846000000001e-05, "median_diff_j": -8.2846000000001e-05, "ci95": [-8.2846000000001e-05, -8.2846000000001e-05], "wilcoxon_z": -1.0, "wilcoxon_p": 0.3173105078629141, "closed_sigma": 1, "closed_mol": 1}, "1.0": {"n_tasks": 0}, "2.0": {"n_tasks": 18, "mean_diff_j": -0.00016861702777777764, "median_diff_j": 1.1671250000000076e-05, "ci95": [-0.0005707756666666669, 0.00013249638888888901], "wilcoxon_z": 0.5879298010176119, "wilcoxon_p": 0.5565794125211809, "closed_sigma": 21, "closed_mol": 20}}

## Acts

{"n_acts": 7960, "kendall_tau_b_est_vs_reported": 0.9419406028933061, "n_tau": 4000, "confirmed_acts": 2448, "min_distance_to_floor": 639987693279774.2, "median_distance_to_floor": 1.1210025602064002e+16, "iota_act_median": 31071.584608978177, "iota_act_q25_q75": [14606.353113120149, 41785.352400064505], "zero_reported_acts": 0}

## Refusal

{"infeasible_pairs": 49, "recall_on_infeasible": 1.0, "refusals": 5223, "share_on_tasks_closed_by_some_arm": 0.08098793796668581}

## Falsifiers

- R-F1: v2 fired=False; v1 fired=True (sigma-law selector closes tasks in fewer joules than Mixture of Limits)
- R-F2: v2 fired=False; v1 fired=True (refusal implementation (zero overspends))
- R-F3: v2 fired=False; v1 fired=True (refusal correctness)
- R-F4: v2 fired=False; v1 fired=False (cycle-count est_j model usable for ranking)
- R-F5: v2 fired=True; v1 fired=True (iota is stable across seeds at run granularity)
- R-F6: v2 fired=True; v1 fired=True (ranking by J* equals ranking by integrated iota)
- R-F7: v2 fired=False; v1 fired=False (the accounting (no act below k_B T ln 2 per bit))
- R-F8: v2 fired=False; v1 fired=False (prediction first, comparison and refusal raise iota over a goal-blind agent)

## Paired by seed (declared in advance)

{"0.5": {"closed_diff_mean": 0.05, "closed_diff_ci95": [-0.2, 0.275], "iota_diff_mean": 165.14474320582926, "iota_diff_ci95": [-601.053380072528, 884.3413412429794], "n_seeds": 40, "seeds_sigma_more": 13, "seeds_tied": 16}, "1.0": {"closed_diff_mean": 0.225, "closed_diff_ci95": [-0.425, 0.9], "iota_diff_mean": 556.981075763613, "iota_diff_ci95": [-486.80073535582756, 1656.1302135228436], "n_seeds": 40, "seeds_sigma_more": 18, "seeds_tied": 6}, "2.0": {"closed_diff_mean": 2.8, "closed_diff_ci95": [2.3, 3.275], "iota_diff_mean": 2674.481839444446, "iota_diff_ci95": [1831.0746792639736, 3504.4705812956345], "n_seeds": 40, "seeds_sigma_more": 39, "seeds_tied": 0}}

overspend max fraction: -0.03684
close_j: {'max': 0.000212354, 'median': 2.63825e-05}
