# Summary: jetson-hub (second fabric), v2 protocol, part A

Energy label: reported_j (Intel RAPL package-0 on-chip energy model/sensor, idle baseline power x time subtracted, agent pinned to CPU 4, one episode at a time). measured_j: empty, no wall meter.

| arm | B/J_g2 | closed of 30 | X bits | J reported | iota bits/J | CV iota | refused | cut | overspends |
|---|---|---|---|---|---|---|---|---|---|
| sigma | 0.5 | 0.00 | 0 | 0.0018 | 0 | n/a | 30.00 | 0.00 | 323 |
| sigma | 1.0 | 0.00 | 0 | 0.0002 | 0 | n/a | 30.00 | 0.00 | 322 |
| sigma | 2.0 | 1.00 ± 0.39 | 181 ± 71 | 0.0018 ± 0.0336 | 14427 ± 18680 | 1.295 | 29.00 | 0.00 | 322 |
| mol | 0.5 | 0.00 | 0 | -0.0008 | 0 | n/a | 30.00 | 0.00 | 326 |
| mol | 1.0 | 0.00 | 0 | -0.0005 | 0 | n/a | 30.00 | 0.00 | 324 |
| mol | 2.0 | 1.00 ± 0.51 | 181 ± 91 | 0.0107 ± 0.0286 | 15451 ± 23767 | 1.538 | 29.00 | 0.00 | 320 |
| blind | 0.5 | 0.00 | 0 | 0.0026 | 0 | n/a | 0.00 | 30.00 | 327 |
| blind | 1.0 | 0.00 | 0 | 0.0009 | 0 | n/a | 0.00 | 30.00 | 323 |
| blind | 2.0 | 0.28 ± 0.45 | 50 ± 82 | 0.0019 ± 0.0180 | 3801 ± 13749 | 3.618 | 0.00 | 28.90 | 321 |

## Binding

{"0.5": {"pilot_frac_exceeding": 0.6466666666666666, "binding": true}, "1.0": {"pilot_frac_exceeding": 0.4, "binding": true}, "2.0": {"pilot_frac_exceeding": 0.35333333333333333, "binding": true}}

## Ranking

{"0.5": {"by_jstar": ["sigma", "mol", "blind"], "by_iota": ["sigma", "mol", "blind"], "agree": true, "tasks_closed": {"sigma": 0, "mol": 0, "blind": 0}, "common_tasks": 0, "sum_median_jstar_common": {"sigma": 0, "mol": 0, "blind": 0}}, "1.0": {"by_jstar": ["sigma", "mol", "blind"], "by_iota": ["sigma", "mol", "blind"], "agree": true, "tasks_closed": {"sigma": 0, "mol": 0, "blind": 0}, "common_tasks": 0, "sum_median_jstar_common": {"sigma": 0, "mol": 0, "blind": 0}}, "2.0": {"by_jstar": ["sigma", "mol", "blind"], "by_iota": ["mol", "sigma", "blind"], "agree": false, "tasks_closed": {"sigma": 1, "mol": 1, "blind": 0}, "common_tasks": 0, "sum_median_jstar_common": {"sigma": 0, "mol": 0, "blind": 0}}}

## F1 paired

{"0.5": {"n_tasks": 0}, "1.0": {"n_tasks": 0}, "2.0": {"n_tasks": 1, "mean_diff_j": -0.00523892747361652, "median_diff_j": -0.00523892747361652, "ci95": [-0.00523892747361652, -0.00523892747361652], "wilcoxon_z": -1.0, "wilcoxon_p": 0.31731050786291415, "closed_sigma": 1, "closed_mol": 1}}

## Acts

{"n_acts": 137, "kendall_tau_b_est_vs_reported": 0.3683964469378214, "n_tau": 93, "confirmed_acts": 91, "min_distance_to_floor": -1.3190010889140466e+17, "median_distance_to_floor": 9590908723703414.0, "iota_act_median": 18135.931565863437, "iota_act_q25_q75": [10949.152723193714, 42751.50623148866], "zero_reported_acts": 44}

## Refusal

{"infeasible_pairs": 88, "recall_on_infeasible": 1.0, "refusals": 7120, "share_on_tasks_closed_by_some_arm": 0.0011235955056179776}

## Falsifiers

- R-F1: v2 fired=False; v1 fired=True (sigma-law selector closes tasks in fewer joules than Mixture of Limits)
- R-F2: v2 fired=True; v1 fired=True (refusal implementation (zero overspends))
- R-F3: v2 fired=False; v1 fired=True (refusal correctness)
- R-F4: v2 fired=True; v1 fired=False (cycle-count est_j model usable for ranking)
- R-F5: v2 fired=True; v1 fired=True (iota is stable across seeds at run granularity)
- R-F6: v2 fired=True; v1 fired=True (ranking by J* equals ranking by integrated iota)
- R-F7: v2 fired=True; v1 fired=False (the accounting (no act below k_B T ln 2 per bit))
- R-F8: v2 fired=True; v1 fired=False (prediction first, comparison and refusal raise iota over a goal-blind agent)

## Paired by seed (declared in advance)

{"0.5": {"closed_diff_mean": 0, "closed_diff_ci95": [0, 0], "iota_diff_mean": 0.0, "iota_diff_ci95": [0.0, 0.0], "n_seeds": 40, "seeds_sigma_more": 0, "seeds_tied": 40}, "1.0": {"closed_diff_mean": 0, "closed_diff_ci95": [0, 0], "iota_diff_mean": 0.0, "iota_diff_ci95": [0.0, 0.0], "n_seeds": 40, "seeds_sigma_more": 0, "seeds_tied": 40}, "2.0": {"closed_diff_mean": 0, "closed_diff_ci95": [-0.15, 0.15], "iota_diff_mean": 1327.69193382958, "iota_diff_ci95": [-8971.149377306747, 12580.596798691186], "n_seeds": 40, "seeds_sigma_more": 5, "seeds_tied": 30}}

overspend max fraction: 10.85534
close_j: {'max': 0.04243124208915557, 'median': -4.451010075085231e-05}

## Jetson additions (reported; only R-F4_part_B fires, part B only)

```json
{
 "setup": {
  "meter": "Linux powercap intel-rapl:0 (package-0) energy_uj, idle-subtracted (P_idle x dt), agent pinned",
  "cycles_source": "perf cpu_core raw 0x3c user cycles, this thread",
  "affinity": [
   4
  ],
  "no_turbo": "1",
  "governors": [
   "powersave"
  ],
  "epp": [
   "performance"
  ],
  "min_max_khz": [
   [
    "1900000",
    "1900000"
   ],
   [
    "2600000",
    "2600000"
   ]
  ],
  "agent_cpu_avg_freq_khz": {
   "n": 720,
   "min": 400000,
   "q25": 2592744,
   "median": 2600000,
   "q75": 2600000,
   "max": 2600210
  },
  "quiet_window": "no",
  "probes": 40,
  "probe_others_cores": [
   3.56,
   11.244,
   1.226,
   1.042,
   1.568,
   1.83,
   5.235,
   4.913,
   17.931,
   2.034,
   1.012,
   4.411,
   1.016,
   1.012,
   19.964,
   1.274,
   1.79,
   6.609,
   1.142,
   1.094,
   1.012,
   1.016,
   1.01,
   1.004,
   1.07,
   1.008,
   1.036,
   1.014,
   1.014,
   1.008,
   1.038,
   1.008,
   1.012,
   1.008,
   1.01,
   1.01,
   13.988,
   3.92,
   6.723,
   1.01
  ],
  "probe_package_w": [
   10.726,
   20.494,
   5.106,
   5.441,
   5.408,
   5.919,
   13.432,
   12.831,
   27.296,
   4.416,
   2.445,
   9.716,
   2.401,
   4.465,
   28.656,
   5.049,
   5.881,
   14.398,
   2.937,
   5.379,
   3.268,
   4.689,
   3.455,
   2.335,
   2.658,
   2.336,
   3.186,
   3.536,
   2.353,
   4.769,
   2.479,
   4.736,
   2.328,
   4.751,
   2.334,
   4.398,
   22.167,
   11.629,
   14.054,
   5.48
  ],
  "idle_pre": {
   "seconds": 60.003652578,
   "package-0_j": 240.649347,
   "core_j": 84.092009,
   "psys_j": 12.250396,
   "others_cores": 0.9839390021296162,
   "package_w": 4.010578300832185
  },
  "idle_post": {
   "seconds": 60.000597598,
   "package-0_j": 333.242861,
   "core_j": 156.150235,
   "psys_j": 12.205657,
   "others_cores": 2.0284706647684465,
   "package_w": 5.553992365754504
  },
  "baseline_drift_package_w": 1.5434140649223194,
  "block_baseline_w": {
   "n": 360,
   "min": 2.338098128472035,
   "q25": 3.1973123782074637,
   "median": 4.30188549998287,
   "q75": 5.865084816580494,
   "max": 28.100129461004915
  },
  "block_baseline_core_w": {
   "n": 360,
   "min": 0.007017076622806228,
   "q25": 0.02074575171151652,
   "median": 0.6093944396887364,
   "q75": 2.19059129578889,
   "max": 23.533636765952856
  },
  "block_others_cores": {
   "n": 360,
   "min": 0.0,
   "q25": 0.0,
   "median": 1.1069782667970014,
   "q75": 2.288296125994384,
   "max": 19.71320089630342
  },
  "baseline_others_cores": {
   "n": 360,
   "min": 0.0,
   "q25": 0.029984582285132948,
   "median": 0.9995114443945097,
   "q75": 1.3997041787308349,
   "max": 19.133768014663158
  },
  "quiet_blocks": 98,
  "blocks": 360,
  "gate_met": 180,
  "main_run_s": 1888.350581407547,
  "pilot_idle_baseline_w": 18.370329166689164,
  "open_threshold_j": 0.11702807591377287,
  "step_floor_j": 0.03835108920673284,
  "close_reserve_j_locked": 0.04032589750030719,
  "close_reserve_j_final": 0.06364686313373336,
  "refusal_quantile": 0.5,
  "J_g2_median": {
   "n": 30,
   "min": -0.011039428868771854,
   "q25": -0.0018894165801541657,
   "median": 0.009667335706026021,
   "q75": 0.025787234219986778,
   "max": 0.09135608777200008
  },
  "tasks_with_budget_below_open_threshold": {
   "0.5": 30,
   "1.0": 30,
   "2.0": 28
  }
 },
 "rapl_quantisation": {
  "episodes": 10800,
  "zero_gross_package_episodes": 10075,
  "nonpositive_reported_episodes": 10549,
  "episode_seconds": {
   "n": 10800,
   "min": 3.5998e-05,
   "q25": 3.7943e-05,
   "median": 4.0068e-05,
   "q75": 5.7483e-05,
   "max": 0.027193316
  }
 },
 "crosscheck": {
  "block_package_net_j_total": 3.445367401907013,
  "sum_episode_reported_j_total": 2.7370383127038904,
  "ratio_episodes_to_block_net": 0.7944111595149295,
  "block_core_net_j_total": 1.7278374927010807,
  "core_net_over_package_net": 0.501495861296163,
  "core_share_of_package_gross": {
   "n": 360,
   "min": 0.012493173129437466,
   "q25": 0.11629324798049077,
   "median": 0.22544748555734442,
   "q75": 0.4295853788371681,
   "max": 0.851534837384031
  },
  "psys_over_package_gross": {
   "n": 360,
   "min": 0.004417355621266068,
   "q25": 0.02539376406300225,
   "median": 0.03422543903944342,
   "q75": 0.042402186551500236,
   "max": 0.06762749445676275
  },
  "idle_pre_w": 4.010578300832185,
  "idle_post_w": 5.553992365754504,
  "drift_x_main_run_s_j": 3.418105678948658,
  "achievable": false,
  "note": "package net = block gross package joules minus that block's idle baseline power x block seconds; episode reported_j is the same quantity per episode; the gap is harness work between episodes."
 },
 "per_act": {
  "acts": 137,
  "confirmed": 91,
  "reported_j_all_acts": {
   "n": 137,
   "min": -0.06842250900080071,
   "q25": -0.0004936446731233484,
   "median": 0.003899432350191795,
   "q75": 0.01425256156493062,
   "max": 0.057517600897987714
  },
  "reported_j_confirmed": {
   "n": 91,
   "min": -0.06842250900080071,
   "q25": -0.0014932886056806122,
   "median": 0.0049752350016158235,
   "q75": 0.01425256156493062,
   "max": 0.057517600897987714
  },
  "nonpositive_confirmed": 26,
  "j_per_bit_confirmed": {
   "n": 91,
   "min": -0.00037868242756680724,
   "q25": -8.264563263097665e-06,
   "median": 2.7535296434469836e-05,
   "q75": 7.888039610459387e-05,
   "max": 0.0003183295242156915
  },
  "multiples_of_kTln2_confirmed": {
   "n": 91,
   "min": -1.3190010889140466e+17,
   "q25": -2878656929889279.5,
   "median": 9590908723703414.0,
   "q75": 2.7475087509196684e+16,
   "max": 1.108783926869468e+17
  },
  "multiples_of_kTln2_positive_only": {
   "n": 65,
   "min": 1790377783815225.5,
   "q25": 8375806175710039.0,
   "median": 1.9205699666519596e+16,
   "q75": 3.151775627014159e+16,
   "max": 1.108783926869468e+17
  }
 },
 "quiet_block_sensitivity": {
  "sigma@0.5": {
   "n_blocks": 14,
   "closed_mean": 0,
   "iota_mean": 0.0,
   "iota_sd": 0.0
  },
  "sigma@1.0": {
   "n_blocks": 10,
   "closed_mean": 0,
   "iota_mean": 0.0,
   "iota_sd": 0.0
  },
  "sigma@2.0": {
   "n_blocks": 8,
   "closed_mean": 1,
   "iota_mean": 37150.1147224319,
   "iota_sd": 24477.848526868285
  },
  "mol@0.5": {
   "n_blocks": 10,
   "closed_mean": 0,
   "iota_mean": 0.0,
   "iota_sd": 0.0
  },
  "mol@1.0": {
   "n_blocks": 11,
   "closed_mean": 0,
   "iota_mean": 0.0,
   "iota_sd": 0.0
  },
  "mol@2.0": {
   "n_blocks": 13,
   "closed_mean": 1.0769230769230769,
   "iota_mean": 30140.72982070144,
   "iota_sd": 28679.794134033993
  },
  "blind@0.5": {
   "n_blocks": 9,
   "closed_mean": 0,
   "iota_mean": 0.0,
   "iota_sd": 0.0
  },
  "blind@1.0": {
   "n_blocks": 7,
   "closed_mean": 0,
   "iota_mean": 0.0,
   "iota_sd": 0.0
  },
  "blind@2.0": {
   "n_blocks": 16,
   "closed_mean": 0.3125,
   "iota_mean": 7337.683524223044,
   "iota_sd": 21019.983576617287
  }
 },
 "vs_mac_v1": {
  "sigma@0.5": {
   "mac_v1_closed": 0.6,
   "jetson_closed": 0,
   "mac_v1_iota": 5254.376716053403,
   "jetson_iota": 0.0,
   "mac_v1_J": 0.020846548200000002,
   "jetson_J": 0.001787972279209718
  },
  "sigma@1.0": {
   "mac_v1_closed": 9.1,
   "jetson_closed": 0,
   "mac_v1_iota": 34454.29328038495,
   "jetson_iota": 0.0,
   "mac_v1_J": 0.04381087055,
   "jetson_J": 0.00022644280179338956
  },
  "sigma@2.0": {
   "mac_v1_closed": 28.4,
   "jetson_closed": 1,
   "mac_v1_iota": 73345.05089385762,
   "jetson_iota": 14426.641957628704,
   "mac_v1_J": 0.0662276315,
   "jetson_J": 0.0018448583760600587
  },
  "mol@0.5": {
   "mac_v1_closed": 0.7,
   "jetson_closed": 0,
   "mac_v1_iota": 6801.07583243979,
   "jetson_iota": 0.0,
   "mac_v1_J": 0.0187763464,
   "jetson_J": -0.0007764953666962864
  },
  "mol@1.0": {
   "mac_v1_closed": 6.45,
   "jetson_closed": 0,
   "mac_v1_iota": 23804.12224938882,
   "jetson_iota": 0.0,
   "mac_v1_J": 0.0446960957,
   "jetson_J": -0.0004944288919233866
  },
  "mol@2.0": {
   "mac_v1_closed": 27.5,
   "jetson_closed": 1,
   "mac_v1_iota": 70417.5261418113,
   "jetson_iota": 15451.088844716114,
   "mac_v1_J": 0.06698783609999999,
   "jetson_J": 0.010658463754349833
  },
  "blind@0.5": {
   "mac_v1_closed": 0.25,
   "jetson_closed": 0,
   "mac_v1_iota": 2775.0287436886756,
   "jetson_iota": 0.0,
   "mac_v1_J": 0.01413027455,
   "jetson_J": 0.002579988912182693
  },
  "blind@1.0": {
   "mac_v1_closed": 3.85,
   "jetson_closed": 0,
   "mac_v1_iota": 24152.594347677492,
   "jetson_iota": 0.0,
   "mac_v1_J": 0.0265751776,
   "jetson_J": 0.0008944330942878155
  },
  "blind@2.0": {
   "mac_v1_closed": 18.25,
   "jetson_closed": 0.275,
   "mac_v1_iota": 92724.38757146311,
   "jetson_iota": 3800.6393918796352,
   "mac_v1_J": 0.0340764357,
   "jetson_J": 0.0019116735994464964
  }
 }
}
```
