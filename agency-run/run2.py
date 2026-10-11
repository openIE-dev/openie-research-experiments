"""v2 harness. Modes: pilot2, main2, probe. All joules are reported_j.

pilot2: the v1 pilot procedure (gears alone on the calibration split, g2 alone
on the test split, 5 repetitions), plus guard calibration (largest metered
step, closing cost) and the refusal-quantile replay on the calibration split.
main2: idle baseline, main run inside a powermetrics window, idle baseline;
process-list samples every 10 s throughout.
"""
import gc, json, os, plistlib, random, statistics as st, subprocess, sys, threading, time
from agency_run import meter
from agency_run.agents import ebin
from agency_run.agents2 import Calib2, episode2, guard_ok
from agency_run.sudoku import GEARS, ORDER, complete, bits

ARMS = ['sigma', 'mol', 'blind']
LEVELS = [0.5, 1.0, 2.0]
SEEDS = list(range(1, 41))            # v2: 40 seeds
QGRID = [0.10, 0.25, 0.50, 0.75, 0.90]
P, R = 'pilot2', 'results2'


def load(n):
    return json.load(open(f'tasks/{n}.json'))


def q(v, r):
    v = sorted(v); k = (len(v) - 1) * r; lo = int(k); hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def gear_alone(task, g, seed):
    """v1 pilot measurement, unchanged."""
    rng = random.Random(seed)
    a = meter.read(); out, _ = GEARS[g](task['grid'], rng=rng); b = meter.read()
    return complete(out, task['grid']), meter.joules(a, b), b[1] - a[1]


def gear_steps(task, g, seed):
    """Run a gear alone; return pass, joules, cycles, step costs, close cost."""
    rng = random.Random(seed); steps = []; last = [meter.read()]
    def rec():
        x = meter.read(); steps.append(meter.joules(last[0], x)); last[0] = x; return True
    a = last[0]; out, _ = GEARS[g](task['grid'], rng=rng, check=rec); b = meter.read()
    c0 = meter.read(); ok = complete(out, task['grid']); _ = {'m': ok, 'h': str(out)}; c1 = meter.read()
    return ok, meter.joules(a, b), b[1] - a[1], steps, meter.joules(c0, c1)


def replay(calib_tasks, rows, r, close_reserve, step_floor):
    """Refusal precision and recall on the calibration split for quantile r.
    Costs are each task's median pilot cost per gear. An episode is infeasible
    at (task, level) when no single gear that passes costs at most B - close_reserve,
    the room the v2 guard leaves for acts."""
    cost, ok = {}, {}
    for t in calib_tasks:
        for g in ORDER:
            rr = [x for x in rows if x['set'] == 'calib' and x['task'] == t['id'] and x['gear'] == g]
            cost[(t['id'], g)] = st.median([x['reported_j'] for x in rr]); ok[(t['id'], g)] = min(x['pass'] for x in rr)
    tab = {'cost': {}, 'passes': {}, 'cost_q': {}}
    for b in (0, 1, 2):
        tb = [t for t in calib_tasks if ebin(t['grid']) == b]
        tab['cost'][b] = {g: st.median([cost[(t['id'], g)] for t in tb]) for g in ORDER}
        tab['cost_q'][b] = {g: q([cost[(t['id'], g)] for t in tb], r) for g in ORDER}
        tab['passes'][b] = [{g: ok[(t['id'], g)] for g in ORDER} for t in tb]
    from agency_run.agents2 import select2
    cal = Calib2(tab)
    refusals = ref_infeasible = infeasible_eps = 0
    for t in calib_tasks:
        b = ebin(t['grid']); bq = bits(t['grid'])
        for lvl in LEVELS:
            B = lvl * cost[(t['id'], 'g2')]; cap = B - close_reserve
            opens = guard_ok(0.0, step_floor, close_reserve, B)       # else every arm stops at open
            infeasible = (not opens) or not any(ok[(t['id'], g)] and cost[(t['id'], g)] <= cap for g in ORDER)
            for arm in ('sigma', 'mol'):
                spent, tried, refused = 0.0, [], not opens
                while opens:
                    g, why = select2(arm, cal, b, tried, cap - spent, bq, bq / B)
                    if g is None:
                        refused = True; break
                    spent += cost[(t['id'], g)]
                    if spent > cap:
                        refused = True; break
                    if ok[(t['id'], g)]:
                        break
                    tried.append(g)
                infeasible_eps += infeasible; refusals += refused; ref_infeasible += refused and infeasible
    prec = ref_infeasible / refusals if refusals else 1.0
    rec = ref_infeasible / infeasible_eps if infeasible_eps else 1.0
    return {'r': r, 'precision': prec, 'recall': rec, 'refusals': refusals}


def pilot2():
    os.makedirs(P, exist_ok=True); os.makedirs(R, exist_ok=True)
    ps = PsSampler(f'{R}/load_ps.jsonl'); ps.start()
    calib, test = load('calib'), load('test')
    rows, steps, closes = [], [], []
    # (a) the v1 pilot, unchanged: gears alone, no in-act reads
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
    # (b) guard sizing: the same gears with the in-act reads the agents use
    for rep in range(2):
        for t in calib:
            for g in ORDER:
                _, _, _, s, c = gear_steps(t, g, 3000 + rep); steps += s; closes.append(c)
        for t in test:
            _, _, _, s, c = gear_steps(t, 'g2', 4000 + rep); steps += s; closes.append(c)
    with open(f'{P}/pilot_rows.jsonl', 'w') as f:
        for r_ in rows:
            f.write(json.dumps(r_) + '\n')
    close_reserve, step_floor = max(closes), max(steps)
    rep_ = [replay(calib, rows, r, close_reserve, step_floor) for r in QGRID]
    ok_ = [x for x in rep_ if x['recall'] >= 0.9]
    pool = ok_ if ok_ else rep_
    best = max(pool, key=lambda x: (round(x['precision'], 6), -abs(x['r'] - 0.5)))
    r = best['r']
    cost, passes, cost_q = {}, {}, {}
    for b in (0, 1, 2):
        cr = lambda g: [x['reported_j'] for x in rows if x['set'] == 'calib' and x['bin'] == b and x['gear'] == g]
        cost[b] = {g: st.median(cr(g)) for g in ORDER}
        tb = [t for t in calib if ebin(t['grid']) == b]
        tmed = lambda g: [st.median([x['reported_j'] for x in rows if x['set'] == 'calib' and x['task'] == t['id'] and x['gear'] == g]) for t in tb]
        cost_q[b] = {g: q(tmed(g), r) for g in ORDER}          # same construction as the replay
        passes[b] = [{g: min(x['pass'] for x in rows if x['set'] == 'calib' and x['task'] == t['id'] and x['gear'] == g)
                      for g in ORDER} for t in calib if ebin(t['grid']) == b]
    jg2 = {t['id']: st.median([x['reported_j'] for x in rows if x['set'] == 'test' and x['task'] == t['id']]) for t in test}
    ratio = [x['reported_j'] / x['cycles'] for x in rows if x['cycles'] > 0 and x['reported_j'] > 0]
    locked = {'cost': cost, 'passes': passes, 'cost_q': cost_q, 'refusal_quantile': r, 'replay': rep_,
              'J_g2_median': jg2, 'est_j_per_cycle': st.median(ratio),
              'step_floor': step_floor, 'close_reserve': close_reserve,
              'open_threshold_j': 2 * step_floor + close_reserve,
              'min_budget_j': 0.5 * min(jg2.values()),
              'max_step_seen': max(steps), 'max_close_seen': max(closes), 'n_steps': len(steps),
              'note': 'v2 pilot, locked and committed before the v2 main run.'}
    json.dump(locked, open(f'{P}/locked.json', 'w'), indent=1)
    ps.stop.set(); ps.join()
    print(json.dumps({k: locked[k] for k in ('refusal_quantile', 'replay', 'step_floor', 'close_reserve', 'est_j_per_cycle')}, indent=1))


import ctypes as _ct
_lib2 = _ct.CDLL('/usr/lib/libSystem.B.dylib') if os.uname().sysname == 'Darwin' else None
_buf2 = _ct.create_string_buffer(464)


def read_watch():
    """Same counter as meter.read, own buffer, for the watcher thread."""
    if _lib2 is None:
        return meter.read()
    _lib2.proc_pid_rusage(os.getpid(), 6, _buf2); b = _buf2.raw
    return (int.from_bytes(b[336:344], 'little'), int.from_bytes(b[256:264], 'little'),
            int.from_bytes(b[248:256], 'little'), time.perf_counter_ns())


def pm_window(fn, seconds, interval_ms=500):
    n = int(seconds * 1000 / interval_ms)
    return subprocess.Popen(['sudo', '-n', '/usr/bin/powermetrics', '-i', str(interval_ms), '-n', str(n), '-f', 'plist',
                             '--samplers', 'cpu_power,gpu_power,ane_power', '-o', fn],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def pm_parse(fn):
    raw = open(fn, 'rb').read(); tot = {'cpu': 0.0, 'gpu': 0.0, 'ane': 0.0}; secs = 0.0; n = 0
    for c in raw.split(b'\x00'):
        c = c.strip()
        if not c:
            continue
        d = plistlib.loads(c); dt = d['elapsed_ns'] / 1e9; p = d['processor']
        for k in tot:
            tot[k] += p.get(f'{k}_power', 0.0) / 1e3 * dt
        secs += dt; n += 1
    return {'samples': n, 'seconds': secs, **{f'{k}_j': v for k, v in tot.items()},
            'package_j': sum(tot.values()), 'cpu_w': tot['cpu'] / secs, 'gpu_w': tot['gpu'] / secs,
            'package_w': sum(tot.values()) / secs}


def ps_top(k=8):
    out = subprocess.run(['ps', '-Ao', 'pid=,pcpu=,comm='], capture_output=True, text=True).stdout.splitlines()
    rows = []
    for line in out:
        parts = line.split(None, 2)
        if len(parts) == 3 and int(parts[0]) != os.getpid():
            rows.append((float(parts[1]), int(parts[0]), os.path.basename(parts[2])[:40]))
    rows.sort(reverse=True)
    return {'t': time.time(), 'total_pcpu_others': round(sum(r[0] for r in rows), 1),
            'top': [{'pcpu': r[0], 'pid': r[1], 'comm': r[2]} for r in rows[:k]]}


class PsSampler(threading.Thread):
    def __init__(self, fn, every=10):
        super().__init__(daemon=True); self.fn, self.every, self.stop = fn, every, threading.Event()
    def run(self):
        with open(self.fn, 'a') as f:
            while not self.stop.is_set():
                f.write(json.dumps(ps_top()) + '\n'); f.flush(); self.stop.wait(self.every)


def probe(cpu_max=5.0, gpu_max=3.0, pcpu_max=200.0):
    os.makedirs('_tmp', exist_ok=True); fn = '_tmp/probe.plist'
    if os.path.exists(fn):
        os.remove(fn)
    p = pm_window(fn, 6, 2000); p.wait(timeout=60)
    w = pm_parse(fn); os.remove(fn); top = ps_top(5)
    quiet = w['cpu_w'] <= cpu_max and w['gpu_w'] <= gpu_max and top['total_pcpu_others'] <= pcpu_max
    rec = {'t': time.strftime('%Y-%m-%d %H:%M:%S'), 'cpu_w': round(w['cpu_w'], 2), 'gpu_w': round(w['gpu_w'], 2),
           'total_pcpu_others': top['total_pcpu_others'], 'top': top['top'], 'quiet': quiet}
    print(json.dumps(rec), flush=True)
    return 0 if quiet else 1


def main2(quiet_flag='unknown'):
    os.makedirs(R, exist_ok=True)
    locked = json.load(open(f'{P}/locked.json')); calib = Calib2(locked); test = load('test')
    G = {'step_floor': locked['step_floor'], 'close_reserve': locked['close_reserve']}
    ps = PsSampler(f'{R}/load_ps.jsonl'); ps.start()
    win = {}
    # idle baseline before
    a = meter.read(); p = pm_window(f'{R}/pm_idle_pre.plist', 60); p.wait(timeout=200); b = meter.read()
    win['idle_pre'] = {'process_j': meter.joules(a, b)}
    # main run inside one window
    mon = {}
    pmain = pm_window(f'{R}/pm_main.plist', 90)
    def watch():
        mon['a'] = read_watch(); pmain.wait(timeout=900); mon['b'] = read_watch()
    th = threading.Thread(target=watch); th.start(); time.sleep(1.0)
    warm = random.Random(0)
    for t in test:
        episode2(t, 'mol', locked['J_g2_median'][t['id']] * 2.0, warm, calib, {}, G)
    conds = [(arm, l) for arm in ARMS for l in LEVELS]
    fe = open(f'{R}/episodes.jsonl', 'w'); runs = []
    t_main0 = time.time()
    for seed in SEEDS:
        order = list(conds); random.Random(seed).shuffle(order)
        for arm, lvl in order:
            rng = random.Random(seed * 1000 + ARMS.index(arm) * 10 + LEVELS.index(lvl))
            tasks = list(test); random.Random(seed).shuffle(tasks)
            meta = {'arm': arm, 'level': lvl, 'seed': seed}
            gc.collect(); gc.disable(); r0 = meter.read(); X = 0.0; la = os.getloadavg()[0]
            for t in tasks:
                ep = episode2(t, arm, lvl * locked['J_g2_median'][t['id']], rng, calib, meta, G)
                X += ep['X_bits']; fe.write(json.dumps(ep) + '\n')
            r1 = meter.read(); gc.enable()
            runs.append({**meta, 'X_bits': X, 'reported_j': meter.joules(r0, r1), 'wall_s': (r1[3] - r0[3]) / 1e9,
                         'loadavg_1m_start': la})
            print(seed, arm, lvl, round(X, 1), round(runs[-1]['reported_j'], 4), flush=True)
        fe.flush()
    fe.close(); t_main1 = time.time()
    json.dump(runs, open(f'{R}/runs.json', 'w'), indent=1)
    th.join()
    win['main'] = {'process_j': meter.joules(mon['a'], mon['b']), 'main_run_s': t_main1 - t_main0,
                   'window_process_s': (mon['b'][3] - mon['a'][3]) / 1e9}
    a = meter.read(); p = pm_window(f'{R}/pm_idle_post.plist', 60); p.wait(timeout=200); b = meter.read()
    win['idle_post'] = {'process_j': meter.joules(a, b)}
    ps.stop.set(); ps.join()
    for k in ('idle_pre', 'main', 'idle_post'):
        win[k].update(pm_parse(f'{R}/pm_{k}.plist'))
    base_w = st.mean([win['idle_pre']['package_w'], win['idle_post']['package_w']])
    base_cpu_w = st.mean([win['idle_pre']['cpu_w'], win['idle_post']['cpu_w']])
    m = win['main']
    m['package_net_j'] = m['package_j'] - base_w * m['seconds']
    m['cpu_net_j'] = m['cpu_j'] - base_cpu_w * m['seconds']
    m['ratio_package_net_to_process'] = m['package_net_j'] / m['process_j'] if m['process_j'] > 0 else None
    m['ratio_cpu_net_to_process'] = m['cpu_net_j'] / m['process_j'] if m['process_j'] > 0 else None
    win['baseline_package_w'] = base_w; win['baseline_cpu_w'] = base_cpu_w
    win['baseline_drift_package_w'] = win['idle_post']['package_w'] - win['idle_pre']['package_w']
    win['quiet_window'] = quiet_flag
    win['guard_final'] = G
    json.dump(win, open(f'{R}/crosscheck.json', 'w'), indent=1)
    print(json.dumps(win, indent=1))


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'probe':
        sys.exit(probe())
    if mode == 'pilot2':
        pilot2()
    if mode == 'main2':
        main2(sys.argv[2] if len(sys.argv) > 2 else 'unknown')
