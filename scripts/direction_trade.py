"""Predict, at filing time, whether a +20% or -20% move follows -- then trade it.

Classifying already-known movers is not a strategy: it needs the move to have
happened. The tradable question is the forward one -- of all filings, which are
followed by a large UP move rather than a large DOWN move -- and it is answered
here with a rule built on 1-14 July and scored on 15-29 July, so nothing from the
test half touches the fit.
"""
import sys
sys.path.insert(0, '/home/user/integratedai/scripts')
import numpy as np, pandas as pd
from pathlib import Path
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

ROOT = Path('/root/.iai/wide2015')
CACHE = Path('/root/.iai/minutecache')
SPLIT = pd.Timestamp('2026-07-15', tz='America/New_York')
BEARISH = {"3.01", "3.02", "4.02", "1.03", "2.06", "2.05", "2.04"}
BULLISH = {"2.01", "1.01", "8.01"}
SCHED = {"2.02", "7.01"}
HORIZON = 5 * 390          # five sessions of bars

fil = pd.read_parquet(ROOT / 'recent_filings.parquet')
fil['accepted'] = pd.to_datetime(fil['accepted'], utc=True, format='mixed')
fil['et'] = fil.accepted.dt.tz_convert('America/New_York')
fil = fil[(fil.et >= pd.Timestamp('2026-07-01', tz='America/New_York')) &
          (fil.et <= pd.Timestamp('2026-07-29', tz='America/New_York'))].copy()
fil['codes'] = fil['items'].fillna('').apply(
    lambda s: {c.strip() for c in str(s).split(',') if c.strip()})

rows = []
for tkr, grp in fil.groupby('ticker'):
    p = CACHE / f'{tkr}.parquet'
    if not p.exists():
        continue
    b = pd.read_parquet(p)
    if b.empty or 't_utc' not in b.columns:
        continue
    b = b.sort_values('t_utc').reset_index(drop=True)
    tv = b.t_utc.to_numpy()
    traded = b.volume.fillna(0).to_numpy() > 0
    close = b.close.to_numpy(dtype=float)
    hi = b.high.to_numpy(dtype=float)
    lo = b.low.to_numpy(dtype=float)
    for r in grp.itertuples():
        t0 = np.datetime64(r.accepted.tz_convert('UTC').tz_localize(None))
        i0 = int(np.searchsorted(tv, t0 + np.timedelta64(1, 'm'), 'left'))
        fwd = np.nonzero(traded[i0:])[0]
        if not len(fwd):
            continue
        i = i0 + int(fwd[0])
        e = float(hi[i])
        if not np.isfinite(e) or e < 1.0:
            continue
        # ---- ex-ante features, from bars strictly before the fill ----
        pj = max(0, i - 5 * 390)
        prior = b.iloc[pj:i]
        prior = prior[prior.volume.fillna(0) > 0]
        if len(prior) < 30:
            continue
        rr = prior.close.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        if len(rr) < 10:
            continue
        pre_vol = float(rr.std() * np.sqrt(390))
        dollars = float((prior.close * prior.volume).sum())
        if dollars < 250_000:
            continue
        # ---- forward label ----
        j = min(i + HORIZON, len(b) - 1)
        seg_t = traded[i + 1:j + 1]
        if not seg_t.any():
            continue
        up = np.where(seg_t, hi[i + 1:j + 1] / e - 1.0, -np.inf).max()
        dn = np.where(seg_t, lo[i + 1:j + 1] / e - 1.0, np.inf).min()
        if abs(up) > 3 or abs(dn) > 3:
            continue                              # split artifact
        rows.append({
            'ticker': tkr, 'et': r.et, 'entry': e,
            'has_8k': str(r.form).upper().startswith('8-K'),
            'sched': bool(r.codes & SCHED),
            'bearish': bool(r.codes & BEARISH),
            'bullish': bool(r.codes & BULLISH),
            'offering': str(r.form).upper().startswith(('424B', 'S-1', 'S-3', 'F-')),
            'insider': str(r.form).strip() in ('4', '144', '3'),
            'pre_vol': pre_vol, 'log_dollars': np.log10(dollars),
            'log_price': np.log10(e),
            'fwd_up': up, 'fwd_dn': dn,
            'up20': up >= 0.20, 'dn20': dn <= -0.20})

d = pd.DataFrame(rows)
print(f"{len(d):,} filings with ex-ante features and a forward 5-session label")
print(f"  reached +20%: {d.up20.sum():4d} ({d.up20.mean()*100:.1f}%)")
print(f"  reached -20%: {d.dn20.sum():4d} ({d.dn20.mean()*100:.1f}%)")

# Direction problem: among filings that hit ONE of the barriers, which one?
one = d[d.up20 ^ d.dn20].copy()
one['y'] = one.up20.astype(int)
print(f"\nfilings hitting exactly one barrier: {len(one)} "
      f"({one.y.mean()*100:.1f}% up)")

FEATS = ['has_8k', 'sched', 'bearish', 'bullish', 'offering', 'insider',
         'pre_vol', 'log_dollars', 'log_price']
tr = one[one.et < SPLIT]
te = one[one.et >= SPLIT]
print(f"train (1-14 Jul) n={len(tr)}   test (15-29 Jul) n={len(te)}")
if len(tr) < 30 or len(te) < 30:
    print("too few to fit"); sys.exit(0)

X = tr[FEATS].astype(float).to_numpy()
m = LogisticRegression(max_iter=2000, C=1.0).fit(X, tr.y)
pte = m.predict_proba(te[FEATS].astype(float).to_numpy())[:, 1]
auc = roc_auc_score(te.y, pte)
print(f"\nOUT-OF-SAMPLE AUC on 15-29 July: {auc:.4f}   "
      f"(0.5 = coin; base rate {te.y.mean():.1%} up)")
print("\ncoefficients (positive = predicts UP):")
for f, c in sorted(zip(FEATS, m.coef_[0]), key=lambda x: -abs(x[1])):
    print(f"  {f:14s}{c:+.3f}")

te = te.copy(); te['p'] = pte
for q in (0.5, 0.6, 0.7):
    sel = te[te.p >= q]
    if len(sel) < 5:
        continue
    print(f"\n  take p>={q:.1f}: n={len(sel)}, actually up {sel.y.mean()*100:.0f}% "
          f"(base {te.y.mean()*100:.0f}%), mean fwd_up {sel.fwd_up.mean()*100:+.1f}%, "
          f"mean fwd_dn {sel.fwd_dn.mean()*100:+.1f}%")

# The tradable version: buy at the fill, 20% target, 20% stop, 5 sessions.
print("\nTRADING THE RULE on 15-29 July (buy at fill, +20% target, -20% stop):")
for q in (0.0, 0.5, 0.6):
    allte = d[d.et >= SPLIT].copy()
    pall = m.predict_proba(allte[FEATS].astype(float).to_numpy())[:, 1]
    allte['p'] = pall
    sel = allte[allte.p >= q]
    if not len(sel):
        continue
    # whichever barrier is touched first is unknown from max/min alone, so the
    # conservative reading books a stop whenever both are touched
    ret = np.where(sel.dn20, -0.20, np.where(sel.up20, 0.20, sel.fwd_up * 0))
    ret = np.where(sel.dn20 & sel.up20, -0.20, ret)
    print(f"  p>={q:.1f}: n={len(sel):4d}  mean {ret.mean()*100:+.2f}%  "
          f"up {sel.up20.mean()*100:4.1f}%  down {sel.dn20.mean()*100:4.1f}%")
d.to_parquet(ROOT / 'direction_filings.parquet')
