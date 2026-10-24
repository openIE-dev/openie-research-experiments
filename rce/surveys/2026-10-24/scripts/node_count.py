import json,sys,collections,re
j=json.load(open(sys.argv[1]))
print('entries in index.json',len(j))
cves=set(); byyear=collections.Counter(); nocve=0
for k,v in j.items():
    c=v.get('cve',[])
    if isinstance(c,str): c=[c]
    if not c: nocve+=1
    for x in c: cves.add(x)
    m=None
    for x in c:
        m=re.match(r'CVE-(\d{4})',x)
        if m: break
    byyear[m.group(1) if m else 'none']+=1
print('distinct CVE ids',len(cves),'entries without CVE',nocve)
print('entries by first CVE year',sorted(byyear.items()))
k=list(j.items())[-1]; print('last entry',k)
