import re,sys,html,collections
for fn in sys.argv[1:]:
    t=open(fn,encoding='utf-8',errors='replace').read()
    i=t.find('id="AppendixJAVA"')
    if i<0: i=t.find('AppendixJAVA')
    seg=t[i:]
    # cut at next appendix
    m=re.search(r'id="Appendix(?!JAVA)',seg[100:])
    if m: seg=seg[:100+m.start()]
    rows=re.findall(r'<tr[^>]*>(.*?)</tr>',seg,flags=re.S)
    comps=collections.Counter(); cves=set()
    for r in rows:
        cells=[html.unescape(re.sub(r'<[^>]+>','',c)).strip() for c in re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>',r,flags=re.S)]
        if cells and re.match(r'CVE-\d{4}-\d+',cells[0]):
            cves.add(cells[0])
            comps[cells[2] if len(cells)>2 else '?']+=1
    print(fn,len(cves),dict(comps.most_common()))
