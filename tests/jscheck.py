# SPDX-License-Identifier: EUPL-1.2
# Hrubá kontrola JS (na Pi není JS engine): spustit `python3 tests/jscheck.py web/js/*.js`.
# vyvážené závorky (mimo řetězce/komentáře/šablony), importovaná jména existují v exportech.
import re, sys, os
def strip(src):
    out=[];i=0;n=len(src);stack=[]
    prev=''
    while i<n:
        c=src[i]
        if src.startswith('//',i): i=src.find('\n',i); i=n if i<0 else i; continue
        if src.startswith('/*',i): i=src.find('*/',i)+2; continue
        if c in '"\'':
            j=i+1
            while src[j]!=c:
                j+= 2 if src[j]=='\\' else 1
            i=j+1; out.append('S'); prev='S'; continue
        if c=='`':
            j=i+1; depth=0
            while True:
                if src[j]=='\\': j+=2; continue
                if src.startswith('${',j): depth+=1; j+=2; continue
                if src[j]=='}' and depth: depth-=1; j+=1; continue
                if src[j]=='`' and not depth: break
                j+=1
            i=j+1; out.append('S'); prev='S'; continue
        if c=='/' and prev in '(,=:[!&|?{};\n' :
            j=i+1; cls=False
            while True:
                if src[j]=='\\': j+=2; continue
                if src[j]=='[': cls=True
                elif src[j]==']': cls=False
                elif src[j]=='/' and not cls: break
                j+=1
            i=j+1; out.append('R'); prev='R'; continue
        out.append(c)
        if not c.isspace(): prev=c
        i+=1
    return ''.join(out)
ok=True
for f in sys.argv[1:]:
    s=strip(open(f).read()); st=[]; pairs={')':'(',']':'[','}':'{'}
    for k,c in enumerate(s):
        if c in '([{': st.append((c,k))
        elif c in ')]}':
            if not st or st[-1][0]!=pairs[c]: print(f,'nesoulad',c,'u',s[max(0,k-60):k]); ok=False; break
            st.pop()
    if st and ok: print(f,'neuzavřeno',st[-1]); ok=False
    src=open(f).read()
    for m in re.finditer(r"import\s*\{([^}]*)\}\s*from\s*'(\.[^']*)'",src):
        tgt=os.path.normpath(os.path.join(os.path.dirname(f),m.group(2))); t=open(tgt).read()
        for name in [x.strip().split(' as ')[0] for x in m.group(1).split(',') if x.strip()]:
            if not re.search(r'export\s+(async\s+)?(function|const|class|let)\s+'+name+r'\b',t) and not re.search(r'export\s*\{[^}]*\b'+name+r'\b',t):
                print(f,'chybí export',name,'v',tgt); ok=False
print('OK' if ok else 'CHYBA')
