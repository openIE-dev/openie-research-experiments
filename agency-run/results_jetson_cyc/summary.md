# Summary: jetson-hub (second fabric), v2 protocol, part B

Energy label: est_j (agent user cycles x c, c calibrated on Intel RAPL package-0 net of idle over a 20 s window in the pilot); the column says J reported for code reuse but every value is est_j. RAPL validates at block level below. measured_j: empty, no wall meter.

| arm | B/J_g2 | closed of 30 | X bits | J reported | iota bits/J | CV iota | refused | cut | overspends |
|---|---|---|---|---|---|---|---|---|---|
| sigma | 0.5 | 1.10 ± 0.98 | 200 ± 178 | 0.0345 ± 0.0017 | 6027 ± 5458 | 0.906 | 28.90 | 0.00 | 0 |
| sigma | 1.0 | 8.75 ± 3.14 | 1574 ± 565 | 0.0805 ± 0.0098 | 20519 ± 8516 | 0.415 | 21.25 | 0.00 | 0 |
| sigma | 2.0 | 28.60 ± 0.98 | 4882 ± 154 | 0.1008 ± 0.0234 | 50667 ± 10088 | 0.199 | 1.40 | 0.00 | 0 |
| mol | 0.5 | 1.15 ± 0.92 | 208 ± 167 | 0.0366 ± 0.0013 | 5833 ± 4757 | 0.816 | 28.85 | 0.00 | 0 |
| mol | 1.0 | 9.22 ± 3.07 | 1660 ± 551 | 0.0813 ± 0.0106 | 21412 ± 8130 | 0.380 | 20.77 | 0.00 | 0 |
| mol | 2.0 | 27.77 ± 2.30 | 4745 ± 377 | 0.1099 ± 0.0339 | 47108 ± 13216 | 0.281 | 2.23 | 0.00 | 0 |
| blind | 0.5 | 0.20 ± 0.46 | 36 ± 84 | 0.0210 ± 0.0055 | 1722 ± 3927 | 2.280 | 0.00 | 21.50 | 0 |
| blind | 1.0 | 3.73 ± 2.12 | 667 ± 381 | 0.0436 ± 0.0140 | 16393 ± 9246 | 0.564 | 0.00 | 16.68 | 0 |
| blind | 2.0 | 15.65 ± 2.50 | 2662 ± 433 | 0.0499 ± 0.0160 | 57266 ± 14596 | 0.255 | 0.00 | 4.17 | 0 |

## Binding

{"0.5": {"pilot_frac_exceeding": 0.98, "binding": true}, "1.0": {"pilot_frac_exceeding": 0.4, "binding": true}, "2.0": {"pilot_frac_exceeding": 0.0, "binding": false}}

## Ranking

{"0.5": {"by_jstar": ["sigma", "mol", "blind"], "by_iota": ["sigma", "mol", "blind"], "agree": true, "tasks_closed": {"sigma": 1, "mol": 1, "blind": 0}, "common_tasks": 0, "sum_median_jstar_common": {"sigma": 0, "mol": 0, "blind": 0}}, "1.0": {"by_jstar": ["mol", "sigma", "blind"], "by_iota": ["mol", "sigma", "blind"], "agree": true, "tasks_closed": {"sigma": 9, "mol": 11, "blind": 0}, "common_tasks": 0, "sum_median_jstar_common": {"sigma": 0, "mol": 0, "blind": 0}}, "2.0": {"by_jstar": ["sigma", "mol", "blind"], "by_iota": ["blind", "sigma", "mol"], "agree": false, "tasks_closed": {"sigma": 29, "mol": 29, "blind": 15}, "common_tasks": 15, "sum_median_jstar_common": {"sigma": 0.023699821978991745, "mol": 0.024747977609277487, "blind": 0.02430265790599823}}}

## F1 paired

{"0.5": {"n_tasks": 1, "mean_diff_j": -6.677283513068996e-06, "median_diff_j": -6.677283513068996e-06, "ci95": [-6.677283513068996e-06, -6.677283513068996e-06], "wilcoxon_z": -1.0, "wilcoxon_p": 0.31731050786291415, "closed_sigma": 1, "closed_mol": 1}, "1.0": {"n_tasks": 9, "mean_diff_j": 0.00010192301241452134, "median_diff_j": 2.6865643157482615e-05, "ci95": [-0.0005229400735753248, 0.000603408076657268], "wilcoxon_z": 1.2439326432940938, "wilcoxon_p": 0.21352435403618233, "closed_sigma": 9, "closed_mol": 11}, "2.0": {"n_tasks": 29, "mean_diff_j": -0.0002645583170079559, "median_diff_j": -4.7413052892695054e-07, "ci95": [-0.0006628371355016408, 5.668463040175829e-05], "wilcoxon_z": -0.9189860496432602, "wilcoxon_p": 0.3581028690285257, "closed_sigma": 29, "closed_mol": 29}}

## Acts

{"n_acts": 7800, "kendall_tau_b_est_vs_reported": 0.9999998749687343, "n_tau": 4000, "confirmed_acts": 3847, "min_distance_to_floor": 360477060794897.25, "median_distance_to_floor": 4983557031392288.0, "iota_act_median": 69892.49899869514, "iota_act_q25_q75": [35758.594479856656, 146697.04382005223], "zero_reported_acts": 0}

## Refusal

{"infeasible_pairs": 45, "recall_on_infeasible": 1.0, "refusals": 4136, "share_on_tasks_closed_by_some_arm": 0.07108317214700194}

## Falsifiers

- R-F1: v2 fired=False; v1 fired=True (sigma-law selector closes tasks in fewer joules than Mixture of Limits)
- R-F2: v2 fired=False; v1 fired=True (refusal implementation (zero overspends))
- R-F3: v2 fired=False; v1 fired=True (refusal correctness)
- R-F4 (part B: episode est_j vs RAPL net, tau=-0.037, fired=True); analyze2 value: fired=False; v1 fired=False (cycle-count est_j model usable for ranking)
- R-F5: v2 fired=True; v1 fired=True (iota is stable across seeds at run granularity)
- R-F6: v2 fired=True; v1 fired=True (ranking by J* equals ranking by integrated iota)
- R-F7: v2 fired=False; v1 fired=False (the accounting (no act below k_B T ln 2 per bit))
- R-F8: v2 fired=False; v1 fired=False (prediction first, comparison and refusal raise iota over a goal-blind agent)

## Paired by seed (declared in advance)

{"0.5": {"closed_diff_mean": -0.05, "closed_diff_ci95": [-0.45, 0.35], "iota_diff_mean": 193.2894062409374, "iota_diff_ci95": [-1965.5862156444853, 2325.41396723066], "n_seeds": 40, "seeds_sigma_more": 12, "seeds_tied": 15}, "1.0": {"closed_diff_mean": -0.475, "closed_diff_ci95": [-1.8, 0.775], "iota_diff_mean": -893.3031260807227, "iota_diff_ci95": [-4368.831715719086, 2452.8333517418428], "n_seeds": 40, "seeds_sigma_more": 17, "seeds_tied": 6}, "2.0": {"closed_diff_mean": 0.825, "closed_diff_ci95": [0.125, 1.575], "iota_diff_mean": 3558.9491996718175, "iota_diff_ci95": [-1068.1878816151088, 8320.013649979755], "n_seeds": 40, "seeds_sigma_more": 9, "seeds_tied": 27}}

overspend max fraction: -0.03977
close_j: {'max': 0.0002155005463824272, 'median': 8.392307681083679e-06}

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
   "q25": 2476168,
   "median": 2600000,
   "q75": 2600000,
   "max": 2602587
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
   "seconds": 60.003190339,
   "package-0_j": 562.451136,
   "core_j": 323.686976,
   "psys_j": 12.282745,
   "others_cores": 3.973941577785997,
   "package_w": 9.373687179336967
  },
  "idle_post": {
   "seconds": 60.000724849,
   "package-0_j": 190.212098,
   "core_j": 0.881834,
   "psys_j": 12.435638,
   "others_cores": 0.013666470859092257,
   "package_w": 3.1701633351712775
  },
  "baseline_drift_package_w": -6.203523844165689,
  "block_baseline_w": {
   "n": 360,
   "min": 2.353689115457051,
   "q25": 3.0839194110478796,
   "median": 3.2894401567558957,
   "q75": 4.726145016297285,
   "max": 27.891281858671164
  },
  "block_baseline_core_w": {
   "n": 360,
   "min": 0.0062844555974651325,
   "q25": 0.010402766296336134,
   "median": 0.024192802043932038,
   "q75": 1.2424470142930806,
   "max": 23.105613166641707
  },
  "block_others_cores": {
   "n": 360,
   "min": 0.0,
   "q25": 7.79577925461091e-10,
   "median": 0.17548530995163006,
   "q75": 1.028565210536934,
   "max": 18.857993076209237
  },
  "baseline_others_cores": {
   "n": 360,
   "min": 0.0,
   "q25": 0.009994789640421683,
   "median": 0.029983767344201905,
   "q75": 1.0146502333589833,
   "max": 19.060669507182347
  },
  "quiet_blocks": 208,
  "blocks": 360,
  "gate_met": 244,
  "main_run_s": 1621.4012863636017,
  "pilot_idle_baseline_w": 4.7153992091416805,
  "open_threshold_j": 0.0015361566166076659,
  "step_floor_j": 0.0005037081219482421,
  "close_reserve_j_locked": 0.0005287403727111817,
  "close_reserve_j_final": 0.0005287403727111817,
  "refusal_quantile": 0.1,
  "J_g2_median": {
   "n": 30,
   "min": 0.000763333714981079,
   "q25": 0.0011813965023345946,
   "median": 0.0035021891701202392,
   "q75": 0.0067790525729522705,
   "max": 0.017112107379379272
  },
  "tasks_with_budget_below_open_threshold": {
   "0.5": 14,
   "1.0": 9,
   "2.0": 1
  }
 },
 "rapl_quantisation": {
  "episodes": 10800,
  "zero_gross_package_episodes": 5258,
  "nonpositive_reported_episodes": 0,
  "episode_seconds": {
   "n": 10800,
   "min": 2.5809e-05,
   "q25": 4.7885e-05,
   "median": 0.000344819,
   "q75": 0.001781266,
   "max": 0.019672747
  }
 },
 "crosscheck": {
  "block_package_net_j_total": 17.141651987008686,
  "sum_episode_reported_j_total": 23.230019077973818,
  "ratio_episodes_to_block_net": 1.355179716376192,
  "block_core_net_j_total": 18.186794967116892,
  "core_net_over_package_net": 1.0609709601443489,
  "core_share_of_package_gross": {
   "n": 360,
   "min": 0.0486062123108431,
   "q25": 0.11405673226869854,
   "median": 0.16209056186422152,
   "q75": 0.4203108543509015,
   "max": 0.8404568982804432
  },
  "psys_over_package_gross": {
   "n": 360,
   "min": 0.0064609662766495326,
   "q25": 0.033313929515632196,
   "median": 0.0532916970549866,
   "q75": 0.06087369249532873,
   "max": 0.0729578000856368
  },
  "idle_pre_w": 9.373687179336967,
  "idle_post_w": 3.1701633351712775,
  "drift_x_main_run_s_j": -89.3259841737843,
  "achievable": false,
  "note": "package net = block gross package joules minus that block's idle baseline power x block seconds; episode reported_j is the same quantity per episode; the gap is harness work between episodes."
 },
 "per_act": {
  "acts": 7800,
  "confirmed": 3847,
  "reported_j_all_acts": {
   "n": 7800,
   "min": 5.605722208023071e-05,
   "q25": 0.00025849714921569823,
   "median": 0.0018822377089881897,
   "q75": 0.003574591729894638,
   "max": 0.0328510544862442
  },
  "reported_j_confirmed": {
   "n": 3847,
   "min": 0.00016075063566970825,
   "q25": 0.0011035259878149032,
   "median": 0.002498045150259018,
   "q75": 0.005135924611911774,
   "max": 0.03263045818745518
  },
  "nonpositive_confirmed": 0,
  "j_per_bit_confirmed": {
   "n": 3847,
   "min": 1.0349220300973894e-06,
   "q25": 6.825954701487804e-06,
   "median": 1.4307687009712867e-05,
   "q75": 2.7965304972020494e-05,
   "max": 0.00018059234160644597
  },
  "multiples_of_kTln2_confirmed": {
   "n": 3847,
   "min": 360477060794897.25,
   "q25": 2377570499373642.0,
   "median": 4983557031392288.0,
   "q75": 9740686397020878.0,
   "max": 6.2902706301684984e+16
  },
  "multiples_of_kTln2_positive_only": {
   "n": 3847,
   "min": 360477060794897.25,
   "q25": 2377570499373642.0,
   "median": 4983557031392288.0,
   "q75": 9740686397020878.0,
   "max": 6.2902706301684984e+16
  }
 },
 "quiet_block_sensitivity": {
  "sigma@0.5": {
   "n_blocks": 22,
   "closed_mean": 1.5909090909090908,
   "iota_mean": 8715.61881859996,
   "iota_sd": 4805.872464440634
  },
  "sigma@1.0": {
   "n_blocks": 28,
   "closed_mean": 10.142857142857142,
   "iota_mean": 23854.893774777393,
   "iota_sd": 3822.1064862128105
  },
  "sigma@2.0": {
   "n_blocks": 23,
   "closed_mean": 28.91304347826087,
   "iota_mean": 55052.85500907932,
   "iota_sd": 6267.81541050491
  },
  "mol@0.5": {
   "n_blocks": 20,
   "closed_mean": 1.25,
   "iota_mean": 6290.719935287596,
   "iota_sd": 4051.334874474985
  },
  "mol@1.0": {
   "n_blocks": 25,
   "closed_mean": 10.24,
   "iota_mean": 23768.132946855552,
   "iota_sd": 3953.5798883548646
  },
  "mol@2.0": {
   "n_blocks": 23,
   "closed_mean": 29,
   "iota_mean": 54308.38006753049,
   "iota_sd": 5281.011677814937
  },
  "blind@0.5": {
   "n_blocks": 20,
   "closed_mean": 0.25,
   "iota_mean": 2278.375666232336,
   "iota_sd": 4071.0605625069966
  },
  "blind@1.0": {
   "n_blocks": 21,
   "closed_mean": 4.095238095238095,
   "iota_mean": 18223.577288728575,
   "iota_sd": 6624.288285951806
  },
  "blind@2.0": {
   "n_blocks": 26,
   "closed_mean": 15.923076923076923,
   "iota_mean": 57771.560175949984,
   "iota_sd": 13594.156390439095
  }
 },
 "vs_mac_v1": {
  "sigma@0.5": {
   "mac_v1_closed": 0.6,
   "jetson_closed": 1.1,
   "mac_v1_iota": 5254.376716053403,
   "jetson_iota": 6026.502399105674,
   "mac_v1_J": 0.020846548200000002,
   "jetson_J": 0.03446539729883936
  },
  "sigma@1.0": {
   "mac_v1_closed": 9.1,
   "jetson_closed": 8.75,
   "mac_v1_iota": 34454.29328038495,
   "jetson_iota": 20518.71501295332,
   "mac_v1_J": 0.04381087055,
   "jetson_J": 0.08054321173000582
  },
  "sigma@2.0": {
   "mac_v1_closed": 28.4,
   "jetson_closed": 28.6,
   "mac_v1_iota": 73345.05089385762,
   "jetson_iota": 50667.36722667162,
   "mac_v1_J": 0.0662276315,
   "jetson_J": 0.10076723253334521
  },
  "mol@0.5": {
   "mac_v1_closed": 0.7,
   "jetson_closed": 1.15,
   "mac_v1_iota": 6801.07583243979,
   "jetson_iota": 5833.212992864737,
   "mac_v1_J": 0.0187763464,
   "jetson_J": 0.036646103333612734
  },
  "mol@1.0": {
   "mac_v1_closed": 6.45,
   "jetson_closed": 9.225,
   "mac_v1_iota": 23804.12224938882,
   "jetson_iota": 21412.018139034044,
   "mac_v1_J": 0.0446960957,
   "jetson_J": 0.08126469615911881
  },
  "mol@2.0": {
   "mac_v1_closed": 27.5,
   "jetson_closed": 27.775,
   "mac_v1_iota": 70417.5261418113,
   "jetson_iota": 47108.4180269998,
   "mac_v1_J": 0.06698783609999999,
   "jetson_J": 0.10988283498606712
  },
  "blind@0.5": {
   "mac_v1_closed": 0.25,
   "jetson_closed": 0.2,
   "mac_v1_iota": 2775.0287436886756,
   "jetson_iota": 1722.186258070089,
   "mac_v1_J": 0.01413027455,
   "jetson_J": 0.020963614519848857
  },
  "blind@1.0": {
   "mac_v1_closed": 3.85,
   "jetson_closed": 3.725,
   "mac_v1_iota": 24152.594347677492,
   "jetson_iota": 16393.137541911947,
   "mac_v1_J": 0.0265751776,
   "jetson_J": 0.04361982413724223
  },
  "blind@2.0": {
   "mac_v1_closed": 18.25,
   "jetson_closed": 15.65,
   "mac_v1_iota": 92724.38757146311,
   "jetson_iota": 57265.646636359044,
   "mac_v1_J": 0.0340764357,
   "jetson_J": 0.049905585568112636
  }
 },
 "R-F4_part_B": {
  "tau_b_episode_est_vs_rapl_net": -0.03740889898589944,
  "n": 4000,
  "fired": true,
  "note": "replaces analyze2 R-F4, which is identically 1 when reported_j is itself the cycle model"
 },
 "calibration": {
  "attempt": 2,
  "rounds": [
   {
    "seconds": 3.01731877,
    "package_gross_j": 44.736763,
    "core_gross_j": 31.792155,
    "idle_w": 10.732914579867014,
    "net_j": 12.352138381360596,
    "cycles": 7800963923,
    "gear_runs": 4770,
    "others_cores": 4.371326890494673
   },
   {
    "seconds": 3.04568212,
    "package_gross_j": 22.980044,
    "core_gross_j": 11.594026,
    "idle_w": 4.268395567788808,
    "net_j": 9.97986793809838,
    "cycles": 7872127506,
    "gear_runs": 4860,
    "others_cores": 1.0834137429985544
   },
   {
    "seconds": 3.008610565,
    "package_gross_j": 21.678716,
    "core_gross_j": 10.394688,
    "idle_w": 4.711194767200704,
    "net_j": 7.5045656496272475,
    "cycles": 7786046178,
    "gear_runs": 4770,
    "others_cores": 1.0601674365509297
   },
   {
    "seconds": 3.035464279,
    "package_gross_j": 22.356388,
    "core_gross_j": 9.901525,
    "idle_w": 5.164003888738485,
    "net_j": 6.681238659117238,
    "cycles": 7862808183,
    "gear_runs": 4860,
    "others_cores": 1.0046762686880557
   },
   {
    "seconds": 3.00143534,
    "package_gross_j": 43.494457,
    "core_gross_j": 29.713119,
    "idle_w": 8.13284277857218,
    "net_j": 19.084255269729663,
    "cycles": 7764816505,
    "gear_runs": 4770,
    "others_cores": 3.7144718065187963
   },
   {
    "seconds": 3.04368838,
    "package_gross_j": 27.411062,
    "core_gross_j": 15.052939,
    "idle_w": 16.99708959332948,
    "net_j": -24.32278208903586,
    "cycles": 7870301488,
    "gear_runs": 4680,
    "others_cores": 1.990863309841883
   },
   {
    "seconds": 3.000262651,
    "package_gross_j": 68.028513,
    "core_gross_j": 54.295027,
    "idle_w": 20.558730659673174,
    "net_j": 6.346921249813988,
    "cycles": 7744642460,
    "gear_runs": 4050,
    "others_cores": 10.502177715761592
   },
   {
    "seconds": 3.02529704,
    "package_gross_j": 39.115928,
    "core_gross_j": 29.438035,
    "idle_w": 11.777723714441006,
    "net_j": 3.484815308763821,
    "cycles": 7814929458,
    "gear_runs": 4410,
    "others_cores": 5.4262344407268355
   }
  ],
  "idle_w": [
   17.18105943406854,
   4.2847697256654875,
   4.252021409912127,
   5.17036812448928,
   5.1576396529876885,
   11.108045904156668,
   22.886133282502293,
   18.23132803684405,
   5.324119392037962
  ],
  "idle_others_cores": [
   7.623358793725823,
   0.6347853362174121,
   1.0097099366992206,
   1.0646708878282718,
   1.009653243541102,
   3.8655582274345988,
   13.65770442612027,
   8.639318275399349,
   1.0095150799203163
  ],
  "package_net_j": 41.11102036747507,
  "cycles": 62516635701,
  "c_j_per_cycle": 6.576012913442408e-10,
  "agent_net_w": 1.7003652042739825,
  "idle_after": {
   "seconds": 10.000193797,
   "package-0_j": 65.09694,
   "core_j": 23.276735,
   "psys_j": 2.018244,
   "others_cores": 1.429916703343232,
   "package_w": 6.509567846528006
  }
 }
}
```
