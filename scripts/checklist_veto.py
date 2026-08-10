"""Loser-avoidance has been the one repeatable theme. Test it as a VETO:
are there conditions that reliably predict a disaster (ret <= -20%)?"""
import sys; sys.path.insert(0,'/home/user/integratedai/scripts')
import numpy as np, pandas as pd
from pathlib import Path
from adrnn_train import build_arrays
from trade_checklist import candidate_questions, DERIVE_END, COST
R=Path('/root/.iai/wide2015')
p=pd.read_parquet(R/'tail_anatomy_picks.parquet'); p['net']=p.ret-COST
d,X,feats,idx=build_arrays(R/'adrnn_panel.parquet',10)
fr=pd.DataFrame(X[p.row.to_numpy()],columns=feats)
for c in ('date','mup','net'): fr[c]=p[c].to_numpy()
fr['date']=pd.to_datetime(fr['date'])
der=fr[fr.date<DERIVE_END]; tst=fr[fr.date>=DERIVE_END]
print(f'disaster rate (ret<=-20%): derive {(der.net<=-.2).mean()*100:.1f}%  test {(tst.net<=-.2).mean()*100:.1f}%')
qd=candidate_questions(der); qt=candidate_questions(tst)
rng=np.random.default_rng(29); rows=[]
for k in qd:
    if k not in qt: continue
    md=qd[k].fillna(False); mt=qt[k].fillna(False)
    if not (0.08<=md.mean()<=0.92): continue
    dy,dn=der[md],der[~md]; ty,tn=tst[mt],tst[~mt]
    if min(len(dy),len(dn),len(ty),len(tn))<25: continue
    # effect on DISASTER rate: negative = the condition protects you
    dd=((dy.net<=-.2).mean()-(dn.net<=-.2).mean())*100
    dt=((ty.net<=-.2).mean()-(tn.net<=-.2).mean())*100
    a=np.array([(rng.choice((ty.net<=-.2).to_numpy().astype(float),len(ty),True).mean()
                -rng.choice((tn.net<=-.2).to_numpy().astype(float),len(tn),True).mean())*100
                for _ in range(20000)])
    lo,hi=np.percentile(a,[2.5,97.5])
    rows.append({'question':k,'derive_dis':dd,'test_dis':dt,'lo':lo,'hi':hi,
                 'p_prot':(a>=0).mean(),'same':np.sign(dd)==np.sign(dt),
                 'dis_yes':(ty.net<=-.2).mean()*100,'dis_no':(tn.net<=-.2).mean()*100})
r=pd.DataFrame(rows).sort_values('test_dis')
print('\n'+'='*112)
print('AS A VETO: does the condition REDUCE the disaster rate (ret <= -20%)?  negative = protective')
print('='*112)
print(r.round(2).to_string(index=False))
prot=r[(r.same)&(r.hi<0)]
print(f'\nprotective in BOTH periods with test CI excluding zero: {len(prot)}')
if len(prot): print(prot.round(2).to_string(index=False))

print('\n'+'='*112); print('SIZING: what the risk actually requires'); print('='*112)
n=p.sort_values('date').reset_index(drop=True)
for slots in (4,10,20):
    w=1/slots; e=[1.0]
    for x in n.net.to_numpy(): e.append(e[-1]*(1+w*x))
    e=np.array(e[1:]); pk=np.maximum.accumulate(e)
    print(f'  {slots:2d} slots (1/{slots} each): final {e[-1]:6.2f}x  maxDD {(e/pk-1).min()*100:6.1f}%')
for frac in (0.5,0.25):
    w=frac/10; e=[1.0]
    for x in n.net.to_numpy(): e.append(e[-1]*(1+w*x))
    e=np.array(e[1:]); pk=np.maximum.accumulate(e)
    print(f'  10 slots at {frac:.0%} of full size: final {e[-1]:6.2f}x  maxDD {(e/pk-1).min()*100:6.1f}%')
