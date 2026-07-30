"""Event-anchored forward test on FDA / trial events, comparable to the 8-K run."""
import sys, logging
sys.path.insert(0, '/home/user/integratedai/scripts')
import pandas as pd, numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from moonshot_census import daily_bars
from iai.core.config import Config
from iai.core.http import HttpClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
ROOT = Path('/root/.iai/wide2015')
cfg = Config.load()
yah = HttpClient(cfg.data.cache_dir, 'chhillarnaresh03@gmail.com',
                 rate_per_sec=12.0, ttl_hours=6.0)

ev = pd.read_parquet(ROOT / 'gov_events.parquet')
ev = ev[ev.ticker.notna()].copy()
ev['date'] = pd.to_datetime(ev['date'])
by = {t: g for t, g in ev.groupby('ticker')}
logging.info('%d matched events across %d names', len(ev), len(by))


def work(tkr):
    try:
        b = daily_bars(yah, tkr, 40)
    except Exception:
        return []
    if b.empty or len(b) < 8:
        return []
    b = b.sort_values('date').reset_index(drop=True)
    out = []
    for e in by[tkr].itertuples():
        # Government sources are date-only, so the earliest actionable price is
        # the open of the session AFTER the publication date.
        nxt = b[b.date > e.date.normalize()]
        if nxt.empty:
            continue
        i = nxt.index[0]
        o = float(b.open.iloc[i])
        if not np.isfinite(o) or o <= 0:
            continue
        pri = b.iloc[max(0, i - 10):i]
        if pri.empty:
            continue
        md = float((pri.close * pri.volume.fillna(0)).median())
        if o < 1.0 or md < 250_000:
            continue
        rec = {'source': e.source, 'ticker': tkr, 'date': e.date, 'open': o}
        for h, lab in ((0, 'd0'), (1, 'd1'), (5, 'd5'), (10, 'd10')):
            j = min(i + h, len(b) - 1)
            rec[lab] = float(b.close.iloc[j]) / o - 1.0
            rec['pk_' + lab] = float(b.high.iloc[i:j + 1].max()) / o - 1.0
        out.append(rec)
    return out


rows = []
with ThreadPoolExecutor(max_workers=12) as p:
    futs = {p.submit(work, t): t for t in by}
    for fu in as_completed(futs):
        rows.extend(fu.result())

d = pd.DataFrame(rows)
d.to_parquet(ROOT / 'gov_forward.parquet')
print(f"\n{len(d)} tradable gov events, entry at next session open\n")
print(f"{'source':16s}{'n':>5s}{'d0':>8s}{'d1':>8s}{'d5':>8s}{'d10':>8s}{'t(d10)':>8s}{'pk>=10%':>9s}")
for s, g in d.groupby('source'):
    n = len(g)
    t = g.d10.mean() / (g.d10.std(ddof=1) / np.sqrt(n)) if n > 1 else np.nan
    print(f"{s:16s}{n:5d}{g.d0.mean()*100:+7.2f}%{g.d1.mean()*100:+7.2f}%"
          f"{g.d5.mean()*100:+7.2f}%{g.d10.mean()*100:+7.2f}%{t:+8.2f}"
          f"{(g.pk_d10>=.10).mean()*100:8.0f}%")
n = len(d)
t = d.d10.mean() / (d.d10.std(ddof=1) / np.sqrt(n))
print(f"{'ALL GOV':16s}{n:5d}{d.d0.mean()*100:+7.2f}%{d.d1.mean()*100:+7.2f}%"
      f"{d.d5.mean()*100:+7.2f}%{d.d10.mean()*100:+7.2f}%{t:+8.2f}"
      f"{(d.pk_d10>=.10).mean()*100:8.0f}%")

a8 = pd.read_parquet(ROOT / 'nextopen_all8k.parquet')
n8 = len(a8)
t8 = a8.d10.mean() / (a8.d10.std(ddof=1) / np.sqrt(n8))
print(f"{'(8-K, same rule)':16s}{n8:5d}{a8.d0.mean()*100:+7.2f}%{a8.d1.mean()*100:+7.2f}%"
      f"{a8.d5.mean()*100:+7.2f}%{a8.d10.mean()*100:+7.2f}%{t8:+8.2f}"
      f"{(a8.pk_d10>=.10).mean()*100:8.0f}%")

sub = d[d.source.isin(['fda_drug', 'fda_pma', 'fda_510k'])]
if len(sub) > 1:
    t = sub.d10.mean() / (sub.d10.std(ddof=1) / np.sqrt(len(sub)))
    print(f"\nFDA only (drug+device), n={len(sub)}: d10 {sub.d10.mean()*100:+.2f}%  "
          f"median {sub.d10.median()*100:+.2f}%  t={t:+.2f}  "
          f"win {(sub.d10>0).mean()*100:.0f}%")
tr = d[d.source.str.startswith('trial')]
if len(tr) > 1:
    t = tr.d10.mean() / (tr.d10.std(ddof=1) / np.sqrt(len(tr)))
    print(f"Trials only, n={len(tr)}: d10 {tr.d10.mean()*100:+.2f}%  "
          f"median {tr.d10.median()*100:+.2f}%  t={t:+.2f}  "
          f"win {(tr.d10>0).mean()*100:.0f}%")
