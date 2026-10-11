import json,csv,os,sys,collections
res=sys.argv[1]
refcsv=sys.argv[2] if len(sys.argv)>2 else 'tbar-ref/tbar_perfectfl_100.csv'
ref={r['bug']:r['tbar'] for r in csv.DictReader(open(refcsv))}
REV=json.load(open(sys.argv[3])) if len(sys.argv)>3 else {}
def ours(b):
  f=f'{res}/{b}/result.json'
  if not os.path.exists(f): return 'pending'
  r=json.load(open(f))
  if b in REV and r.get('plausible'): return REV[b]
  return 'correct' if r.get('correct') else 'plausible' if r.get('plausible') else 'partial' if r.get('partial') else '-'
T=collections.defaultdict(collections.Counter);rows=[]
for b,t in ref.items():
  p=b.split('-')[0];o=ours(b)
  T[p]['tc']+=t.endswith('correct') and not t.startswith('partial');T[p]['tp']+=t in('correct','plausible')
  T[p]['oc']+=o=='correct';T[p]['op']+=o in('correct','plausible');T[p]['n']+=1
  if t!='-' or o!='-': rows.append((b,t,o))
print('# G1-J vs TBar PerfectFL, per bug\n\nPlausible counts include correct. TBar partial = its separate partial patches, not counted as fixed here.\n')
print('| project | bugs | TBar correct | ours correct | TBar plausible | ours plausible |\n|---|---|---|---|---|---|')
S=collections.Counter()
for p in T:
  t=T[p];S.update(t);print(f"| {p} | {t['n']} | {t['tc']} | {t['oc']} | {t['tp']} | {t['op']} |")
print(f"| total | {S['n']} | {S['tc']} | {S['oc']} | {S['tp']} | {S['op']} |\n")
print('| bug | TBar | ours | gap |\n|---|---|---|---|')
for b,t,o in rows:
  g='MISS' if t in('correct','plausible') and o not in('correct','plausible') else 'WEAKER' if t=='correct' and o=='plausible' else 'OURS ONLY' if o in('correct','plausible') and t not in('correct','plausible') else ''
  print(f'| {b} | {t} | {o} | {g} |')
