# Summary

Energy label: reported_j (macOS per-process kernel energy model). measured_j: empty, no wall meter.

| arm | B/J_g2 | closed of 30 | X bits | J reported | iota bits/J | CV iota | refused | cut | overspends |
|---|---|---|---|---|---|---|---|---|---|
| sigma | 0.5 | 0.60 ± 0.50 | 108 ± 91 | 0.0208 ± 0.0003 | 5254 ± 4402 | 0.838 | 29.40 | 0.00 | 0 |
| sigma | 1.0 | 9.10 ± 1.86 | 1479 ± 316 | 0.0438 ± 0.0040 | 34454 ± 10007 | 0.290 | 20.90 | 0.00 | 9 |
| sigma | 2.0 | 28.40 ± 0.60 | 4823 ± 105 | 0.0662 ± 0.0058 | 73345 ± 6443 | 0.088 | 1.60 | 0.00 | 0 |
| mol | 0.5 | 0.70 ± 0.47 | 126 ± 85 | 0.0188 ± 0.0003 | 6801 ± 4569 | 0.672 | 29.30 | 0.00 | 0 |
| mol | 1.0 | 6.45 ± 1.50 | 1047 ± 254 | 0.0447 ± 0.0036 | 23804 ± 7067 | 0.297 | 23.55 | 0.00 | 7 |
| mol | 2.0 | 27.50 ± 0.51 | 4668 ± 92 | 0.0670 ± 0.0067 | 70418 ± 7766 | 0.110 | 2.50 | 0.00 | 0 |
| blind | 0.5 | 0.25 ± 0.44 | 45 ± 80 | 0.0141 ± 0.0031 | 2775 ± 4999 | 1.801 | 0.00 | 20.35 | 20 |
| blind | 1.0 | 3.85 ± 1.84 | 623 ± 301 | 0.0266 ± 0.0057 | 24153 ± 13364 | 0.553 | 0.00 | 17.45 | 0 |
| blind | 2.0 | 18.25 ± 2.71 | 3034 ± 471 | 0.0341 ± 0.0097 | 92724 ± 15690 | 0.169 | 0.00 | 1.35 | 0 |

## Binding

{"0.5": {"pilot_frac_exceeding": 0.98, "binding": true}, "1.0": {"pilot_frac_exceeding": 0.4, "binding": true}, "2.0": {"pilot_frac_exceeding": 0.006666666666666667, "binding": false}}

## Ranking

{"0.5": {"by_jstar": ["mol", "sigma", "blind"], "by_iota": ["mol", "sigma", "blind"], "agree": true, "tasks_closed": {"sigma": 0, "mol": 1, "blind": 0}, "common_tasks": 0, "sum_median_jstar_common": {"sigma": 0, "mol": 0, "blind": 0}}, "1.0": {"by_jstar": ["sigma", "mol", "blind"], "by_iota": ["sigma", "blind", "mol"], "agree": false, "tasks_closed": {"sigma": 7, "mol": 4, "blind": 1}, "common_tasks": 0, "sum_median_jstar_common": {"sigma": 0, "mol": 0, "blind": 0}}, "2.0": {"by_jstar": ["sigma", "mol", "blind"], "by_iota": ["blind", "sigma", "mol"], "agree": false, "tasks_closed": {"sigma": 28, "mol": 28, "blind": 18}, "common_tasks": 16, "sum_median_jstar_common": {"sigma": 0.016414777, "mol": 0.0170782975, "blind": 0.017615033}}}

## F1 paired

{"0.5": {"n_tasks": 0}, "1.0": {"n_tasks": 4, "mean_diff_j": 3.813749999999997e-06, "median_diff_j": 5.133249999999997e-06, "ci95": [-7.90800000000002e-06, 1.5535500000000014e-05], "wilcoxon_z": 0.7302967433402214, "wilcoxon_p": 0.4652088184521418, "closed_sigma": 7, "closed_mol": 4}, "2.0": {"n_tasks": 26, "mean_diff_j": -7.824655769230771e-05, "median_diff_j": 4.7452500000000136e-06, "ci95": [-0.0003796485769230769, 0.0002003992884615385], "wilcoxon_z": 0.21588280669851348, "wilcoxon_p": 0.8290790993681643, "closed_sigma": 28, "closed_mol": 28}}

## Acts

{"n_acts": 4940, "kendall_tau_b_est_vs_reported": 0.9603870119707338, "n_tau": 4000, "confirmed_acts": 1902, "min_distance_to_floor": 378728028857682.44, "median_distance_to_floor": 2273752995102793.0, "iota_act_median": 153188.7411811187, "iota_act_q25_q75": [82667.16796056963, 466766.634978758], "zero_reported_acts": 0}

## Refusal

{"infeasible_pairs": 41, "recall_on_infeasible": 1.0, "refusals": 2145, "share_on_tasks_closed_by_some_arm": 0.13146853146853146}

## Falsifiers

- R-F1: fired=True (sigma-law selector closes tasks in fewer joules than Mixture of Limits)
- R-F2: fired=True (refusal implementation (zero overspends))
- R-F3: fired=True (refusal correctness)
- R-F4: fired=False (cycle-count est_j model usable for ranking)
- R-F5: fired=True (iota is stable across seeds at run granularity)
- R-F6: fired=True (ranking by J* equals ranking by integrated iota)
- R-F7: fired=False (the accounting (no act below k_B T ln 2 per bit))
- R-F8: fired=False (prediction first, comparison and refusal raise iota over a goal-blind agent)
