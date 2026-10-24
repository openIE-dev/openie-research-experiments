import json,os,sys,collections,re
d=sys.argv[1]; n=0; names=collections.Counter(); cveyear=collections.Counter(); withdrawn=0
for root,_,fs in os.walk(d):
  for f in fs:
    if not f.endswith('.json'): continue
    j=json.load(open(os.path.join(root,f))); n+=1
    if j.get('withdrawn'): withdrawn+=1
    for a in j.get('affected',[]): names[a.get('package',{}).get('name')]+=1
    al=[x for x in j.get('aliases',[]) if x.startswith('CVE-')]
    cveyear[al[0][4:8] if al else 'none']+=1
print('files',n,'withdrawn',withdrawn); print(names.most_common()); print(sorted(cveyear.items()))
