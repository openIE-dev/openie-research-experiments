"""v2 harness on the second fabric (jetson-hub, Linux, Intel RAPL). See
PREREGISTRATION_v2_jetson.md. Modes: freqsave, freqpin, freqrestore, probe,
pilot, main, ps.

Backend switch: on Linux this binds agency_run.meter to agency_run.meter_rapl
before any agent module is imported; on macOS the original meter is used.
Selection, guard, gears, H(a), the pilot procedure and the refusal-quantile
replay are imported unchanged from agents.py, agents2.py, sudoku.py and
run2.py (commit 610dd4c).
"""
import gc, glob, json, os, random, statistics as st, subprocess, sys, time

if sys.platform.startswith('linux'):                    # backend switch
    import agency_run
    from agency_run import meter_rapl as meter
    sys.modules['agency_run.meter'] = meter; agency_run.meter = meter
else:
    from agency_run import meter

import run2                                              # pilot procedure and replay, unchanged
from agency_run.agents2 import Calib2, episode2

ARMS, LEVELS, SEEDS = run2.ARMS, run2.LEVELS, run2.SEEDS
PART = os.environ.get('JETSON_PART', 'A')              # A: RAPL per read; B: RAPL-calibrated cycles (amendment 1)
P, R = ('pilot_jetson', 'results_jetson') if PART == 'A' else ('pilot_jetson_cyc', 'results_jetson_cyc')
if PART == 'B':
    meter.MODE = 'cyc'
AGENT_CPU = 4
QUIET_OTHERS_CORES = 0.5          # other processes' busy CPU, in cores
GATE_MAX_S, BASE_S = 5.0, 2.0     # per-block quiet gate (max wait) and idle baseline
CPU = '/sys/devices/system/cpu/'


# ---------- frequency
def _w(path, val):
    with open(path, 'w') as f:
        f.write(str(val))


def freq_state():
    cpus = sorted(glob.glob(CPU + 'cpu[0-9]*/cpufreq'), key=lambda p: int(p.split('/')[-2][3:]))
    s = {'no_turbo': open(CPU + 'intel_pstate/no_turbo').read().strip(),
         'status': open(CPU + 'intel_pstate/status').read().strip(), 'cpus': {}}
    for c in cpus:
        n = c.split('/')[-2]
        s['cpus'][n] = {k: open(f'{c}/{k}').read().strip() for k in
                        ('scaling_governor', 'energy_performance_preference', 'scaling_min_freq',
                         'scaling_max_freq', 'base_frequency', 'cpuinfo_max_freq')}
    return s


def freqpin():
    _w(CPU + 'intel_pstate/no_turbo', 1)
    for n, v in freq_state()['cpus'].items():
        _w(f'{CPU}{n}/cpufreq/scaling_max_freq', v['base_frequency'])
        _w(f'{CPU}{n}/cpufreq/scaling_min_freq', v['base_frequency'])


def freqrestore(fn):
    s = json.load(open(fn))
    _w(CPU + 'intel_pstate/no_turbo', s['no_turbo'])
    for n, v in s['cpus'].items():
        _w(f'{CPU}{n}/cpufreq/scaling_max_freq', v['scaling_max_freq'])
        _w(f'{CPU}{n}/cpufreq/scaling_min_freq', v['scaling_min_freq'])


def avg_freq(cpu=AGENT_CPU):
    try:
        return int(open(f'{CPU}cpu{cpu}/cpufreq/cpuinfo_avg_freq').read())
    except OSError:
        return None


# ---------- load
def stat_busy():
    v = list(map(int, open('/proc/stat').readline().split()[1:]))
    return (sum(v[:8]) - v[3] - v[4]) / os.sysconf('SC_CLK_TCK')   # busy CPU-seconds, all CPUs


def own_cpu():
    t = os.times(); return t.user + t.system


class Load:
    def __init__(self):
        self.b, self.o, self.t = stat_busy(), own_cpu(), time.perf_counter()
    def others_cores(self):
        dt = time.perf_counter() - self.t
        return max(0.0, (stat_busy() - self.b) - (own_cpu() - self.o)) / dt if dt > 0 else None


def window(seconds):
    """Agent idle for `seconds`: package/subdomain joules, others' CPU."""
    L = Load(); a = meter.read_all(); time.sleep(seconds); b = meter.read_all()
    d = meter.diff_all(a, b); d['others_cores'] = L.others_cores()
    d['package_w'] = d['package-0_j'] / d['seconds']
    return d


def gate():
    """Wait (polling 1 s windows, at most GATE_MAX_S) until others' CPU <= threshold."""
    t0 = time.perf_counter(); polls = []
    while True:
        L = Load(); time.sleep(1.0); oc = L.others_cores(); polls.append(round(oc, 3))
        if oc <= QUIET_OTHERS_CORES:
            return {'gate_met': True, 'gate_wait_s': time.perf_counter() - t0, 'gate_polls': polls}
        if time.perf_counter() - t0 >= GATE_MAX_S:
            return {'gate_met': False, 'gate_wait_s': time.perf_counter() - t0, 'gate_polls': polls}


def ps_top(k=8):
    out = subprocess.run(['ps', '-eo', 'pid=,user=,pcpu=,comm='], capture_output=True, text=True).stdout.splitlines()
    rows = []
    for line in out:
        p = line.split(None, 3)
        if len(p) == 4 and int(p[0]) != os.getpid():
            rows.append((float(p[2]), int(p[0]), p[1], p[3][:40]))
    rows.sort(reverse=True)
    return {'t': time.strftime('%Y-%m-%d %H:%M:%S'), 'loadavg': os.getloadavg(),
            'top': [{'pcpu': r[0], 'pid': r[1], 'user': r[2], 'comm': r[3]} for r in rows[:k]]}


def ps_loop(fn, every=10):
    with open(fn, 'a') as f:
        while not os.path.exists(f'{R}/STOP_PS'):
            f.write(json.dumps(ps_top()) + '\n'); f.flush(); time.sleep(every)


def probe(seconds=5.0):
    d = window(seconds); top = ps_top(6)
    quiet = d['others_cores'] <= QUIET_OTHERS_CORES
    rec = {'t': top['t'], 'package_w': round(d['package_w'], 3), 'core_w': round(d.get('core_j', 0) / d['seconds'], 3),
           'others_cores': round(d['others_cores'], 3), 'top': top['top'], 'quiet': quiet}
    print(json.dumps(rec), flush=True)
    return 0 if quiet else 1


# ---------- pilot: run2.pilot2 unchanged, outputs to pilot_jetson/
class _NoPs:                       # the load sampler runs as its own process on another core
    def __init__(self, *a, **k):
        import threading; self.stop = threading.Event()
    def start(self): pass
    def join(self): pass


def pilot():
    os.makedirs(P, exist_ok=True); os.makedirs(R, exist_ok=True)
    env = {'affinity': sorted(os.sched_getaffinity(0)), 'cycles_source': meter.CYCLES_SOURCE, 'meter': meter.METER,
           'freq': freq_state(), 'avg_freq_agent_cpu_khz_before': avg_freq()}
    env['gate'] = gate(); base = window(10.0); env['idle_baseline'] = base
    meter.set_baseline(base['package_w'])
    if PART == 'B':
        env['calibration'] = calibrate()
        meter.C_J_PER_CYCLE = env['calibration']['c_j_per_cycle']
        env['calibration']['idle_after'] = window(10.0)
    run2.P, run2.R, run2.PsSampler = P, R, _NoPs
    t0 = time.time(); run2.pilot2(); env['pilot_s'] = time.time() - t0
    env['avg_freq_agent_cpu_khz_after'] = avg_freq()
    env['idle_after'] = window(10.0)
    json.dump(env, open(f'{P}/env.json', 'w'), indent=1, default=str)


def calibrate(base_w=None, rounds=8, idle_s=2.0, active_s=3.0, tries=3):
    """Part B: c = sum over rounds of (package joules - P_idle x T) / sum of agent cycles.
    Rounds alternate idle (agent sleeping) and active (every gear on every calibration
    puzzle in a loop); P_idle for an active segment is the mean of the idle segments
    before and after it, which cancels linear drift of other load. Up to 3 tries if
    the summed net is not positive."""
    from agency_run.sudoku import GEARS, ORDER
    calib = run2.load('calib'); rng = random.Random(7)
    for attempt in range(tries):
        idle = [window(idle_s)]; segs = []
        for k in range(rounds):
            L = Load(); a = meter.read_all(); c0 = meter._cycles(); n = 0
            t_end = time.perf_counter() + active_s
            while time.perf_counter() < t_end:
                for t in calib:
                    for g in ORDER:
                        GEARS[g](t['grid'], rng=rng); n += 1
            c1 = meter._cycles(); b = meter.read_all(); d = meter.diff_all(a, b); oc = L.others_cores()
            idle.append(window(idle_s))
            pw = (idle[-2]['package_w'] + idle[-1]['package_w']) / 2
            segs.append({'seconds': d['seconds'], 'package_gross_j': d['package-0_j'], 'core_gross_j': d.get('core_j'),
                         'idle_w': pw, 'net_j': d['package-0_j'] - pw * d['seconds'], 'cycles': c1 - c0,
                         'gear_runs': n, 'others_cores': oc})
        net = sum(x['net_j'] for x in segs); cyc = sum(x['cycles'] for x in segs)
        out = {'attempt': attempt + 1, 'rounds': segs, 'idle_w': [x['package_w'] for x in idle],
               'idle_others_cores': [x['others_cores'] for x in idle],
               'package_net_j': net, 'cycles': cyc, 'c_j_per_cycle': net / cyc,
               'agent_net_w': net / sum(x['seconds'] for x in segs)}
        if out['c_j_per_cycle'] > 0:
            return out
    raise SystemExit('calibration failed: net package joules not positive in 3 tries')


# ---------- main
def main(quiet_flag='unknown'):
    os.makedirs(R, exist_ok=True)
    locked = json.load(open(f'{P}/locked.json')); calib = Calib2(locked); test = run2.load('test')
    if PART == 'B':
        meter.C_J_PER_CYCLE = json.load(open(f'{P}/env.json'))['calibration']['c_j_per_cycle']
    G = {'step_floor': locked['step_floor'], 'close_reserve': locked['close_reserve']}
    env = {'affinity': sorted(os.sched_getaffinity(0)), 'cycles_source': meter.CYCLES_SOURCE, 'meter': meter.METER,
           'freq': freq_state(), 'quiet_window': quiet_flag, 'part': PART, 'meter_mode': meter.MODE,
           'c_j_per_cycle': meter.C_J_PER_CYCLE}
    env['idle_pre'] = window(60.0)
    meter.set_baseline(env['idle_pre']['package_w'])
    warm = random.Random(0)
    for t in test:
        episode2(t, 'mol', locked['J_g2_median'][t['id']] * 2.0, warm, calib, {}, G)
    conds = [(arm, l) for arm in ARMS for l in LEVELS]
    fe = open(f'{R}/episodes.jsonl', 'w'); fb = open(f'{R}/blocks.jsonl', 'w'); runs = []
    t_main0 = time.time()
    for seed in SEEDS:
        order = list(conds); random.Random(seed).shuffle(order)
        for arm, lvl in order:
            g = gate(); base = window(BASE_S); meter.set_baseline(base['package_w'])
            rng = random.Random(seed * 1000 + ARMS.index(arm) * 10 + LEVELS.index(lvl))
            tasks = list(test); random.Random(seed).shuffle(tasks)
            meta = {'arm': arm, 'level': lvl, 'seed': seed}
            L = Load(); f0 = avg_freq()
            gc.collect(); gc.disable(); A0 = meter.read_all(); r0 = meter.read(); X = 0.0
            for t in tasks:
                ha = meter.read_all()
                ep = episode2(t, arm, lvl * locked['J_g2_median'][t['id']], rng, calib, meta, G)
                hb = meter.read_all(); d = meter.diff_all(ha, hb)
                ep['harness'] = {'base_w': base['package_w'], 'seconds': d['seconds'],
                                 'pkg_gross_j': d['package-0_j'], 'core_gross_j': d.get('core_j'),
                                 'psys_gross_j': d.get('psys_j'), 'uncore_gross_j': d.get('uncore_j')}
                X += ep['X_bits']; fe.write(json.dumps(ep) + '\n')
            r1 = meter.read(); A1 = meter.read_all(); gc.enable()
            blk = meter.diff_all(A0, A1); oc = L.others_cores()
            run = {**meta, 'X_bits': X, 'reported_j': meter.joules(r0, r1), 'wall_s': (r1[3] - r0[3]) / 1e9,
                   'loadavg_1m_start': os.getloadavg()[0], 'base_w': base['package_w'],
                   'base_core_w': base.get('core_j', 0) / base['seconds'], 'base_others_cores': base['others_cores'],
                   'block_others_cores': oc, 'block': blk, 'avg_freq_khz': [f0, avg_freq()], **g,
                   'quiet_block': bool(g['gate_met'] and base['others_cores'] <= QUIET_OTHERS_CORES and oc is not None and oc <= QUIET_OTHERS_CORES)}
            runs.append(run); fb.write(json.dumps(run) + '\n'); fb.flush()
            print(seed, arm, lvl, round(X, 1), round(run['reported_j'], 5), round(base['package_w'], 2),
                  round(oc, 2), run['quiet_block'], flush=True)
        fe.flush()
    fe.close(); fb.close(); env['main_run_s'] = time.time() - t_main0
    json.dump(runs, open(f'{R}/runs.json', 'w'), indent=1)
    env['idle_post'] = window(60.0)
    env['guard_final'] = G; env['freq_after'] = freq_state()
    json.dump(env, open(f'{R}/env_main.json', 'w'), indent=1, default=str)


if __name__ == '__main__':
    m = sys.argv[1]
    if m == 'freqsave':
        json.dump(freq_state(), open(sys.argv[2], 'w'), indent=1)
    elif m == 'freqpin':
        freqpin(); print(json.dumps(freq_state()))
    elif m == 'freqrestore':
        freqrestore(sys.argv[2]); print(json.dumps(freq_state()))
    elif m == 'probe':
        sys.exit(probe())
    elif m == 'pilot':
        pilot()
    elif m == 'main':
        main(sys.argv[2] if len(sys.argv) > 2 else 'unknown')
    elif m == 'ps':
        os.makedirs(R, exist_ok=True); ps_loop(f'{R}/load_ps.jsonl')
    elif m == 'calibcheck':                 # print the calibration a pilot would use (no files)
        c = calibrate(rounds=3); c.pop('rounds'); print(json.dumps(c))
