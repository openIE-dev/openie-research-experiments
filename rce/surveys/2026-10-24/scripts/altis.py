import re,sys
txt=open(sys.argv[1]).read()
units={'s':1.0,'ms':1e-3,'µs':1e-6}
def parse(v):
    v=v.strip()
    m=re.match(r"([0-9.']+)\s*(µs|ms|s)$",v)
    if not m: return None
    return float(m.group(1).replace("'",""))*units[m.group(2)]
secs=re.split(r'\n# ',txt)
out=[]
for s in secs[1:]:
    name=s.split('\n')[0].strip()
    tbl=s.split('\n\n')[1] if '\n\n' in s else s
    rows={}
    for line in s.split('\n'):
        if line.startswith('|') and 'W |' not in line and '---' not in line and 'Device' not in line:
            cells=[c.strip() for c in line.strip().strip('|').split('|')]
            rows[cells[0]]=[parse(c) for c in cells[1:]]
    if not rows: continue
    print("==",name)
    for i in range(3):
        g=lambda k: rows.get(k,[None]*3)[i]
        s10=g('Stratix10'); opt=g('Stratix10 OPT'); ag=g('Agilex OPT')
        cpu=[x for x in (g('Xeon6128 SYCL'),g('Epyc 7763')) if x]
        gpu=[x for x in (g('RTX 2080 SYCL'),g('A100 SYCL'),g('P630 SYCL')) if x]
        bestall=min([x for x in cpu+gpu if x])
        gap=s10/opt if s10 and opt else None
        # app-eff PP over {Xeon,Epyc,RTX2080,A100,P630,Stratix10} for same-source SYCL
        effs=[]
        for k in ('Xeon6128 SYCL','Epyc 7763','A100 SYCL','P630 SYCL'):
            effs.append(1.0)
        r=g('RTX 2080 SYCL'); c=g('RTX 2080 CUDA'); effs.append(min(r,c)/r)
        effs.append(min(s10,opt)/s10)
        pp=len(effs)/sum(1/e for e in effs)
        effs_noF=effs[:-1]; ppnoF=len(effs_noF)/sum(1/e for e in effs_noF)
        print(f"  size{i+1}: S10 unopt/opt = {gap:.1f}x ; FPGA-same-source eff={min(s10,opt)/s10:.3f}; S10unopt vs best CPU/GPU = {s10/bestall:.1f}x slower; S10opt vs best CPU/GPU = {opt/bestall:.2f}x ; PP6(incl FPGA)={pp:.3f}  PP5(CPU+GPU)={ppnoF:.3f}")
