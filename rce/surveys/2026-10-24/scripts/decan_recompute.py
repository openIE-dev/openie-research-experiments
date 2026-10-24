# Recompute Decan, Mens, Grosjean (EMSE 2019) snapshot metrics from their replication data,
# following helpers.py (load_data/clean_data/create_snapshot/create_graph).
import sys, time, statistics, collections
import pandas as pd
from multiprocessing import Pool

DATA = sys.argv[1]; eco = sys.argv[2]; date = pd.to_datetime(sys.argv[3] if len(sys.argv)>3 else '2017-01-01')

def clean(packages, deps, ecosystem=None):
    packages = packages[packages['time'] >= pd.to_datetime('1980-01-01')].dropna()
    if ecosystem == 'npm':
        packages = packages[~packages['package'].astype(str).str.startswith(('all-packages-','cool-','neat-','wowdude-'))]
    deps = deps.merge(packages[['package','version']], how='inner')
    deps = deps[deps['dependency'].isin(packages['package'])]
    return packages, deps

t0=time.time()
packages = pd.read_csv(f'{DATA}/{eco}/packages.csv.gz', usecols=['package','version','time'], engine='c')
packages['time'] = pd.to_datetime(packages['time'], errors='coerce', utc=True).dt.tz_localize(None)
deps = pd.read_csv(f'{DATA}/{eco}/dependencies.csv.gz', usecols=['package','version','dependency','constraint'], engine='c')
for df in (packages, deps):
    for c in ('package','version'):
        df[c] = df[c].astype(str)
deps['dependency'] = deps['dependency'].astype(str)
packages, deps = clean(packages, deps, eco)
snap = packages[packages['time'] <= date].sort_values('time').groupby('package', sort=False).tail(1)
deps = deps.merge(snap[['package','version']], how='inner')
snap, deps = clean(snap, deps)
names = list(snap['package']); idx = {n:i for i,n in enumerate(names)}
N=len(names)
adj=[set() for _ in range(N)]
for p,d in zip(deps['package'], deps['dependency']):
    a=idx[p]; b=idx[d]
    if a!=b: adj[a].add(b)
adj=[list(s) for s in adj]
indeg=collections.Counter(b for s in adj for b in s)
def reach(i):
    seen={i}; stack=[i]
    while stack:
        v=stack.pop()
        for w in adj[v]:
            if w not in seen:
                seen.add(w); stack.append(w)
    return len(seen)-1
dependent=[i for i in range(N) if adj[i]]
with Pool(4) as pool:
    tr=pool.map(reach, dependent, chunksize=2000)
out=[len(adj[i]) for i in dependent]
q=lambda xs,p: sorted(xs)[int(p*(len(xs)-1))]
print(f"{eco} @ {date.date()}: packages={N} with>=1 dep={len(dependent)} ({100*len(dependent)/N:.1f}%) required={len(indeg)} ({100*len(indeg)/N:.1f}%)")
print(f"  direct deps (dependents only): median={statistics.median(out)} mean={statistics.mean(out):.2f}")
print(f"  transitive deps (dependents only): median={statistics.median(tr)} mean={statistics.mean(tr):.2f} p75={q(tr,0.75)} p90={q(tr,0.9)}")
print(f"  ratio median(tr)/median(direct)={statistics.median(tr)/statistics.median(out):.1f}  elapsed={time.time()-t0:.0f}s")
