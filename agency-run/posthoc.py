"""Post hoc analysis, written after the main run. Not part of the preregistration.
Paired by seed: sigma minus Mixture of Limits, tasks closed per run and run iota."""
import json, random, statistics as st
from collections import defaultdict
eps = [json.loads(l) for l in open('results/episodes.jsonl')]
R = defaultdict(lambda: [0, 0.0, 0.0])
for e in eps:
    r = R[(e['arm'], e['level'], e['seed'])]; r[0] += e['passed']; r[1] += e['X_bits']; r[2] += e['reported_j']
def boot(v, n=10000, s=1):
    g = random.Random(s); m = sorted(st.mean([v[g.randrange(len(v))] for _ in v]) for _ in range(n)); return m[250], m[9749]
out = {}
for l in (0.5, 1.0, 2.0):
    seeds = sorted({k[2] for k in R})
    dc = [R[('sigma', l, s)][0] - R[('mol', l, s)][0] for s in seeds]
    di = [R[('sigma', l, s)][1] / R[('sigma', l, s)][2] - R[('mol', l, s)][1] / R[('mol', l, s)][2] for s in seeds]
    out[l] = {'closed_diff_mean': st.mean(dc), 'closed_diff_ci95': boot(dc), 'iota_diff_mean': st.mean(di), 'iota_diff_ci95': boot(di),
              'seeds_sigma_closes_more': sum(d > 0 for d in dc), 'seeds_tied': sum(d == 0 for d in dc)}
by = defaultdict(list)
for e in eps:
    if e['passed']:
        by[(e['arm'], e['stratum'])].append(e['reported_j'])
out['median_j_per_closed_episode'] = {f'{a}|{s}': st.median(v) for (a, s), v in sorted(by.items())}
json.dump(out, open('results/posthoc.json', 'w'), indent=1)
print(json.dumps(out, indent=1))
