"""Analysis of the jetson-hub v2 run (PREREGISTRATION_v2_jetson.md).

Primary: analyze2.main() unchanged (same tables, falsifiers R-F1..R-F8 and
thresholds, paired-by-seed with 10,000-resample bootstrap), pointed at
pilot_jetson/ and results_jetson/. Added (reported, fire nothing): setup and
load record, idle-subtracted package cross-check, RAPL quantisation, per-act
joules and multiples of k_B T ln 2 per bit, quiet-block sensitivity table and
a side-by-side with Mac run 1. All joules are reported_j (RAPL on-chip
model/sensor, package-0, idle-subtracted). measured_j is empty."""
import json, math, statistics as st
from collections import defaultdict
import os
import analyze2 as A

PART = os.environ.get('JETSON_PART', 'A')
A.P, A.RES = ('pilot_jetson', 'results_jetson') if PART == 'A' else ('pilot_jetson_cyc', 'results_jetson_cyc')
P, R = A.P, A.RES
LABEL = {'A': 'Energy label: reported_j (Intel RAPL package-0 on-chip energy model/sensor, idle baseline power x time subtracted, agent pinned to CPU 4, one episode at a time).',
         'B': 'Energy label: est_j (agent user cycles x c, c calibrated on Intel RAPL package-0 net of idle over a 20 s window in the pilot); the column says J reported for code reuse but every value is est_j. RAPL validates at block level below.'}[PART]


def qs(v):
    v = sorted(v)
    if not v:
        return None
    k = lambda p: v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))]
    return {'n': len(v), 'min': v[0], 'q25': k(.25), 'median': k(.5), 'q75': k(.75), 'max': v[-1]}


def main():
    A.main()
    out = json.load(open(f'{R}/summary.json'))
    eps = [json.loads(l) for l in open(f'{R}/episodes.jsonl')]
    runs = json.load(open(f'{R}/runs.json'))
    env = json.load(open(f'{R}/env_main.json'))
    penv = json.load(open(f'{P}/env.json'))
    locked = json.load(open(f'{P}/locked.json'))
    probes = [json.loads(l) for l in open('results_jetson/load_probe.jsonl')]
    J = {}
    # setup
    pin = env['freq']['cpus']
    J['setup'] = {'meter': env['meter'], 'cycles_source': env['cycles_source'], 'affinity': env['affinity'],
                  'no_turbo': env['freq']['no_turbo'], 'governors': sorted({v['scaling_governor'] for v in pin.values()}),
                  'epp': sorted({v['energy_performance_preference'] for v in pin.values()}),
                  'min_max_khz': sorted({(v['scaling_min_freq'], v['scaling_max_freq']) for v in pin.values()}),
                  'agent_cpu_avg_freq_khz': qs([f for r in runs for f in r['avg_freq_khz'] if f]),
                  'quiet_window': env['quiet_window'], 'probes': len(probes),
                  'probe_others_cores': [p['others_cores'] for p in probes], 'probe_package_w': [p['package_w'] for p in probes],
                  'idle_pre': env['idle_pre'], 'idle_post': env['idle_post'],
                  'baseline_drift_package_w': env['idle_post']['package_w'] - env['idle_pre']['package_w'],
                  'block_baseline_w': qs([r['base_w'] for r in runs]),
                  'block_baseline_core_w': qs([r['base_core_w'] for r in runs]),
                  'block_others_cores': qs([r['block_others_cores'] for r in runs]),
                  'baseline_others_cores': qs([r['base_others_cores'] for r in runs]),
                  'quiet_blocks': sum(r['quiet_block'] for r in runs), 'blocks': len(runs),
                  'gate_met': sum(r['gate_met'] for r in runs), 'main_run_s': env['main_run_s'],
                  'pilot_idle_baseline_w': penv['idle_baseline']['package_w'],
                  'open_threshold_j': locked['open_threshold_j'], 'step_floor_j': locked['step_floor'],
                  'close_reserve_j_locked': locked['close_reserve'], 'close_reserve_j_final': env['guard_final']['close_reserve'],
                  'refusal_quantile': locked['refusal_quantile'], 'J_g2_median': qs(list(locked['J_g2_median'].values())),
                  'tasks_with_budget_below_open_threshold': {str(l): sum(l * v <= locked['open_threshold_j'] for v in locked['J_g2_median'].values()) for l in A.LEVELS}}
    # quantisation and cross-check
    h = [e['harness'] for e in eps]
    J['rapl_quantisation'] = {'episodes': len(eps), 'zero_gross_package_episodes': sum(x['pkg_gross_j'] == 0 for x in h),
                              'nonpositive_reported_episodes': sum(e['reported_j'] <= 0 for e in eps),
                              'episode_seconds': qs([x['seconds'] for x in h])}
    blk = []
    for r in runs:
        b = r['block']; net = b['package-0_j'] - r['base_w'] * b['seconds']
        blk.append({'net': net, 'sum_eps': r['reported_j'], 'core_share': b.get('core_j', 0) / b['package-0_j'] if b['package-0_j'] > 0 else None,
                    'psys_over_pkg': b.get('psys_j', 0) / b['package-0_j'] if b['package-0_j'] > 0 else None})
    tot_net = sum(x['net'] for x in blk); tot_eps = sum(x['sum_eps'] for x in blk)
    core_net = sum(r['block'].get('core_j', 0) - r['base_core_w'] * r['block']['seconds'] for r in runs)
    J['crosscheck'] = {
        'block_package_net_j_total': tot_net, 'sum_episode_reported_j_total': tot_eps,
        'ratio_episodes_to_block_net': tot_eps / tot_net if tot_net else None,
        'block_core_net_j_total': core_net, 'core_net_over_package_net': core_net / tot_net if tot_net else None,
        'core_share_of_package_gross': qs([x['core_share'] for x in blk if x['core_share'] is not None]),
        'psys_over_package_gross': qs([x['psys_over_pkg'] for x in blk if x['psys_over_pkg'] is not None]),
        'idle_pre_w': env['idle_pre']['package_w'], 'idle_post_w': env['idle_post']['package_w'],
        'drift_x_main_run_s_j': (env['idle_post']['package_w'] - env['idle_pre']['package_w']) * sum(r['wall_s'] for r in runs),
        'achievable': tot_net > 0 and env['quiet_window'] == 'yes',
        'note': 'package net = block gross package joules minus that block\'s idle baseline power x block seconds; '
                'episode reported_j is the same quantity per episode; the gap is harness work between episodes.'}
    # per act
    acts = [a for e in eps for a in e['acts']]
    conf = [a for a in acts if a['b_bits'] > 0]
    jb = [a['reported_j'] / a['b_bits'] for a in conf]
    J['per_act'] = {'acts': len(acts), 'confirmed': len(conf), 'reported_j_all_acts': qs([a['reported_j'] for a in acts]),
                    'reported_j_confirmed': qs([a['reported_j'] for a in conf]),
                    'nonpositive_confirmed': sum(a['reported_j'] <= 0 for a in conf),
                    'j_per_bit_confirmed': qs(jb),
                    'multiples_of_kTln2_confirmed': qs([x / A.FLOOR for x in jb]),
                    'multiples_of_kTln2_positive_only': qs([x / A.FLOOR for x in jb if x > 0])}
    # quiet-block sensitivity (declared, fires nothing)
    qk = {(r['arm'], r['level'], r['seed']) for r in runs if r['quiet_block']}
    RR = defaultdict(lambda: [0, 0.0, 0.0])
    for e in eps:
        k = (e['arm'], e['level'], e['seed'])
        if k in qk:
            x = RR[k]; x[0] += e['passed']; x[1] += e['X_bits']; x[2] += e['reported_j']
    sens = {}
    for a in A.ARMS:
        for l in A.LEVELS:
            v = [RR[k] for k in RR if k[0] == a and k[1] == l]
            if v:
                io = [x[1] / x[2] if x[2] > 0 else 0 for x in v]
                sens[f'{a}@{l}'] = {'n_blocks': len(v), 'closed_mean': st.mean(x[0] for x in v),
                                    'iota_mean': st.mean(io), 'iota_sd': A.sd(io)}
    J['quiet_block_sensitivity'] = sens
    # Mac run 1 side by side
    try:
        v1 = json.load(open('results/summary.json'))['conditions']
        J['vs_mac_v1'] = {k: {'mac_v1_closed': v1[k]['closed']['mean'], 'jetson_closed': out['conditions'][k]['closed']['mean'],
                              'mac_v1_iota': v1[k]['iota_bits_per_j']['mean'], 'jetson_iota': out['conditions'][k]['iota_bits_per_j']['mean'],
                              'mac_v1_J': v1[k]['J_reported']['mean'], 'jetson_J': out['conditions'][k]['J_reported']['mean']}
                          for k in out['conditions']}
    except FileNotFoundError:
        J['vs_mac_v1'] = None
    if PART == 'B':
        # R-F4 in part B (amendment 1): Kendall tau-b between episode est_j and the episode's RAPL
        # package net (harness reads around the episode, minus block baseline x seconds), threshold 0.8.
        xs = [(e['reported_j'], e['harness']['pkg_gross_j'] - e['harness']['base_w'] * e['harness']['seconds']) for e in eps]
        import random as _r
        sub = xs if len(xs) <= 4000 else _r.Random(3).sample(xs, 4000)
        tau = A.kendall_tau_b([x[0] for x in sub], [x[1] for x in sub])
        J['R-F4_part_B'] = {'tau_b_episode_est_vs_rapl_net': tau, 'n': len(sub), 'fired': tau < 0.8,
                            'note': 'replaces analyze2 R-F4, which is identically 1 when reported_j is itself the cycle model'}
        out['falsifiers']['R-F4'] = {'fired': tau < 0.8, 'claim': 'cycle-count est_j model usable for ranking (episode est_j vs RAPL net)', 'tau': tau}
        J['calibration'] = penv.get('calibration')
    out['jetson'] = J
    json.dump(out, open(f'{R}/summary.json', 'w'), indent=1, default=str)
    md = open(f'{R}/summary.md').read().replace(
        'Energy label: reported_j (macOS per-process kernel energy model).', LABEL)
    md = md.replace('# Summary', f'# Summary: jetson-hub (second fabric), v2 protocol, part {PART}', 1)
    if PART == 'B':
        md = md.replace(f"- R-F4: v2 fired=", f"- R-F4 (part B: episode est_j vs RAPL net, tau={J['R-F4_part_B']['tau_b_episode_est_vs_rapl_net']:.3f}, fired={J['R-F4_part_B']['fired']}); analyze2 value: fired=")
    md += '\n## Jetson additions (reported; only R-F4_part_B fires, part B only)\n\n```json\n' + json.dumps(J, indent=1, default=str) + '\n```\n'
    open(f'{R}/summary.md', 'w').write(md)
    print(json.dumps({k: J[k] for k in ('crosscheck', 'per_act', 'rapl_quantisation')}, indent=1, default=str))


if __name__ == '__main__':
    main()
