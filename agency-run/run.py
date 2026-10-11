"""Harness. Modes: pilot, main, crosscheck. All joules are reported_j."""
import gc, json, os, random, statistics, subprocess, sys, time
from agency_run import meter
from agency_run.agents import Calib, episode, ebin
from agency_run.sudoku import GEARS, ORDER, Abort, complete

ARMS = ['sigma', 'mol', 'blind']
LEVELS = [0.5, 1.0, 2.0]       # preregistered budget multiples of the g2 pilot median
SEEDS = list(range(1, 21))     # preregistered: 20 seeds per condition


def load(n):
    return json.load(open(f'tasks/{n}.json'))


def gear_alone(task, g, seed):
    rng = random.Random(seed)
    a = meter.read(); out, _ = GEARS[g](task['grid'], rng=rng); b = meter.read()
    return complete(out, task['grid']), meter.joules(a, b), b[1] - a[1]


def pilot():
    calib, test = load('calib'), load('test')
    rows = []
    for rep in range(5):
        for t in calib:
            for g in ORDER:
                ok, j, cyc = gear_alone(t, g, 1000 + rep)
                rows.append({'set': 'calib', 'task': t['id'], 'bin': ebin(t['grid']), 'gear': g,
                             'rep': rep, 'pass': int(ok), 'reported_j': j, 'cycles': cyc})
        for t in test:
            ok, j, cyc = gear_alone(t, 'g2', 2000 + rep)
            rows.append({'set': 'test', 'task': t['id'], 'bin': ebin(t['grid']), 'gear': 'g2',
                         'rep': rep, 'pass': int(ok), 'reported_j': j, 'cycles': cyc})
    with open('pilot/pilot_rows.jsonl', 'w') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    cost, passes = {}, {}
    for b in (0, 1, 2):
        cost[b] = {g: statistics.median([r['reported_j'] for r in rows
                                         if r['set'] == 'calib' and r['bin'] == b and r['gear'] == g] or [0])
                   for g in ORDER}
        passes[b] = []
        for t in calib:
            if ebin(t['grid']) != b:
                continue
            passes[b].append({g: min(r['pass'] for r in rows if r['set'] == 'calib'
                                     and r['task'] == t['id'] and r['gear'] == g) for g in ORDER})
    jg2 = {t['id']: statistics.median([r['reported_j'] for r in rows
                                       if r['set'] == 'test' and r['task'] == t['id']]) for t in test}
    ratio = [r['reported_j'] / r['cycles'] for r in rows if r['cycles'] > 0 and r['reported_j'] > 0]
    locked = {'cost': cost, 'passes': passes, 'J_g2_median': jg2,
              'est_j_per_cycle': statistics.median(ratio),
              'note': 'Locked after the pilot and committed before the main run.'}
    json.dump(locked, open('pilot/locked.json', 'w'), indent=1)
    print(json.dumps({k: v for k, v in locked.items() if k != 'J_g2_median'}, indent=1))


def main():
    locked = json.load(open('pilot/locked.json'))
    calib = Calib(locked)
    test = load('test')
    conds = [(a, l) for a in ARMS for l in LEVELS]
    os.makedirs('results', exist_ok=True)
    fe = open('results/episodes.jsonl', 'w')
    runs = []
    warm = random.Random(0)
    for t in test:                                     # one discarded warm-up pass
        episode(t, 'mol', None, warm, calib, {})
    for seed in SEEDS:
        order = list(conds); random.Random(seed).shuffle(order)
        for arm, lvl in order:
            rng = random.Random(seed * 1000 + ARMS.index(arm) * 10 + LEVELS.index(lvl))
            tasks = list(test); random.Random(seed).shuffle(tasks)
            meta = {'arm': arm, 'level': lvl, 'seed': seed}
            gc.collect(); gc.disable()          # no collector pauses inside a metered run
            r0 = meter.read(); la = os.getloadavg()[0]
            X = 0.0
            for t in tasks:
                ep = episode(t, arm, lvl * locked['J_g2_median'][t['id']], rng, calib, meta)
                X += ep['X_bits']
                fe.write(json.dumps(ep) + '\n')
            r1 = meter.read()
            gc.enable()
            runs.append({**meta, 'X_bits': X, 'reported_j': meter.joules(r0, r1),
                         'wall_s': (r1[3] - r0[3]) / 1e9, 'loadavg_1m_start': la})
            print(seed, arm, lvl, round(X, 1), round(runs[-1]['reported_j'], 4), flush=True)
        fe.flush()
    fe.close()
    json.dump(runs, open('results/runs.json', 'w'), indent=1)


def crosscheck(window_s=30, interval_ms=250):
    """Package-level cross-check with powermetrics over fixed windows.

    powermetrics runs with a fixed sample count, so it exits by itself.
    Its readings are filed as reported_j (Apple states they are estimates)."""
    locked = json.load(open('pilot/locked.json'))
    calib = Calib(locked); test = load('test')
    n = int(window_s * 1000 / interval_ms)
    out = []
    for label in ['idle', 'sigma', 'mol', 'blind', 'idle_end']:
        fn = f'results/pm_{label}.plist'
        cmd = ['sudo', '-n', '/usr/bin/powermetrics', '-i', str(interval_ms), '-n', str(n),
               '-f', 'plist', '--samplers', 'cpu_power,gpu_power,ane_power', '-o', fn]
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        time.sleep(0.3)
        a = meter.read(); rng = random.Random(7); k = 0
        while (meter.read()[3] - a[3]) / 1e9 < window_s:
            if label.startswith('idle'):
                time.sleep(0.5)
            else:
                t = test[k % len(test)]; k += 1
                episode(t, label, 1.0 * locked['J_g2_median'][t['id']], rng, calib, {})
        b = meter.read()
        p.wait(timeout=window_s + 30)
        out.append({'window': label, 'process_reported_j': meter.joules(a, b),
                    'wall_s': (b[3] - a[3]) / 1e9, 'episodes': k, 'plist': fn})
        print(out[-1], flush=True)
    json.dump(out, open('results/crosscheck_process.json', 'w'), indent=1)


if __name__ == '__main__':
    {'pilot': pilot, 'main': main, 'crosscheck': crosscheck}[sys.argv[1]]()
