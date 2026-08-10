"""A pre-trade checklist derived from the losers, not invented.

The model's picks split two ways: about a third touch +20% and pay, and
two-thirds touch under +20% and lose an average of 9.21% with 72.8% of them
closing red. A checklist is worth having only if it separates those two
populations using things knowable *before* the trade.

So the questions are not written from intuition. Each candidate is a binary
condition computed from the point-in-time panel, scored on how much it shifts
`P(touch >= 20%)` and mean return among the model's own picks. Then the ones
that survive are frozen and tested on years that had no part in choosing them.

**Derivation 2019-2022. Test 2023-2025.** That split is the entire discipline
here. Every dead rule in this project was born by finding a pattern and
reporting it on the same data, and the failure mode is so reliable that the
split is worth more than any individual question.

Two things this cannot do, stated plainly because the request was to eliminate
risk:

*It cannot remove the left tail.* Two-thirds of picks lose; a good checklist
moves that to something less bad, not to zero. A rule that appeared to eliminate
losses would be overfitting, and would be reported as a failure of the test.

*It cannot fix survivorship.* The panel contains no delisted companies, so the
losing population here is missing its worst members. Any checklist derived from
it is tuned against a gentler set of losers than reality provides.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adrnn_train import build_arrays  # noqa: E402

DERIVE_END = "2023-01-01"
COST = 20.0 / 1e4
MIN_SUPPORT = 0.10      # a question must apply to at least 10% of picks
MAX_SUPPORT = 0.90      # and must not be true of nearly all of them


def candidate_questions(f: pd.DataFrame) -> dict:
    """Binary conditions, each with a mechanism worth stating out loud.

    Thresholds are round numbers or in-sample medians rather than tuned values.
    A threshold chosen to maximise a statistic is a fitted parameter wearing a
    checklist's clothes.
    """
    q = {}
    med = f.median(numeric_only=True)

    # --- financing: can the company fund itself past the catalyst -------
    if "dilution_armed" in f:
        q["No registered stock ready to sell (no S-3/424B5 in 120d)"] = \
            f.dilution_armed <= 0
    if "runway_years" in f:
        q["More than one year of cash runway"] = f.runway_years > 1.0
    if "cash_per_cap" in f:
        q["Cash is over 15% of market cap"] = f.cash_per_cap > 0.15
    if "share_growth" in f:
        q["Share count grew less than 20% year on year"] = f.share_growth < 0.20
    if "liab_per_cash" in f:
        q["Liabilities under 3x cash"] = f.liab_per_cash < 3.0

    # --- the move has not already been paid ----------------------------
    if "ret_5d" in f:
        q["Has not already run more than 15% in five sessions"] = f.ret_5d < 0.15
    if "ret_20d" in f:
        q["Has not already run more than 30% in twenty sessions"] = f.ret_20d < 0.30
    if "dist_hi60" in f:
        q["Not pinned to its 60-day high"] = f.dist_hi60 < -0.02
    if "pos_in_range" in f:
        q["Not in the top quarter of its 60-day range"] = f.pos_in_range < 0.75

    # --- fillability ----------------------------------------------------
    if "log_dollar_vol" in f:
        q["Trades more than the median pick by dollar volume"] = \
            f.log_dollar_vol > med.get("log_dollar_vol", 0)
    if "log_price" in f:
        q["Share price above $3"] = f.log_price > np.log(3.0)
    if "rvol" in f:
        q["Volume is not already spiking (RVOL under 2x)"] = f.rvol < np.log(2.0)

    # --- size ------------------------------------------------------------
    if "log_cap" in f:
        q["Market cap above $100m"] = f.log_cap > 8.0
        q["Market cap below $5bn"] = f.log_cap < 9.7

    # --- volatility regime ----------------------------------------------
    if "vol_20d" in f:
        q["Not in a violent regime (20d daily vol under 6%)"] = f.vol_20d < 0.06
        q["Actually moving (20d daily vol above 2%)"] = f.vol_20d > 0.02

    # --- catalyst and insiders -------------------------------------------
    for col, label in (("i8.01_20d", "A material-event 8-K in the last month"),
                       ("i7.01_20d", "A Reg-FD 8-K in the last month"),
                       ("i1.01_20d", "A material-agreement 8-K in the last month")):
        if col in f:
            q[label] = f[col] > 0
    if "nbuy_60d" in f:
        q["An insider bought in the last quarter"] = f["nbuy_60d"] > 0
    if "nsell_60d" in f:
        q["No insider selling in the last quarter"] = f["nsell_60d"] <= 0
    if "i3.02_60d" in f:
        q["No unregistered share issuance in the last quarter"] = f["i3.02_60d"] <= 0
    return q


def score_question(d: pd.DataFrame, mask: pd.Series) -> dict:
    yes, no = d[mask], d[~mask]
    if len(yes) < 30 or len(no) < 30:
        return {}
    return {
        "support": float(mask.mean()),
        "p20_yes": float((yes.mup >= 0.20).mean()),
        "p20_no": float((no.mup >= 0.20).mean()),
        "lift_pp": float(((yes.mup >= 0.20).mean() - (no.mup >= 0.20).mean()) * 100),
        "ret_yes": float(yes.net.mean() * 100),
        "ret_no": float(no.net.mean() * 100),
        "ret_gain_pp": float((yes.net.mean() - no.net.mean()) * 100),
        "p50_yes": float((yes.mup >= 0.50).mean() * 100),
        "n_yes": int(len(yes)),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--top", type=int, default=8, help="questions to keep")
    args = ap.parse_args(argv)
    root = Path(args.root)

    p = pd.read_parquet(root / "tail_anatomy_picks.parquet")
    p["net"] = p.ret - COST
    d, X, feats, idx = build_arrays(root / "adrnn_panel.parquet", args.stride)
    pos = pd.Series(np.arange(len(d)), index=d.index)
    fr = pd.DataFrame(X[p.row.to_numpy()], columns=feats)
    for c in ("date", "mup", "net", "ret"):
        fr[c] = p[c].to_numpy()
    fr["date"] = pd.to_datetime(fr["date"])

    der = fr[fr.date < DERIVE_END].copy()
    tst = fr[fr.date >= DERIVE_END].copy()
    print(f"picks: {len(fr):,} total -> derive {len(der):,} "
          f"({der.date.min():%Y-%m}..{der.date.max():%Y-%m}), "
          f"test {len(tst):,} ({tst.date.min():%Y-%m}..{tst.date.max():%Y-%m})")
    print(f"derive baseline: P(+20%) {(der.mup >= .20).mean() * 100:.1f}%   "
          f"mean {der.net.mean() * 100:+.3f}%")
    print(f"test   baseline: P(+20%) {(tst.mup >= .20).mean() * 100:.1f}%   "
          f"mean {tst.net.mean() * 100:+.3f}%\n")

    qs = candidate_questions(der)
    rows = []
    for label, mask in qs.items():
        m = mask.fillna(False)
        if not (MIN_SUPPORT <= m.mean() <= MAX_SUPPORT):
            continue
        s = score_question(der, m)
        if s:
            rows.append({"question": label, **s})
    r = pd.DataFrame(rows).sort_values("ret_gain_pp", ascending=False)

    print("=" * 118)
    print("ALL CANDIDATE QUESTIONS, SCORED ON 2019-2022 ONLY")
    print("=" * 118)
    show = r.copy()
    show["support"] = (show.support * 100).round(0)
    for c in ("p20_yes", "p20_no"):
        show[c] = (show[c] * 100).round(1)
    print(show[["question", "support", "n_yes", "p20_yes", "p20_no", "lift_pp",
                "ret_yes", "ret_no", "ret_gain_pp", "p50_yes"]]
          .round(2).to_string(index=False))

    keep = r.head(args.top)["question"].tolist()
    print(f"\nFROZEN CHECKLIST -- top {args.top} by return gain, chosen on "
          f"2019-2022 and never re-touched:")
    for i, k in enumerate(keep, 1):
        print(f"  {i}. {k}")

    # ---------------- test ------------------------------------------
    def apply(df):
        qq = candidate_questions(df)
        sc = pd.Series(0, index=df.index)
        for k in keep:
            if k in qq:
                sc = sc + qq[k].fillna(False).astype(int)
        return sc

    print("\n" + "=" * 118)
    print("OUT OF SAMPLE 2023-2025: DOES ANSWERING MORE QUESTIONS 'YES' HELP?")
    print("=" * 118)
    for name, dd in (("DERIVE 2019-2022", der), ("TEST 2023-2025", tst)):
        dd = dd.copy()
        dd["score"] = apply(dd)
        g = dd.groupby("score").agg(
            n=("net", "size"), p20=("mup", lambda s: (s >= .20).mean() * 100),
            p50=("mup", lambda s: (s >= .50).mean() * 100),
            mean=("net", lambda s: s.mean() * 100),
            median=("net", lambda s: s.median() * 100),
            win=("net", lambda s: (s > 0).mean() * 100))
        print(f"\n{name}  (score = how many of the {len(keep)} answered yes)")
        print(g.round(2).to_string())
        hi = dd[dd.score >= dd.score.median() + 1]
        lo = dd[dd.score <= dd.score.median() - 1]
        if len(hi) > 30 and len(lo) > 30:
            rng = np.random.default_rng(83)
            a = np.array([rng.choice(hi.net.to_numpy(), len(hi), True).mean()
                          - rng.choice(lo.net.to_numpy(), len(lo), True).mean()
                          for _ in range(20000)])
            lo_ci, hi_ci = np.percentile(a, [2.5, 97.5])
            print(f"  high-score minus low-score: "
                  f"{(hi.net.mean() - lo.net.mean()) * 100:+.2f}pp   "
                  f"95% CI [{lo_ci * 100:+.2f}, {hi_ci * 100:+.2f}]   "
                  f"P(<=0) = {(a <= 0).mean():.4f}")
            if name.startswith("TEST"):
                print(f"  -> {'PASS' if lo_ci > 0 else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
