"""Find KNOWN, DATED, imminent binaries: PDUFA / action dates / AdCom scheduled.

The moonshot generator is not 'news happened' -- that gaps and is untradeable.
It is 'a decision with a known date is coming'. Scan biotech 8-Ks for forward
action dates landing Aug-Nov 2026.
"""
import sys, re
sys.path.insert(0,'/home/user/integratedai/scripts'); sys.path.insert(0,'/home/user/integratedai/src')
import pandas as pd
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from catalyst_size import TAGS, WS
from oos_clinical import BIO_SIC
from iai.core.config import Config
from iai.core.http import HttpClient

ROOT = Path('/root/.iai/wide2015')
cfg = Config.load()
sec = HttpClient(cfg.data.cache_dir,'chhillarnaresh03@gmail.com',rate_per_sec=9.0,
                 ttl_hours=48.0, max_retries=5)
SUB='https://data.sec.gov/submissions/CIK{cik}.json'
IDX='https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json'
ARCH='https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}'
EX=re.compile(r'ex-?99',re.I)

LO=pd.Timestamp('2026-05-01',tz='America/New_York'); HI=pd.Timestamp('2026-08-04',tz='America/New_York')
# a forward action date in the next ~4 months
FWD = re.compile(
  r'(?:PDUFA|target action|action date|goal date)[^.]{0,120}?'
  r'(August|September|October|November|December)\s+(\d{1,2}),?\s*2026'
  r'|(August|September|October|November|December)\s+(\d{1,2}),?\s*2026[^.]{0,80}?'
  r'(?:PDUFA|target action date|action date|goal date)', re.I)
ADCOM = re.compile(r'advisory committee[^.]{0,140}?(?:scheduled|will\s+(?:be\s+)?(?:meet|convene|hold)|'
                   r'has\s+scheduled|to\s+be\s+held)', re.I)

pool = pd.read_parquet(ROOT/'candidate_pool.parquet')
pool['cik']=pool['cik'].astype(str).str.zfill(10)

def subs(item):
    tkr,cik=item
    b=sec.get(SUB.format(cik=cik))
    if not b or str(b.get('sic','')).strip() not in BIO_SIC: return []
    rec=b.get('filings',{}).get('recent',{}); forms=rec.get('form',[]); out=[]
    for i,f in enumerate(forms):
        if not str(f).startswith('8-K'): continue
        raw=rec.get('acceptanceDateTime',[None]*len(forms))[i]
        if not raw: continue
        ts=pd.Timestamp(raw); ts=ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')
        et=ts.tz_convert('America/New_York')
        if not (LO<=et<=HI): continue
        out.append({'ticker':tkr,'cik':cik,'et':et,
                    'accession':rec.get('accessionNumber',['']*len(forms))[i],
                    'doc':rec.get('primaryDocument',['']*len(forms))[i]})
    return out

fil=[]
with ThreadPoolExecutor(max_workers=8) as ex:
    fu=[ex.submit(subs,(r.ticker,r.cik)) for r in pool.itertuples()]
    for k,f_ in enumerate(as_completed(fu),1):
        if k%1200==0: print(f'  subs {k}/{len(pool)}, {len(fil)}',flush=True)
        try: fil.extend(f_.result())
        except Exception: pass
print(f'{len(fil)} biotech 8-Ks {LO:%Y-%m-%d}..{HI:%Y-%m-%d}',flush=True)

def scan(r):
    cik,acc=str(int(r['cik'])),r['accession'].replace('-','')
    txt=''
    if r['doc']:
        b=sec.get_bytes(ARCH.format(cik=cik,acc=acc,doc=r['doc']))
        if b: txt+=WS.sub(' ',TAGS.sub(' ',b.decode('utf-8','ignore')))
    blob=sec.get(IDX.format(cik=cik,acc=acc)) or {}
    for n in [i.get('name','') for i in (blob.get('directory') or {}).get('item',[])
              if EX.search(i.get('name','')) and i.get('name','').lower().endswith(('.htm','.html','.txt'))][:2]:
        b2=sec.get_bytes(ARCH.format(cik=cik,acc=acc,doc=n))
        if b2: txt+=' '+WS.sub(' ',TAGS.sub(' ',b2.decode('utf-8','ignore')))
    t=txt[:40000]
    m=FWD.search(t)
    if not (m or ADCOM.search(t)): return None
    sent=''
    for s in re.split(r'(?<=[.!?])\s+',t):
        if (m and m.group(0)[:40] in s) or (not m and ADCOM.search(s)):
            sent=s.strip()[:300]; break
    return {**r,'kind':'PDUFA' if m else 'ADCOM','hit':(m.group(0) if m else '')[:90],'sent':sent}

hits=[]
with ThreadPoolExecutor(max_workers=8) as ex:
    fu=[ex.submit(scan,r) for r in fil]
    for k,f_ in enumerate(as_completed(fu),1):
        if k%1500==0: print(f'  docs {k}/{len(fil)}, {len(hits)}',flush=True)
        try:
            v=f_.result()
        except Exception: v=None
        if v: hits.append(v)
h=pd.DataFrame(hits)
h.to_parquet(ROOT/'pdufa_forward.parquet')
print(f'\n{len(h)} filings with a forward action date or scheduled AdCom, {h.ticker.nunique()} names\n')
for r in h.sort_values('et').itertuples():
    print(f'{r.ticker:6s} {r.et:%m-%d %H:%M}  {r.kind:6s} {r.hit}')
