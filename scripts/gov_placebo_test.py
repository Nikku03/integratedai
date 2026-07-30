"""Is the trial signal an event effect or just a name effect?

For every gov event, compare the 10-session return from the day after the event
against the *same name's* average 10-session return from every other entry date in
the window. If a trial update carries information, the event dates should beat the
name's own baseline. If it does not, the two are equal and the apparent edge is
simply "companies running trials did fine this month" -- a name effect wearing an
event's clothes.
"""
import sys
sys.path.insert(0, '/home/user/integratedai/scripts')
import pandas as pd, numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from scipy import stats
from moonshot_census import daily_bars
from iai.core.config import Config
from iai.core.http import HttpClient

ROOT = Path('/root/.iai/wide2015')
cfg = Config.load()
yah = HttpClient(cfg.data.cache_dir, 'chhillarnaresh03@gmail.com',
                 rate_per_sec=12.0, ttl_hours=6.0)
fwd = pd.read_parquet(ROOT / 'gov_forward.parquet')


def baseline(tkr):
    """Mean 10-session forward return over every entry date the name offers."""
    try:
        b = daily_bars(yah, tkr, 40)
    except Exception:
        return None
    if b.empty or len(b) < 12:
        return None
    b = b.sort_values('date').reset_index(drop=True)
    o = b.open.to_numpy(dtype=float)
    c = b.close.to_numpy(dtype=float)
    rets = [c[min(i + 10, len(c) - 1)] / o[i] - 1.0
            for i in range(len(b)) if np.isfinite(o[i]) and o[i] > 0]
    return float(np.mean(rets)) if rets else None


names = sorted(fwd.ticker.unique())
base = {}
with ThreadPoolExecutor(max_workers=12) as p:
    futs = {p.submit(baseline, t): t for t in names}
    for fu in as_completed(futs):
        t = futs[fu]
        v = fu.result()
        if v is not None:
            base[t] = v

fwd['name_baseline'] = fwd.ticker.map(base)
f = fwd.dropna(subset=['name_baseline']).copy()
f['excess'] = f.d10 - f.name_baseline

print(f"{len(f)} events across {f.ticker.nunique()} names, "
      f"each compared with its OWN average 10-day return\n")
print(f"{'source':16s}{'n':>5s}{'event d10':>11s}{'name baseline':>15s}"
      f"{'excess':>9s}{'t(excess)':>11s}{'p':>8s}")
for s, g in list(f.groupby('source')) + [('ALL GOV', f)]:
    n = len(g)
    if n < 2:
        continue
    t, pv = stats.ttest_1samp(g.excess, 0.0)
    print(f"{s:16s}{n:5d}{g.d10.mean()*100:+10.2f}%{g.name_baseline.mean()*100:+14.2f}%"
          f"{g.excess.mean()*100:+8.2f}%{t:+11.2f}{pv:8.3f}")

tr = f[f.source.str.startswith('trial')]
t, pv = stats.ttest_1samp(tr.excess, 0.0)
print(f"\ntrials only: event {tr.d10.mean()*100:+.2f}%  own baseline "
      f"{tr.name_baseline.mean()*100:+.2f}%  excess {tr.excess.mean()*100:+.2f}%  "
      f"t={t:+.2f}  p={pv:.3f}")

# One observation per name, so 543 updates on 145 names cannot masquerade as 543
# independent draws.
g = f.groupby('ticker').agg(d10=('d10', 'mean'), bl=('name_baseline', 'first'))
t, pv = stats.ttest_1samp(g.d10 - g.bl, 0.0)
print(f"one obs per name (n={len(g)}): excess {(g.d10 - g.bl).mean()*100:+.2f}%  "
      f"t={t:+.2f}  p={pv:.3f}")
