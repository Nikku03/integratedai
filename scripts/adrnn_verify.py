"""Adversarial re-test of the two ADRNN results that need it.

The pre-registration made a prediction and got it wrong: the direction head
returned AUC 0.5677 with a week-clustered CI of [0.5462, 0.5901] excluding 0.50,
which is nominally a pass. It also said, in advance, that a direction pass would
be "treated as surprising and re-tested before being believed". This is that
re-test, and it is written to try to break the result rather than confirm it.

There are three ways an AUC of 0.57 on this label can be an artifact:

**It could be predicting the era, not the name.** ``P(up | big move)`` swings
from 47.7% in 2022 to 60.9% in 2017. A model that learned nothing but the drift
of that rate through time would score above 0.50 globally while being useless on
any given day, because on any given day the rate is a constant. Splitting the
AUC within month kills that: inside one month there is no era to predict.

**It could be predicting the sector or the name.** Same argument one level down.
If the model has memorised that biotech breaks up more often than mining, it
scores globally and adds nothing to a decision between two biotechs.

**It could be an artifact of the survivorship catastrophe.** Zero of 3,662
tickers delisted in eleven years. The deleted names are the ones that fell 90%
and never came back, so the training label is biased toward "up" in precisely
the way that would manufacture this result. That one cannot be tested away with
the data available; it can only be quantified and stated.

The magnitude head gets a smaller check: it passed its pre-registered criterion
but lost to gradient boosting on flat features, so the question worth asking is
whether the sequence adds anything at all once the flat model is in hand.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adrnn_train import auc, precision_at_k, weekly_boot_auc  # noqa: E402


def within_group_auc(y, s, g) -> tuple[float, int, int]:
    """Mean AUC computed inside each group, weighted by group size.

    A model that only knows the base rate of each group scores 0.50 here by
    construction, because inside a group the base rate is constant.
    """
    df = pd.DataFrame({"y": y, "s": s, "g": g})
    num = den = 0.0
    used = 0
    for _, sub in df.groupby("g"):
        if sub.y.nunique() < 2 or len(sub) < 30:
            continue
        a = auc(sub.y.to_numpy(), sub.s.to_numpy())
        if np.isfinite(a):
            num += a * len(sub)
            den += len(sub)
            used += 1
    return (num / den if den else float("nan")), used, int(den)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    args = ap.parse_args(argv)
    root = Path(args.root)

    z = np.load(root / "adrnn_test_scores.npz")
    idx = z["idx"]
    s_mag, s_dir, s_vol, s_gb = z["s_mag"], z["s_dir"], z["s_vol"], z["s_gb"]
    y_mag, y_dir = z["y_mag"], z["y_dir"]

    import pyarrow.parquet as pq
    meta = pq.read_table(root / "adrnn_panel.parquet",
                         columns=["ticker", "date"]).to_pandas()
    tick = meta["ticker"].to_numpy()[idx]
    date = pd.to_datetime(meta["date"].to_numpy()[idx])
    month = date.to_period("M").astype(str)
    week = date.to_period("W").astype(str)

    print(f"test set: {len(idx):,} samples, {pd.Series(tick).nunique()} tickers, "
          f"{date.min():%Y-%m-%d}..{date.max():%Y-%m-%d}")

    # ------------------------------------------------------------------
    print("\n" + "=" * 74)
    print("MAGNITUDE -- does the sequence add anything over flat features?")
    print("=" * 74)
    print(f"  vol baseline        AUC {auc(y_mag, s_vol):.4f}")
    print(f"  gradient boosting   AUC {auc(y_mag, s_gb):.4f}")
    print(f"  ADRNN               AUC {auc(y_mag, s_mag):.4f}")
    blend = 0.5 * pd.Series(s_gb).rank(pct=True) + 0.5 * pd.Series(s_mag).rank(pct=True)
    print(f"  rank-average of the two  AUC {auc(y_mag, blend.to_numpy()):.4f}")
    print("\n  precision at the top k names each day:")
    print(f"    {'k':>4s} {'base':>7s} {'vol':>7s} {'GB':>7s} {'ADRNN':>7s} {'blend':>7s}")
    for k in (5, 10, 20, 50):
        row = [precision_at_k(date, y_mag, s, k)[0] for s in
               (s_vol, s_gb, s_mag, blend.to_numpy())]
        print(f"    {k:>4d} {y_mag.mean() * 100:6.2f}% " +
              " ".join(f"{v * 100:6.2f}%" for v in row))

    # ------------------------------------------------------------------
    print("\n" + "=" * 74)
    print("DIRECTION -- the pre-registration predicted FAIL and got PASS")
    print("=" * 74)
    m = y_mag == 1
    yd, sd = y_dir[m], s_dir[m]
    print(f"  {int(m.sum()):,} real moves, {yd.mean() * 100:.2f}% of them up")
    a_all = auc(yd, sd)
    print(f"  pooled AUC {a_all:.4f}")

    a_m, n_m, cov_m = within_group_auc(yd, sd, month[m])
    print(f"\n  within MONTH   AUC {a_m:.4f}   ({n_m} months, {cov_m:,} samples)")
    a_w, n_w, cov_w = within_group_auc(yd, sd, week[m])
    print(f"  within WEEK    AUC {a_w:.4f}   ({n_w} weeks, {cov_w:,} samples)")
    a_t, n_t, cov_t = within_group_auc(yd, sd, tick[m])
    print(f"  within TICKER  AUC {a_t:.4f}   ({n_t} tickers, {cov_t:,} samples)")
    print("  A model that only learned the era or the name scores 0.50 here.")

    lo, hi, p = weekly_boot_auc(yd, sd, week[m].to_numpy(), null=0.5)
    print(f"\n  pooled week-clustered 95% CI [{lo:.4f}, {hi:.4f}]  P(<=0.5)={p:.4f}")

    print("\n  what the score is worth in practice -- decile of direction score:")
    q = pd.qcut(pd.Series(sd).rank(method="first"), 10, labels=False)
    t = pd.DataFrame({"q": q, "up": yd}).groupby("q").agg(
        n=("up", "size"), p_up=("up", "mean"))
    t["p_up"] = (t.p_up * 100).round(1)
    t["lift_vs_base"] = (t.p_up - yd.mean() * 100).round(1)
    print(t.to_string())
    top, bot = t.p_up.iloc[-1], t.p_up.iloc[0]
    print(f"  top decile {top:.1f}% up vs bottom decile {bot:.1f}% up "
          f"-> spread {top - bot:+.1f}pp")

    # ------------------------------------------------------------------
    print("\n" + "=" * 74)
    print("SURVIVORSHIP EXPOSURE -- cannot be tested away, only measured")
    print("=" * 74)
    base_up = yd.mean()
    print(f"  P(up | big move) in this panel      {base_up * 100:.2f}%")
    print("  A delisting-inclusive universe would move this down by roughly the")
    print("  delisted fraction times their (almost always downward) outcome.")
    for assume in (0.20, 0.35, 0.50):
        # If a fraction `assume` of names are missing and essentially all of
        # their big moves were downward, the true rate is the observed rate
        # diluted by that missing mass.
        adj = base_up * (1 - assume)
        print(f"    if {assume:.0%} of names are missing and broke down: "
              f"true P(up|big) ~ {adj * 100:.1f}%")
    print("  The direction head was trained to predict the biased label, so its")
    print("  calibration is wrong by the same amount even where its ranking is not.")

    print("\n" + "=" * 74)
    print("VERDICT")
    print("=" * 74)
    seq_beats_flat = auc(y_mag, s_mag) > auc(y_mag, s_gb)
    print(f"  magnitude: pre-registered criterion PASSED, but the sequence model "
          f"{'beats' if seq_beats_flat else 'LOSES to'} flat gradient boosting.")
    dir_survives = a_m > 0.52 and a_w > 0.52
    print(f"  direction: pooled {a_all:.4f}, within-month {a_m:.4f}, "
          f"within-week {a_w:.4f}")
    print(f"    -> {'survives' if dir_survives else 'DOES NOT SURVIVE'} "
          f"the within-period control")
    return 0


if __name__ == "__main__":
    sys.exit(main())
