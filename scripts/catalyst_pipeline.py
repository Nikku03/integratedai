"""Catalyst-gated pipeline: who the company is, what just happened, and who is buying.

The trade thesis, in order:

1. **Only trade a catalyst.** A hard gate, not a feature. No 8-K, no trade.
2. **The company's prior picture** — what it is worth, what its balance sheet
   looks like, how long its money lasts, and how visible it already is.
3. **The catalyst itself** — what kind, and crucially *how much it means to a
   company this size*. A $200m agreement is transformative for a $150m company
   and rounding error for a $15bn one, and the panel's raw dollar figure cannot
   tell those apart.
4. **The volume surge after the filing** — the timing trigger. If volume lifts
   on and after the disclosure while the price has barely moved, someone is
   accumulating before the story is priced. That is the moment to be early.
5. **A Markov chain over catalyst sequences** as the crowd-state detector, and
   the **REM diffusion** as the closed-form baseline the model corrects.

The one genuinely new block is the fourth
-----------------------------------------
Everything else in this repository has looked at the state of a name *before*
something happens. This looks at the market's *reaction* in the window between a
filing landing and the story reaching a wider audience — the interval the thesis
is actually about. Three quantities matter and they are computed from the
sessions before and after the filing rather than from a fixed window:

    surge      = average volume since the filing / average volume in the 20
                 sessions before it
    response   = price return since the filing
    quiet      = surge with the response still near zero

``quiet`` is the interesting one. High volume with a large price move is the
story already being priced; high volume with the price still flat is
accumulation. They are opposite trades and a plain volume feature conflates
them.

Ablation, because a five-block model that beats a one-block model proves nothing
about which block did the work: each block is added on its own and cumulatively,
all inside the same gate, walk-forward with a fourteen-day embargo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adrnn_train import auc, build_arrays  # noqa: E402
from agreed_strategy import daily_paths  # noqa: E402
from catalyst_markov import ALPHABET, chain, features as mk_features, states  # noqa: E402
from moonshot_tail import MAX_TRAIN, blocks, scale_fit  # noqa: E402
from rem_solver import _roll_count, _roll_sum, compile_shared, infer  # noqa: E402

HORIZON = 10
COST = 20.0 / 1e4
BIG = 0.20

#: Block 2 -- what the company is, before anything happened to it.
PRIOR_COLS = ["log_cap", "cash_per_cap", "runway_years", "liab_per_cash",
              "equity_per_cap", "is_profitable", "pre_revenue", "log_price",
              "ret_60d", "ret_20d", "vol_60d"]

#: Block 2b -- how visible it already is. Attention, not fundamentals.
EYES_COLS = ["log_dollar_vol", "rvol", "dist_hi60", "pos_in_range",
             "gov_n", "gov_60d", "nbuy_60d", "nsell_60d", "ncluster_buy_60d",
             "fSC 13D_since", "fSC 13G_since", "max_exc_20d", "mean_exc_20d"]


def surge_features(prices, since, base_win: int = 20):
    """Block 4: volume and price behaviour since the catalyst landed.

    ``since`` is sessions since the most recent catalyst, per row. The baseline
    is the twenty sessions *ending the day before the filing*, so a surge is
    measured against what the name did when nobody was looking, not against a
    window that already contains the reaction.
    """
    v = np.nan_to_num(prices["volume"].to_numpy(float), nan=0.0)
    c = prices["close"].to_numpy(float)
    tick = prices["ticker"].to_numpy()
    n = len(v)
    dv = v * c

    cv = np.concatenate([[0.0], np.cumsum(v)])
    cd = np.concatenate([[0.0], np.cumsum(dv)])
    idx = np.arange(n)
    start = np.zeros(n, dtype=np.int64)
    change = np.flatnonzero(np.r_[True, tick[1:] != tick[:-1]])
    start[change] = change
    start = np.maximum.accumulate(start)

    s = np.clip(np.nan_to_num(since, nan=999.0), 0, 60).astype(np.int64)
    fil = np.maximum(idx - s, start)                    # the filing bar
    b_hi = np.maximum(fil - 1, start)                   # last bar before it
    b_lo = np.maximum(b_hi - base_win + 1, start)

    post_n = np.maximum(idx - fil + 1, 1)
    base_n = np.maximum(b_hi - b_lo + 1, 1)
    post_v = (cv[idx + 1] - cv[fil]) / post_n
    base_v = (cv[b_hi + 1] - cv[b_lo]) / base_n
    post_d = (cd[idx + 1] - cd[fil]) / post_n
    base_d = (cd[b_hi + 1] - cd[b_lo]) / base_n

    with np.errstate(divide="ignore", invalid="ignore"):
        surge = np.where(base_v > 0, post_v / base_v, 1.0)
        dsurge = np.where(base_d > 0, post_d / base_d, 1.0)
        resp = np.where(c[fil] > 0, c / c[fil] - 1.0, 0.0)
    surge = np.clip(np.nan_to_num(surge, nan=1.0), 0, 50)
    dsurge = np.clip(np.nan_to_num(dsurge, nan=1.0), 0, 50)
    resp = np.clip(np.nan_to_num(resp, nan=0.0), -1, 3)

    # the trigger: money arriving while the price has not yet moved
    quiet = np.log1p(np.maximum(surge - 1.0, 0.0)) / (1.0 + 20.0 * np.abs(resp))
    # is the surge still building, or already fading
    lastv = np.where(base_v > 0, v / base_v, 1.0)
    build = np.clip(np.nan_to_num(lastv, nan=1.0), 0, 50) - surge

    cols = {"sg_surge": surge, "sg_dollar_surge": dsurge, "sg_response": resp,
            "sg_quiet": quiet, "sg_build": build,
            "sg_days_since": s.astype(float),
            "sg_abs_response": np.abs(resp)}
    return np.column_stack(list(cols.values())).astype(np.float32), list(cols)


def materiality(F: dict, feats: list, n: int):
    """Block 3b: the size of the event relative to the size of the company.

    ``log_deal_value`` exists only on the biotech subset the text pass covered,
    so this is mostly zero and carries an explicit presence flag rather than
    pretending absence is a small deal.
    """
    cap = F.get("log_cap", np.zeros(n))
    dv = F.get("log_deal_value", np.zeros(n))
    has = F.get("has_deal_value", np.zeros(n))
    ratio = np.where(has > 0, dv - cap, 0.0)
    cols = {"mt_ratio": ratio, "mt_has_value": has, "mt_log_value": dv}
    return np.column_stack(list(cols.values())).astype(np.float32), list(cols)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--quantile", type=float, default=0.75)
    ap.add_argument("--gate-days", type=int, default=3)
    ap.add_argument("--k", type=int, default=1)
    args = ap.parse_args(argv)
    root = Path(args.root)

    from sklearn.ensemble import HistGradientBoostingRegressor

    d, X, feats, idx = build_arrays(root / "adrnn_panel.parquet", args.stride)
    prices = pd.read_parquet(root / "w2015_prices.parquet",
                             columns=["date", "ticker", "open", "high", "low",
                                      "close", "volume"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)

    paths = daily_paths(prices, idx, HORIZON)
    ret = np.nanprod(1.0 + np.nan_to_num(paths, nan=0.0), axis=1) - 1.0
    ret = np.where(np.isfinite(paths[:, 0]) & (np.abs(ret) <= 3.0), ret, np.nan)
    ok = np.isfinite(ret)
    rows, ret = idx[ok], ret[ok]
    Xp = X[rows]
    dates = pd.Series(pd.to_datetime(d["date"].to_numpy()[rows]))
    F = {c: Xp[:, i] for i, c in enumerate(feats)}
    n = len(rows)

    # ---- block 4 needs the full price series, then index down -----------
    item_cols = [c for c in ALPHABET if c.startswith("i") and c in feats]
    any8k_all = np.min(np.column_stack([X[:, feats.index(c)] for c in item_cols]),
                       axis=1)
    SG_all, sgn = surge_features(prices, any8k_all)
    SG = SG_all[rows]

    mu, sig = compile_shared(prices)
    yrem_all, Frem_all, qn = infer(mu, sig, HORIZON)
    REM = np.column_stack([Frem_all[rows], yrem_all[rows].reshape(-1, 1)]).astype(np.float32)

    cur, prv, sinces, snames = states(F, feats)
    MT, mtn = materiality(F, feats, n)

    # ---- the hard gate --------------------------------------------------
    any8k = any8k_all[rows]
    gate = any8k <= args.gate_days
    print(f"{n:,} eligible candidates; catalyst gate (8-K within "
          f"{args.gate_days} sessions) keeps {int(gate.sum()):,} "
          f"({gate.mean() * 100:.1f}%)", flush=True)

    Xg, retg = Xp[gate], ret[gate]
    dg = dates[gate].reset_index(drop=True)
    SGg, REMg, MTg = SG[gate], REM[gate], MT[gate]
    curg, prvg, sincesg = cur[gate], prv[gate], sinces[gate]
    Fg = {c: Xg[:, i] for i, c in enumerate(feats)}
    PRIOR = np.column_stack([Fg[c] for c in PRIOR_COLS if c in Fg]).astype(np.float32)
    EYES = np.column_stack([Fg[c] for c in EYES_COLS if c in Fg]).astype(np.float32)
    print(f"  blocks: prior {PRIOR.shape[1]}, public-eye {EYES.shape[1]}, "
          f"materiality {MT.shape[1]}, surge {SG.shape[1]}, REM {REM.shape[1]}, "
          f"markov 8", flush=True)
    print(f"  median trades/session in the gate: "
          f"{pd.Series(dg).value_counts().median():.0f}\n", flush=True)

    # ---- what the surge block looks like on its own ---------------------
    print("=" * 104)
    print("THE TIMING TRIGGER -- volume surge after the filing, price not yet moved")
    print("=" * 104)
    q = SGg[:, sgn.index("sg_quiet")]
    sv = SGg[:, sgn.index("sg_surge")]
    fin = np.isfinite(q) & np.isfinite(retg)
    dec = pd.qcut(pd.Series(q[fin]).rank(method="first"), 10, labels=False)
    t = pd.DataFrame({"q": dec, "r": retg[fin], "s": sv[fin]})
    g = t.groupby("q").agg(n=("r", "size"), surge=("s", "median"),
                           mean=("r", lambda x: x.mean() * 100),
                           p_up20=("r", lambda x: (x >= BIG).mean() * 100),
                           p_dn20=("r", lambda x: (x <= -BIG).mean() * 100),
                           p_up=("r", lambda x: (x > 0).mean() * 100))
    print(g.round(2).to_string())
    print(f"\n  decile 9 is the strongest quiet accumulation, decile 0 the weakest")
    print(f"  spread in mean return: "
          f"{(t[t.q == 9].r.mean() - t[t.q == 0].r.mean()) * 100:+.2f}pp")

    # ---- walk-forward, block by block -----------------------------------
    print("\n" + "=" * 104)
    print("WALK-FORWARD INSIDE THE GATE -- each block added on its own, then all")
    print("=" * 104)
    K = len(snames)
    arms = {}

    def add(name, blocks_list):
        arms[name] = blocks_list

    # The first version of this ablation was vacuous for three arms and the
    # output said so: "+ prior", "+ public eye" and "+ materiality" all returned
    # EXACTLY the control's +2.197% and 0.5062 AUC. PRIOR_COLS and EYES_COLS are
    # drawn from `feats`, so those arms were handing the booster duplicate
    # columns, and a tree is invariant to that; materiality is all zeros because
    # log_deal_value lives in adrnn_panel_text.parquet, not this panel. Testing
    # them standalone is the only way to learn anything about them.
    add("panel only (control)", ["panel"])
    add("prior alone", ["prior"])
    add("public eye alone", ["eyes"])
    add("prior + eyes alone", ["prior", "eyes"])
    add("surge alone", ["surge"])
    add("markov alone", ["markov"])
    add("rem alone", ["rem"])
    add("surge+markov+rem alone", ["surge", "markov", "rem"])
    add("+ surge", ["panel", "surge"])
    add("+ REM", ["panel", "rem"])
    add("+ markov", ["panel", "markov"])
    add("full pipeline", ["panel", "prior", "eyes", "mt", "surge", "rem", "markov"])
    add("surge + markov + REM", ["panel", "surge", "markov", "rem"])

    res = {k: [] for k in arms}
    aucs = {k: [] for k in arms}
    for b0, b1 in blocks(dg.max()):
        tr = np.flatnonzero(dg < b0 - pd.Timedelta(days=14))
        te = np.flatnonzero((dg >= b0) & (dg < b1))
        if len(tr) < 5_000 or len(te) < 200:
            continue
        if len(tr) > MAX_TRAIN:
            tr = tr[np.linspace(0, len(tr) - 1, MAX_TRAIN).astype(int)]
        P, B, R, U, cnt, ent = chain(curg, prvg, retg, tr, K)
        MK = mk_features(curg, prvg, sincesg, P, B, R, U, cnt, ent)
        pool = {"panel": Xg, "prior": PRIOR, "eyes": EYES, "mt": MTg,
                "surge": SGg, "rem": REMg, "markov": MK}
        for name, want in arms.items():
            A = np.column_stack([pool[w] for w in want])
            A = np.nan_to_num(A, nan=0.0, posinf=0.0, neginf=0.0)
            med, sc = scale_fit(A[tr])
            mo = HistGradientBoostingRegressor(loss="quantile",
                                               quantile=args.quantile,
                                               max_iter=250, learning_rate=0.05,
                                               max_depth=6, random_state=0)
            mo.fit(np.clip((A[tr] - med) / sc, -5, 5), retg[tr])
            p = mo.predict(np.clip((A[te] - med) / sc, -5, 5))
            s = pd.DataFrame({"d": dg.to_numpy()[te], "p": p, "r": retg[te]})
            pick = s.sort_values("p", ascending=False).groupby("d").head(args.k)
            res[name].append(float(pick.r.mean()) - COST)
            aucs[name].append(auc((retg[te] > 0).astype(int), p))
        print(f"  block {b0:%Y-%m} done", flush=True)

    print(f"\n  {'arm':24s} {'blocks':>7s} {'per trade':>11s} {'vs control':>11s} "
          f"{'dir AUC':>9s}")
    ctrl = np.array(res["panel only (control)"])
    rng = np.random.default_rng(51)
    for name in arms:
        a = np.array(res[name])
        if not len(a):
            continue
        dl = a - ctrl
        extra = ""
        if name != "panel only (control)":
            bs = np.array([rng.choice(dl, len(dl), True).mean() for _ in range(10000)])
            lo, hi = np.percentile(bs, [2.5, 97.5])
            extra = f"  [{lo * 100:+.2f},{hi * 100:+.2f}]"
            if lo > 0:
                extra += " PASS"
        print(f"  {name:24s} {len(a):>7d} {a.mean() * 100:>+10.3f}% "
              f"{dl.mean() * 100:>+10.3f}pp {np.mean(aucs[name]):>9.4f}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
