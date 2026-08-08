"""The vol-band rule was found on TEST. Validation was never used to fit the
gradient-boosting models (no early stopping), so it is a clean holdout for it."""
import sys; sys.path.insert(0,'/home/user/integratedai/scripts')
import numpy as np, pandas as pd, pyarrow.parquet as pq
from pathlib import Path
from sklearn.ensemble import HistGradientBoostingClassifier
from adrnn_train import build_arrays, robust_scaler, split_idx
R=Path('/root/.iai/wide2015')
d,X,feats,idx=build_arrays(R/'adrnn_panel.parquet',10)
lab=pq.read_table(R/'adrnn_panel.parquet',columns=['max_up','max_dn']).to_pandas()
y_up=(lab.max_up.to_numpy(float)>=.20).astype(np.float32)
y_dn=(lab.max_dn.to_numpy(float)<=-.20).astype(np.float32)
tr,va,te=split_idx(d,idx)
tr=tr[np.linspace(0,len(tr)-1,150000).astype(int)]
med,sc=robust_scaler(X,tr); flat=lambda r:(X[r]-med)/sc
mup=HistGradientBoostingClassifier(max_iter=200,learning_rate=.06,max_depth=6,random_state=0).fit(flat(tr),y_up[tr])
mdn=HistGradientBoostingClassifier(max_iter=200,learning_rate=.06,max_depth=6,random_state=0).fit(flat(tr),y_dn[tr])
px=pd.read_parquet(R/'w2015_prices.parquet',columns=['date','ticker','open','close'])
px['date']=pd.to_datetime(px.date); px=px.sort_values(['ticker','date']).reset_index(drop=True)
o=px.open.to_numpy(float); c=px.close.to_numpy(float); tk=px.ticker.to_numpy()
vi=feats.index('vol_20d')

def build(rows):
    ret=np.full(len(rows),np.nan)
    for a,i in enumerate(rows):
        j0=i+1
        if j0>=len(o) or tk[j0]!=tk[i]: continue
        j=min(j0+9,len(o)-1)
        while j>j0 and tk[j]!=tk[i]: j-=1
        if np.isfinite(o[j0]) and o[j0]>0 and np.isfinite(c[j]): ret[a]=c[j]/o[j0]-1
    su=mup.predict_proba(flat(rows))[:,1]; sd=mdn.predict_proba(flat(rows))[:,1]
    t=pd.DataFrame({'date':pd.to_datetime(d['date'].to_numpy()[rows]),'su':su,'sd':sd,
                    'net':su-sd,'y_up':y_up[rows],'y_dn':y_dn[rows],'ret':ret,
                    'vol':X[rows,vi]}).dropna(subset=['ret'])
    # the vol band is defined by the TRAIN distribution, not the evaluation set,
    # so the rule is applicable live rather than needing the future to define it
    return t

qs=np.quantile(X[tr,vi],[0.6,0.9])
print(f'vol band from TRAIN quantiles: {qs[0]:.4f} .. {qs[1]:.4f} (deciles 7-9 by train)')

for nm,rows in (('VALIDATION 2023-01..2024-06  (clean holdout)',va),
                ('TEST 2024-07..2025-12  (where the rule was found)',te)):
    t=build(rows)
    band=t[(t.vol>=qs[0])&(t.vol<qs[1])]
    print(f'\n{"="*88}\n{nm}\n{"="*88}')
    print(f'  all rows n={len(t):,}  P(up){t.y_up.mean()*100:5.2f}% P(dn){t.y_dn.mean()*100:5.2f}% '
          f'edge{(t.y_up.mean()-t.y_dn.mean())*100:+5.2f}pp  ret{t.ret.mean()*100:+.2f}%')
    for k in (1,3,5,10):
        naive=t[t.groupby('date')['y_up'].transform('size')>=k].sort_values('su',ascending=False).groupby('date').head(k)
        g=band[band.groupby('date')['y_up'].transform('size')>=k].sort_values('net',ascending=False).groupby('date').head(k)
        if g.empty: continue
        wk=g.date.dt.to_period('W').astype(str).to_numpy(); rng=np.random.default_rng(41)
        uw=np.unique(wk); wh={w:np.flatnonzero(wk==w) for w in uw}; r=g.ret.to_numpy()
        bs=np.array([np.mean(r[np.concatenate([wh[w] for w in rng.choice(uw,len(uw),True)])]) for _ in range(8000)])
        lo,hi=np.percentile(bs,[2.5,97.5])
        print(f'  k={k:<3d} NAIVE P(up) rank: ret{naive.ret.mean()*100:+6.2f}%  edge{(naive.y_up.mean()-naive.y_dn.mean())*100:+6.1f}pp'
              f'   |  BAND+net: ret{r.mean()*100:+6.2f}% edge{(g.y_up.mean()-g.y_dn.mean())*100:+6.1f}pp '
              f'win{(g.ret>0).mean()*100:4.1f}% CI[{lo*100:+.2f},{hi*100:+.2f}] P(<=0)={np.mean(bs<=0):.3f}')
