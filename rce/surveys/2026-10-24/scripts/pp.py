import sys, csv
def load(fn):
    rows=[r for r in csv.reader(open(fn)) if r and any(c.strip() for c in r)]
    hdr=[h.strip() for h in rows[0]]
    data={}
    for r in rows[1:]:
        plat=r[0].strip(); vals=[]
        for c in r[1:len(hdr)]:
            c=c.strip()
            vals.append(None if c in ('X','x','') else float(c))
        data[plat]=vals
    return hdr[1:],data
def hm(v): return len(v)/sum(1/x for x in v)
fn=sys.argv[1]; mode=sys.argv[2]  # time|tput|raw
models,data=load(fn)
eff={}
for p,vals in data.items():
    ok=[v for v in vals if v is not None]
    if mode=='time': best=min(ok); e=[None if v is None else best/v for v in vals]
    elif mode=='tput': best=max(ok); e=[None if v is None else v/best for v in vals]
    else: e=[None if v is None else v/100 for v in vals]
    eff[p]=e
print(fn, "platforms:",len(data))
for i,m in enumerate(models):
    es=[eff[p][i] for p in data]
    sup=[e for e in es if e is not None]
    n_un=len(es)-len(sup)
    ppall = 0.0 if n_un else hm(sup)
    print(f"  {m:10s} supported {len(sup)}/{len(es)}  PP(all)={ppall:.3f}  HM(supported only)={hm(sup):.3f}  min={min(sup):.3f}")
