"""Analysis fixed before the main run. Reads results/, writes summary.json and summary.md.
All joules are reported_j (kernel energy model, per process). None are measured_j."""
import json, math, random, statistics as st
from collections import defaultdict

KB, T = 1.380649e-23, 300.0
FLOOR = KB * T * math.log(2)            # joules per bit at 300 K
ARMS = ['sigma', 'mol', 'blind']; LEVELS = [0.5, 1.0, 2.0]
INF = float('inf')

def sd(x): return st.stdev(x) if len(x) > 1 else 0.0

def kendall_tau_b(x, y):
    n = len(x); c = d = tx = ty = 0
    for i in range(n):
        xi, yi = x[i], y[i]
        for j in range(i + 1, n):
            a = xi - x[j]; b = yi - y[j]
            if a == 0 and b == 0: continue
            if a == 0: tx += 1
            elif b == 0: ty += 1
            elif (a > 0) == (b > 0): c += 1
            else: d += 1
    den = math.sqrt((c + d + tx) * (c + d + ty))
    return (c - d) / den if den else float('nan')

def boot_ci(v, n=10000, seed=1):
    r = random.Random(seed); m = []
    for _ in range(n):
        s = [v[r.randrange(len(v))] for _ in v]; m.append(st.mean(s))
    m.sort(); return m[int(0.025 * n)], m[int(0.975 * n) - 1]

def wilcoxon(v):
    v = [x for x in v if x != 0]; n = len(v)
    if n == 0: return None, None
    r = sorted(range(n), key=lambda i: abs(v[i])); ranks = [0] * n; i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(v[r[j + 1]]) == abs(v[r[i]]): j += 1
        for k in range(i, j + 1): ranks[r[k]] = (i + j) / 2 + 1
        i = j + 1
    wp = sum(ranks[i] for i in range(n) if v[i] > 0)
    mu = n * (n + 1) / 4; s = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    z = (wp - mu) / s; p = math.erfc(abs(z) / math.sqrt(2))
    return z, p

def main():
    locked = json.load(open('pilot/locked.json'))
    eps = [json.loads(l) for l in open('results/episodes.jsonl')]
    runs = json.load(open('results/runs.json'))
    prow = [json.loads(l) for l in open('pilot/pilot_rows.jsonl')]
    tasks = sorted({e['task'] for e in eps})
    out = {'energy_label': 'reported_j', 'measured_j': None, 'floor_j_per_bit_300K': FLOOR}
    # binding levels from the pilot: >= 20% of pilot g2 runs exceed B
    bind = {}
    for l in LEVELS:
        pr = [r for r in prow if r['set'] == 'test']
        frac = sum(r['reported_j'] > l * locked['J_g2_median'][r['task']] for r in pr) / len(pr)
        bind[l] = {'pilot_frac_exceeding': frac, 'binding': frac >= 0.2}
    out['binding'] = bind
    # per-run integrated iota from episodes
    R = defaultdict(lambda: {'X': 0.0, 'J': 0.0, 'closed': 0, 'refused': 0, 'cut': 0, 'over': 0})
    for e in eps:
        k = (e['arm'], e['level'], e['seed']); r = R[k]
        r['X'] += e['X_bits']; r['J'] += e['reported_j']; r['closed'] += e['passed']
        r['refused'] += e['refused']; r['cut'] += e['cut']; r['over'] += e['overspend']
    cond = {}
    for a in ARMS:
        for l in LEVELS:
            rs = [R[(a, l, s)] for s in sorted({k[2] for k in R if k[0] == a and k[1] == l})]
            io = [r['X'] / r['J'] if r['J'] > 0 else 0 for r in rs]
            row = {'n_seeds': len(rs)}
            for name, v in (('closed', [r['closed'] for r in rs]), ('X_bits', [r['X'] for r in rs]),
                            ('J_reported', [r['J'] for r in rs]), ('iota_bits_per_j', io),
                            ('refused', [r['refused'] for r in rs]), ('cut', [r['cut'] for r in rs])):
                row[name] = {'mean': st.mean(v), 'sd': sd(v)}
            row['iota_cv'] = sd(io) / st.mean(io) if st.mean(io) > 0 else None
            row['overspends'] = sum(r['over'] for r in rs)
            row['run_overhead_reported_j'] = st.mean([x['reported_j'] for x in runs if x['arm'] == a and x['level'] == l])
            cond[f'{a}@{l}'] = row
    out['conditions'] = cond
    # J* per task
    jstar = {}
    for a in ARMS:
        for l in LEVELS:
            for t in tasks:
                v = [e['reported_j'] if e['passed'] else INF for e in eps if e['arm'] == a and e['level'] == l and e['task'] == t]
                ok = [x for x in v if x < INF]
                jstar[(a, l, t)] = {'median': st.median(v), 'closed_frac': len(ok) / len(v),
                                    'mean_closed': st.mean(ok) if ok else None, 'sd_closed': sd(ok) if ok else None}
    out['jstar'] = {f'{a}@{l}@{t}': v for (a, l, t), v in jstar.items()}
    # rankings
    rank = {}
    for l in LEVELS:
        common = [t for t in tasks if all(jstar[(a, l, t)]['median'] < INF for a in ARMS)]
        key = {a: (-sum(jstar[(a, l, t)]['median'] < INF for t in tasks),
                   sum(jstar[(a, l, t)]['median'] for t in common)) for a in ARMS}
        by_j = sorted(ARMS, key=lambda a: key[a])
        by_i = sorted(ARMS, key=lambda a: -cond[f'{a}@{l}']['iota_bits_per_j']['mean'])
        rank[l] = {'by_jstar': by_j, 'by_iota': by_i, 'agree': by_j == by_i,
                   'tasks_closed': {a: -key[a][0] for a in ARMS}, 'common_tasks': len(common),
                   'sum_median_jstar_common': {a: key[a][1] for a in ARMS}}
    out['ranking'] = rank
    # F1: sigma minus mol, paired per task
    f1 = {}
    for l in LEVELS:
        d = [jstar[('sigma', l, t)]['median'] - jstar[('mol', l, t)]['median'] for t in tasks
             if jstar[('sigma', l, t)]['median'] < INF and jstar[('mol', l, t)]['median'] < INF]
        if d:
            lo, hi = boot_ci(d); z, p = wilcoxon(d)
            f1[l] = {'n_tasks': len(d), 'mean_diff_j': st.mean(d), 'median_diff_j': st.median(d),
                     'ci95': [lo, hi], 'wilcoxon_z': z, 'wilcoxon_p': p,
                     'closed_sigma': rank[l]['tasks_closed']['sigma'], 'closed_mol': rank[l]['tasks_closed']['mol']}
        else:
            f1[l] = {'n_tasks': 0}
    out['F1_paired'] = f1
    # acts: Kendall, floor, per-act iota
    acts = [(a, e) for e in eps for a in e['acts']]
    xs = [a for a, e in acts if a['reported_j'] > 0 and a['cycles'] > 0]
    r = random.Random(3); sub = xs if len(xs) <= 4000 else r.sample(xs, 4000)
    tau = kendall_tau_b([a['cycles'] * locked['est_j_per_cycle'] for a in sub], [a['reported_j'] for a in sub])
    conf = [a for a, e in acts if a['b_bits'] > 0]
    ratio = [a['reported_j'] / a['b_bits'] / FLOOR for a in conf]
    iota_act = [a['b_bits'] / a['reported_j'] for a in conf if a['reported_j'] > 0]
    out['acts'] = {'n_acts': len(acts), 'kendall_tau_b_est_vs_reported': tau, 'n_tau': len(sub),
                   'confirmed_acts': len(conf), 'min_distance_to_floor': min(ratio) if ratio else None,
                   'median_distance_to_floor': st.median(ratio) if ratio else None,
                   'iota_act_median': st.median(iota_act) if iota_act else None,
                   'iota_act_q25_q75': [st.quantiles(iota_act, n=4)[0], st.quantiles(iota_act, n=4)[2]] if len(iota_act) > 3 else None,
                   'zero_reported_acts': sum(1 for a, e in acts if a['reported_j'] <= 0)}
    # refusal quality (F3)
    closed_by_any = {(l, t) for l in LEVELS for t in tasks for a in ARMS if jstar[(a, l, t)]['closed_frac'] >= 0.5}
    infeasible = {(l, t) for l in LEVELS for t in tasks if all(jstar[(a, l, t)]['closed_frac'] == 0 for a in ARMS)}
    law = [e for e in eps if e['arm'] in ('sigma', 'mol')]
    inf_eps = [e for e in law if (e['level'], e['task']) in infeasible]
    recall = sum(e['refused'] for e in inf_eps) / len(inf_eps) if inf_eps else None
    refs = [e for e in law if e['refused']]
    false_ref = sum((e['level'], e['task']) in closed_by_any for e in refs) / len(refs) if refs else 0.0
    out['refusal'] = {'infeasible_pairs': len(infeasible), 'recall_on_infeasible': recall,
                      'refusals': len(refs), 'share_on_tasks_closed_by_some_arm': false_ref}
    # falsifiers
    bl = [l for l in LEVELS if bind[l]['binding']]
    F = {}
    F['R-F1'] = {'fired': all((f1[l].get('n_tasks', 0) == 0) or f1[l]['ci95'][0] <= 0 <= f1[l]['ci95'][1] or f1[l]['ci95'][0] > 0 for l in bl) if bl else None,
                 'claim': 'sigma-law selector closes tasks in fewer joules than Mixture of Limits'}
    F['R-F2'] = {'fired': any(cond[k]['overspends'] > 0 for k in cond), 'claim': 'refusal implementation (zero overspends)',
                 'overspends': {k: cond[k]['overspends'] for k in cond}}
    F['R-F3'] = {'fired': (recall is not None and recall < 0.9) or false_ref > 0.10, 'claim': 'refusal correctness'}
    F['R-F4'] = {'fired': tau < 0.8, 'claim': 'cycle-count est_j model usable for ranking', 'tau': tau}
    cvs = {k: cond[k]['iota_cv'] for k in cond if cond[k]['iota_cv'] is not None}
    F['R-F5'] = {'fired': any(v > 0.25 for v in cvs.values()), 'claim': 'iota is stable across seeds at run granularity', 'cv': cvs}
    F['R-F6'] = {'fired': not all(rank[l]['agree'] for l in LEVELS), 'claim': 'ranking by J* equals ranking by integrated iota'}
    F['R-F7'] = {'fired': bool(ratio) and min(ratio) < 1, 'claim': 'the accounting (no act below k_B T ln 2 per bit)'}
    F['R-F8'] = {'fired': any(cond[f'blind@{l}']['iota_bits_per_j']['mean'] >= max(cond[f'sigma@{l}']['iota_bits_per_j']['mean'], cond[f'mol@{l}']['iota_bits_per_j']['mean']) for l in bl) if bl else None,
                 'claim': 'prediction first, comparison and refusal raise iota over a goal-blind agent'}
    out['falsifiers'] = F
    json.dump(out, open('results/summary.json', 'w'), indent=1, default=str)
    # markdown
    L = ['# Summary', '', 'Energy label: reported_j (macOS per-process kernel energy model). measured_j: empty, no wall meter.', '',
         '| arm | B/J_g2 | closed of 30 | X bits | J reported | iota bits/J | CV iota | refused | cut | overspends |', '|---|---|---|---|---|---|---|---|---|---|']
    for a in ARMS:
        for l in LEVELS:
            c = cond[f'{a}@{l}']
            L.append(f"| {a} | {l} | {c['closed']['mean']:.2f} ± {c['closed']['sd']:.2f} | {c['X_bits']['mean']:.0f} ± {c['X_bits']['sd']:.0f} | "
                     f"{c['J_reported']['mean']:.4f} ± {c['J_reported']['sd']:.4f} | {c['iota_bits_per_j']['mean']:.0f} ± {c['iota_bits_per_j']['sd']:.0f} | "
                     f"{c['iota_cv']:.3f} | {c['refused']['mean']:.2f} | {c['cut']['mean']:.2f} | {c['overspends']} |" if c['iota_cv'] is not None else
                     f"| {a} | {l} | {c['closed']['mean']:.2f} | 0 | {c['J_reported']['mean']:.4f} | 0 | n/a | {c['refused']['mean']:.2f} | {c['cut']['mean']:.2f} | {c['overspends']} |")
    L += ['', '## Binding', '', json.dumps(bind), '', '## Ranking', '', json.dumps(rank, default=str), '', '## F1 paired', '', json.dumps(f1, default=str),
          '', '## Acts', '', json.dumps(out['acts']), '', '## Refusal', '', json.dumps(out['refusal']), '', '## Falsifiers', '']
    for k, v in F.items():
        L.append(f"- {k}: fired={v['fired']} ({v['claim']})")
    open('results/summary.md', 'w').write('\n'.join(L) + '\n')
    print('\n'.join(L))

if __name__ == '__main__':
    main()
