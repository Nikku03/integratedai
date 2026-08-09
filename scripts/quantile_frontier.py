"""The moonshot/profit frontier at k=1 -- the 20-trades-a-month book."""
import sys; sys.path.insert(0,'/home/user/integratedai/scripts')
import numpy as np, pandas as pd
from pathlib import Path
from sklearn.ensemble import HistGradientBoostingRegressor
from adrnn_train import build_arrays
from moonshot_tail import forward, blocks, scale_fit
R=Path('/root/.iai/wide2015')
d,X,feats,idx=build_arrays(R/'adrnn_panel.parquet',10)
px=pd.read_parquet(R/'w2015_prices.parquet',columns=['date','ticker','open','high','low','close','volume'])
px['date']=pd.to_datetime(px.date); px=px.sort_values(['ticker','date']).reset_index(drop=True)
ret,mup=forward(px,idx)
vi=feats.index('vol_20d'); vol=X[idx,vi]
ok=np.isfinite(ret)&np.isfinite(mup)&np.isfinite(vol)&(vol>0)
tab=pd.DataFrame({'row':idx,'date':pd.to_datetime(d['date'].to_numpy()[idx]),
                  'vol':vol,'ret':ret,'mup':mup})[ok].reset_index(drop=True)
Xs=X[tab.row.to_numpy()]
COST=20/1e4
CFG=[('mean (vol-scaled)','reg',None),('quantile q60','quant',.60),
     ('quantile q75','quant',.75),('quantile q80','quant',.80),('quantile q85','quant',.85)]
res={n:[] for n,_,_ in CFG}
for b0,b1 in blocks(tab.date.max()):
    tr=np.flatnonzero(tab.date<b0-pd.Timedelta(days=14)); te=np.flatnonzero((tab.date>=b0)&(tab.date<b1))
    if len(tr)<40000 or len(te)<500: continue
    if len(tr)>150000: tr=tr[np.linspace(0,len(tr)-1,150000).astype(int)]
    med,sc=scale_fit(Xs[tr]); ztr=np.clip((Xs[tr]-med)/sc,-5,5); zte=np.clip((Xs[te]-med)/sc,-5,5)
    sub=tab.iloc[te]; uni=float(sub.ret.mean())
    for n,kind,q in CFG:
        if kind=='reg':
            y=(tab.ret/np.maximum(tab.vol,.01)).to_numpy()
            m=HistGradientBoostingRegressor(max_iter=250,learning_rate=.05,max_depth=6,random_state=0)
            m.fit(ztr,np.clip(y[tr],np.percentile(y[tr],.5),np.percentile(y[tr],99.5)))
        else:
            y=tab.ret.to_numpy()
            m=HistGradientBoostingRegressor(loss='quantile',quantile=q,max_iter=250,
                                            learning_rate=.05,max_depth=6,random_state=0).fit(ztr,y[tr])
        s=sub.assign(pred=m.predict(zte))
        p=s.sort_values('pred',ascending=False).groupby('date').head(1)
        res[n].append({'ret':float(p.ret.mean())-COST,'excess':float(p.ret.mean())-COST-uni,
                       'p50':float((p.mup>=.5).mean()),'p100':float((p.mup>=1.).mean()),
                       'p20':float((p.mup>=.2).mean()),'win':float((p.ret>0).mean()),
                       'best':float(p.ret.max())})
b50=(tab.mup>=.5).mean(); b100=(tab.mup>=1.).mean(); b20=(tab.mup>=.2).mean()
print(f"\n{'='*104}\nk=1 (20 TRADES/MONTH): THE MOONSHOT / PROFIT FRONTIER\n{'='*104}")
print(f"{'objective':20s} {'blocks':>7s} {'ret/trade%':>11s} {'excess%':>9s} {'P(+20%)':>9s} "
      f"{'P(+50%)':>9s} {'P(+100%)':>9s} {'lift50':>7s} {'win%':>6s} {'book/mo%':>9s}")
for n,_,_ in CFG:
    r=pd.DataFrame(res[n])
    if r.empty: continue
    mo=((1+r.ret.mean())**2.1-1)*100
    print(f"{n:20s} {int((r.excess>0).sum()):>3d}/{len(r):<3d} {r.ret.mean()*100:+11.3f} "
          f"{r.excess.mean()*100:+9.3f} {r.p20.mean()*100:8.2f}% {r.p50.mean()*100:8.2f}% "
          f"{r.p100.mean()*100:8.2f}% {r.p50.mean()/b50:6.1f}x {r.win.mean()*100:5.1f} {mo:+9.2f}")
print(f"{'universe base rate':20s} {'-':>7s} {'-':>11s} {'-':>9s} {b20*100:8.2f}% "
      f"{b50*100:8.2f}% {b100*100:8.2f}%")
