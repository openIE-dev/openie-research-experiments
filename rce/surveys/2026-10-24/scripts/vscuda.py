import sys,csv
fn,mode=sys.argv[1],sys.argv[2]
rows=[r for r in csv.reader(open(fn)) if r and any(c.strip() for c in r)]
hdr=[h.strip() for h in rows[0]]
ci=hdr.index('CUDA')
print(fn)
for r in rows[1:]:
    vals=[c.strip() for c in r]
    if vals[ci] in ('X',''): continue
    cu=float(vals[ci]); out=[]
    for j,h in enumerate(hdr[1:],1):
        if h=='CUDA' or vals[j] in ('X',''): continue
        v=float(vals[j]); f= cu/v if mode=='time' else v/cu
        out.append(f"{h}={f:.2f}")
    print("  ",vals[0],' '.join(out))
