"""Pick the filings most likely to produce a tail move, then let winners run.

The exit half is settled: dropping the 6% target beats keeping it on every
variant tried. The open half is selection -- which filings deserve the no-target
treatment, decided *before* the move.

Why the features below and not others
-------------------------------------
Choosing predictors after looking at which filings happened to run is how you
fit noise on a sample of 83. So the features here are fixed on mechanical
grounds, stated before measurement, and each has a reason that does not depend
on this month's outcomes:

``pre_vol``
    Realised volatility of the stock's own minute returns over the five
    sessions *before* the filing. A name that normally moves 0.4% a day does not
    produce a 20% day because a press release was good; one that routinely moves
    8% can. This is the scale parameter of the whole distribution, and it is the
    single most defensible ex-ante predictor of the *size* of any move.

``illiq``
    Dollar volume over the prior session, inverted. Depth is what absorbs
    demand. The same buying pressure that moves a $50m-a-day name 1% moves a
    $200k-a-day name 20%. Thin books make tails.

``cheap``
    Reciprocal price. A $2 stock moves in ticks that are whole percents, and
    the marginal buyer of a $2 stock is not the marginal buyer of a $200 one.

``binary``
    Whether the catalyst is a step change (merger, FDA decision, contract award,
    financing, going concern, auditor change) or a recurring disclosure
    (quarterly earnings, dividends, buybacks, officer changes, vote results).
    A step change re-prices the company; a quarterly number updates an estimate
    the market already had. Assigned from item codes and filing text -- never
    from the return.

All four are known at filing time. The score is a plain average of within-sample
ranks with no fitted weights, because any weight I chose would be chosen knowing
the answer.

What the test has to beat
-------------------------
Taking the top-K of anything from 83 filings will look good roughly half the
time. So the selected set is compared against **random subsets of the same
size**, drawn from the same pool, 20,000 times. If the ranking carries no
information the observed result sits inside that null, and the p-value says so.

Usage
-----
    python scripts/moonshot_select.py --top 20 --rule "trail 20%"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from moonshot_scan import walk  # noqa: E402  - shared, volume-aware exit walk

#: Sessions of history used for the pre-event volatility estimate.
VOL_LOOKBACK_SESSIONS = 5
BARS_PER_SESSION = 390

#: Item codes that are, on their face, step changes rather than recurring
#: disclosure. 1.01 material agreement, 2.01 completed acquisition, 3.02
#: unregistered sales (dilution), 4.01 auditor change, 4.02 non-reliance.
BINARY_ITEMS = {"1.01", "2.01", "3.02", "4.01", "4.02", "1.03", "2.04", "3.01"}

#: Text markers of a step change, applied to the grader's own summary. Chosen to
#: name event *kinds*, not outcomes -- "approval" and "rejected" both qualify,
#: because both re-price the company.
BINARY_TEXT = (
    "merger", "acquisition", "acquired", "acquire", "definitive agreement",
    "tender offer", "fda", "approval", "clinical", "phase 3", "phase iii",
    "trial", "contract", "award", "warrant", "convertible", "offering",
    "at-the-market", "shelf", "going concern", "auditor", "bankruptcy",
    "delisting", "patent", "licence", "license", "partnership",
)
#: Text markers of recurring disclosure. Checked only when nothing above hits.
RECURRING_TEXT = (
    "quarter", "fiscal", "dividend", "repurchase", "buyback", "annual meeting",
    "shareholder vote", "director", "appointed", "resigned", "retirement",
    "guidance",
)


def is_binary(items: str, text: str) -> bool:
    """Step change or routine update? Decided from the filing, not the return."""
    codes = {c.strip() for c in (items or "").split(",")}
    if codes & BINARY_ITEMS:
        return True
    low = (text or "").lower()
    if any(k in low for k in BINARY_TEXT):
        return True
    return not any(k in low for k in RECURRING_TEXT)


def pre_event_features(bars: pd.DataFrame, i_ent: int) -> dict:
    """Volatility and depth from bars strictly before the entry bar.

    Nothing at or after ``i_ent`` is read. Zero-volume bars are dropped first --
    a quarter of them are stale quotes, and leaving them in both understates
    volatility (long runs of unchanged prints) and overstates depth.
    """
    lo = max(0, i_ent - VOL_LOOKBACK_SESSIONS * BARS_PER_SESSION)
    prior = bars.iloc[lo:i_ent]
    prior = prior[prior["volume"].fillna(0) > 0]
    if len(prior) < 30:
        return {"pre_vol": np.nan, "prior_dollars": np.nan}

    r = prior["close"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    # Scale minute-return dispersion to a daily figure so the number is
    # readable; the ranking is unaffected by the constant.
    vol = float(r.std() * np.sqrt(BARS_PER_SESSION)) if len(r) > 10 else np.nan
    return {"pre_vol": vol,
            "prior_dollars": float((prior["close"] * prior["volume"]).sum())}


def build(root: Path, bd: Path, max_bars: int) -> pd.DataFrame:
    m = pd.read_parquet(root / "classified_final.parquet")
    m["filed_utc"] = pd.to_datetime(m["filed_et"], utc=True)
    cap = (pd.read_parquet(root / "catalyst_candidates.parquet")
             .drop_duplicates("accession")[["accession", "market_cap"]])
    m = m.merge(cap, on="accession", how="left")

    rows = []
    for f in m.to_dict("records"):
        p = bd / f"{f['ticker']}.parquet"
        if not p.exists():
            continue
        b = pd.read_parquet(p)
        tv = b["t_utc"].to_numpy()
        t = np.datetime64(f["filed_utc"].tz_convert("UTC").tz_localize(None))
        i = int(np.searchsorted(tv, t + np.timedelta64(1, "m"), "left"))
        if i >= len(b) or not (float(b["volume"].iloc[i]) > 0):
            continue
        e = float(b["high"].iloc[i])
        if not np.isfinite(e) or e <= 0:
            continue

        feats = pre_event_features(b, i)
        seg = b.iloc[i + 1: min(i + max_bars, len(b) - 1) + 1]
        seg = seg[seg["volume"].fillna(0) > 0]
        if seg.empty or not np.isfinite(feats["pre_vol"]):
            continue

        rec = {"ticker": f["ticker"], "accession": f["accession"],
               "band": f["band"],
               "verdict": f["final_verdict"], "impact": f["final_impact"],
               "items": f["items"], "entry": e, "cap": f.get("market_cap"),
               "binary": is_binary(f["items"], f.get("what_happened", "")),
               "ceiling": float(seg["high"].max()) / e - 1.0,
               **feats}
        for label, tgt, stp, trl in (("6% target / 10% stop", 0.06, 0.10, None),
                                     ("no target / 10% stop", None, 0.10, None),
                                     ("trail 15%", None, 0.15, 0.15),
                                     ("trail 20%", None, 0.20, 0.20)):
            px, why, _ = walk(b, i, e, tgt, stp, trl, max_bars)
            rec[label] = px / e - 1.0
        rows.append(rec)

    d = pd.DataFrame(rows)
    # Equal-weight rank average. No fitted coefficients: any weighting I picked
    # would be picked knowing which filings ran.
    d["r_vol"] = d["pre_vol"].rank(pct=True)
    d["r_illiq"] = (-d["prior_dollars"]).rank(pct=True)
    d["r_cheap"] = (-d["entry"]).rank(pct=True)
    d["r_binary"] = d["binary"].astype(float)
    d["score"] = d[["r_vol", "r_illiq", "r_cheap", "r_binary"]].mean(axis=1)
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--bars", default="/root/.iai/minutecache")
    ap.add_argument("--max-hold-bars", type=int, default=3900)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--rule", default="trail 20%")
    ap.add_argument("--exclude-traps", action="store_true",
                    help="drop filings graded trap before ranking")
    ap.add_argument("--perm", type=int, default=20000)
    args = ap.parse_args(argv)

    d = build(Path(args.root), Path(args.bars), args.max_hold_bars)
    pool = d[d.verdict != "trap"] if args.exclude_traps else d
    pool = pool.sort_values("score", ascending=False).reset_index(drop=True)
    d.to_parquet(Path(args.root) / "moonshot_select.parquet")

    print(f"pool {len(pool)} filings"
          f"{' (traps excluded)' if args.exclude_traps else ''}, "
          f"taking top {args.top} by score, exit rule '{args.rule}'\n")

    print("does each feature separate the tail, on its own?")
    print(f"  {'feature':12s}{'top-half ceiling':>18s}{'bottom-half':>13s}"
          f"{'top-half >=10%':>16s}")
    for f, col in (("pre_vol", "r_vol"), ("illiquidity", "r_illiq"),
                   ("cheapness", "r_cheap")):
        hi = pool[pool[col] >= pool[col].median()]
        lo = pool[pool[col] < pool[col].median()]
        print(f"  {f:12s}{hi.ceiling.median() * 100:+17.2f}%"
              f"{lo.ceiling.median() * 100:+12.2f}%"
              f"{(hi.ceiling >= .10).mean() * 100:15.0f}%")
    hb = pool[pool.binary], pool[~pool.binary]
    print(f"  {'binary':12s}{hb[0].ceiling.median() * 100:+17.2f}%"
          f"{hb[1].ceiling.median() * 100:+12.2f}%"
          f"{(hb[0].ceiling >= .10).mean() * 100:15.0f}%   "
          f"(n={len(hb[0])} vs {len(hb[1])})")

    sel = pool.head(args.top)
    rest = pool.tail(len(pool) - args.top)
    r = args.rule
    print(f"\n{'':22s}{'n':>4s}{'mean':>9s}{'median':>9s}{'win':>6s}"
          f"{'>=10% hit':>11s}{'best':>9s}")
    for lab, g in (("selected", sel), ("not selected", rest), ("whole pool", pool)):
        print(f"{lab:22s}{len(g):4d}{g[r].mean() * 100:+8.2f}%"
              f"{g[r].median() * 100:+8.2f}%{(g[r] > 0).mean() * 100:5.0f}%"
              f"{(g.ceiling >= .10).mean() * 100:10.0f}%{g[r].max() * 100:+8.1f}%")

    # The only test that matters: beat a random pick of the same size.
    rng = np.random.default_rng(3)
    vals = pool[r].to_numpy()
    obs = sel[r].mean()
    null = np.array([rng.choice(vals, args.top, replace=False).mean()
                     for _ in range(args.perm)])
    print(f"\nvs {args.perm:,} random picks of {args.top} from the same pool: "
          f"observed {obs * 100:+.2f}%, null mean {null.mean() * 100:+.2f}%, "
          f"p={(null >= obs).mean():.4f}")

    print(f"\nselected filings, exit rule '{r}':")
    print(f"{'tkr':6s}{'band':7s}{'verdict':9s}{'score':>6s}{'preVol':>8s}"
          f"{'$prior':>10s}{'px':>8s}{'bin':>4s}{'ceiling':>9s}{'ret':>8s}")
    for _, x in sel.iterrows():
        print(f"{x.ticker:6s}{x.band:7s}{x.verdict:9s}{x.score:6.2f}"
              f"{x.pre_vol * 100:7.1f}%{x.prior_dollars:10,.0f}{x.entry:8.2f}"
              f"{'Y' if x.binary else 'n':>4s}{x.ceiling * 100:+8.1f}%"
              f"{x[r] * 100:+7.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def portfolio(d: pd.DataFrame, root: Path, bd: Path, *, slots: int, capital: float,
              pctile: float, warmup: int, stop: float, trail: float,
              max_bars: int) -> pd.DataFrame:
    """Chronological portfolio, no profit target, selection decided causally.

    Ranking the month's filings against each other and taking the top 20 is a
    peek: it needs the month to be over. Here each filing is ranked against the
    ``pre_vol`` of only the filings *already seen*, so the decision uses nothing
    from the future. The first ``warmup`` filings build the distribution and are
    not traded, which costs coverage and is the price of the rule being real.
    """
    m = pd.read_parquet(root / "classified_final.parquet")
    m["filed_utc"] = pd.to_datetime(m["filed_et"], utc=True)
    # Join on accession, not ticker. A ticker with two filings in the window
    # cartesian-joins on the ticker key, and the surviving row then carries
    # another filing's timestamp -- which silently moves the entry.
    d = d.merge(m[["accession", "filed_et", "filed_utc"]], on="accession",
                how="left").sort_values("filed_utc")

    cash, open_pos, trades, seen = capital, [], [], []
    for f in d.to_dict("records"):
        t = f["filed_utc"]
        still = []
        for p in open_pos:
            if p["exit_t"] <= t:
                cash += p["proceeds"]
                trades.append(p["rec"])
            else:
                still.append(p)
        open_pos = still

        v = f["pre_vol"]
        take = len(seen) >= warmup and np.isfinite(v) and \
            v >= np.quantile(seen, pctile)
        if np.isfinite(v):
            seen.append(v)                      # append AFTER the decision
        if not take or len(open_pos) >= slots:
            continue

        b = pd.read_parquet(bd / f"{f['ticker']}.parquet")
        tv = b["t_utc"].to_numpy()
        tn = np.datetime64(t.tz_convert("UTC").tz_localize(None))
        i = int(np.searchsorted(tv, tn + np.timedelta64(1, "m"), "left"))
        if i >= len(b) or not (float(b["volume"].iloc[i]) > 0):
            continue
        e = float(b["high"].iloc[i])
        equity = cash + sum(p["cost"] for p in open_pos)
        size = equity / slots
        if size < 1.0:
            continue
        cash -= size

        px, why, j = walk(b, i, e, None, stop, trail, max_bars)
        open_pos.append({
            "exit_t": b["t"].iloc[j], "proceeds": (size / e) * px, "cost": size,
            "rec": {"ticker": f["ticker"], "band": f["band"],
                    "verdict": f["verdict"], "pre_vol": v, "entry": e,
                    "filed_et": f["filed_et"], "exit_t": b["t"].iloc[j],
                    "exit_px": px, "why": why, "ret": px / e - 1.0,
                    "size": size, "pnl": (size / e) * px - size}})

    for p in sorted(open_pos, key=lambda q: q["exit_t"]):
        cash += p["proceeds"]
        trades.append(p["rec"])
    tr = pd.DataFrame(trades)
    if not tr.empty:
        tr = tr.sort_values("exit_t").reset_index(drop=True)
        eq, bal = capital, []
        for pnl in tr["pnl"]:
            eq += pnl
            bal.append(eq)
        tr["balance"] = bal
    return tr
