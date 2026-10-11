"""Generate the calibration and test task sets. Deterministic by seed.

For each random full grid, cells are removed in random order while the
solution stays unique. Snapshots: the most-emptied puzzle that g0 still
solves (easy), that g1 still solves but g0 does not (medium), and the final
minimal puzzle if g1 fails on it (hard).
"""
import json, random, sys
from agency_run.sudoku import gear0, gear1, gear2, complete

def full_grid(rng):
    g, _ = gear2([0] * 81, rng=rng)
    return g

def carve(full, rng):
    g = list(full); order = list(range(81)); rng.shuffle(order)
    easy = med = None
    for i in order:
        v = g[i]; g[i] = 0
        n, _ = gear2(g, count_only=True, limit=2)
        if n != 1:
            g[i] = v; continue
        if complete(gear0(g)[0], g):
            easy = list(g)
        elif complete(gear1(g)[0], g):
            med = list(g)
    hard = list(g) if not complete(gear1(g)[0], g) else None
    return easy, med, hard

def make(seed, k):
    rng = random.Random(seed)
    out = {'easy': [], 'medium': [], 'hard': []}
    while min(len(v) for v in out.values()) < k:
        e, m, h = carve(full_grid(rng), rng)
        for name, p in (('easy', e), ('medium', m), ('hard', h)):
            if p and len(out[name]) < k:
                out[name].append(p)
    tasks = []
    for name in ('easy', 'medium', 'hard'):
        for j, p in enumerate(out[name]):
            tasks.append({'id': f'{name[0]}{j:02d}', 'stratum': name, 'grid': p,
                          'empty': sum(1 for v in p if v == 0)})
    return tasks

if __name__ == '__main__':
    for name, seed in (('calib', 20261008), ('test', 8102026)):
        t = make(seed, 10)
        json.dump(t, open(f'tasks/{name}.json', 'w'))
        print(name, len(t), [x['empty'] for x in t])
