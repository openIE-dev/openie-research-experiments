"""Parse powermetrics windows into package-level reported joules.
Each window: sum over samples of (cpu_power + gpu_power + ane_power, mW) x elapsed_ns.
Gross and idle-subtracted figures are both written. All reported_j."""
import json, plistlib, statistics as st

def window(fn):
    raw = open(fn, 'rb').read()
    tot = {'cpu': 0.0, 'gpu': 0.0, 'ane': 0.0}; secs = 0.0; n = 0
    for chunk in raw.split(b'\x00'):
        chunk = chunk.strip()
        if not chunk:
            continue
        d = plistlib.loads(chunk)
        dt = d['elapsed_ns'] / 1e9; p = d.get('processor', {})
        tot['cpu'] += p.get('cpu_power', 0.0) / 1e3 * dt
        tot['gpu'] += p.get('gpu_power', 0.0) / 1e3 * dt
        tot['ane'] += p.get('ane_power', 0.0) / 1e3 * dt
        secs += dt; n += 1
    return {'samples': n, 'seconds': secs, 'cpu_j': tot['cpu'], 'gpu_j': tot['gpu'], 'ane_j': tot['ane'],
            'cpu_w': tot['cpu'] / secs, 'package_w': sum(tot.values()) / secs}

proc = {r['window']: r for r in json.load(open('results/crosscheck_process.json'))}
out = {}
for w in ['idle', 'sigma', 'mol', 'blind', 'idle_end']:
    out[w] = window(f'results/pm_{w}.plist'); out[w]['process_reported_j'] = proc[w]['process_reported_j']
    out[w]['episodes'] = proc[w]['episodes']
idle_cpu_w = st.mean([out['idle']['cpu_w'], out['idle_end']['cpu_w']])
for w in ['sigma', 'mol', 'blind']:
    o = out[w]
    o['cpu_idle_subtracted_j'] = o['cpu_j'] - idle_cpu_w * o['seconds']
    o['ratio_process_to_cpu_idle_subtracted'] = o['process_reported_j'] / o['cpu_idle_subtracted_j'] if o['cpu_idle_subtracted_j'] > 0 else None
out['idle_cpu_w_mean'] = idle_cpu_w
out['label'] = 'reported_j (powermetrics, Apple-estimated) and reported_j (per-process kernel energy model); measured_j empty'
json.dump(out, open('results/crosscheck.json', 'w'), indent=1)
print(json.dumps(out, indent=1))
