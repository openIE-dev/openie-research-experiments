import json, os, sys, collections
d = sys.argv[1]
tot=0; std=0; tool=0; stdonly=0; withdrawn_std=0; byyear=collections.Counter(); byyear_all=collections.Counter(); pkgs=collections.Counter()
for f in os.listdir(d):
    if not f.endswith('.json'): continue
    j=json.load(open(os.path.join(d,f)))
    tot+=1
    yr=j.get('published','')[:4]
    byyear_all[yr]+=1
    names={a['package']['name'] for a in j.get('affected',[])}
    if 'withdrawn' in j and 'stdlib' in names: withdrawn_std+=1
    if 'stdlib' in names:
        std+=1; byyear[yr]+=1
        for a in j['affected']:
            if a['package']['name']=='stdlib':
                for imp in a.get('ecosystem_specific',{}).get('imports',[]):
                    pkgs[imp['path']]+=1
        if names=={'stdlib'}: stdonly+=1
    if 'toolchain' in names: tool+=1
print('total OSV entries',tot)
print('entries affecting stdlib',std,'(stdlib-only',stdonly,', withdrawn',withdrawn_std,')')
print('entries affecting toolchain',tool)
print('stdlib by published year',sorted(byyear.items()))
print('all by published year',sorted(byyear_all.items()))
print('top stdlib packages',pkgs.most_common(15))
