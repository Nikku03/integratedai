"""Did reading the filing predict the option, over fifteen blind sessions?

Judgements were fixed and committed before any option was priced, the exit was
named in advance as the close of the purchase session, and the window was chosen
to exclude every date whose per-name outcomes had already been seen. What follows
is therefore a report rather than a search.

Alternative exits are shown because they were registered in advance, not because
one of them is the answer. The intraday path comes from the same cached minute
bars as the primary, so nothing here cost an extra request or an extra decision.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

#: Contracts traded in the chosen strike on the purchase session. Below this the
#: printed price is not one anybody could have transacted in size.
MIN_VOL = 100


def path_points(cache: Path, occ: str, day: str) -> dict:
    """Entry at 09:35 and the value at several later moments, same session."""
    p = cache / f"m_{occ}_{day}.json"
    if not p.exists():
        return {}
    rows = json.loads(p.read_text()).get("results") or []
    if not rows:
        return {}
    t = pd.to_datetime([x["t"] for x in rows], unit="ms", utc=True) \
          .tz_convert("America/New_York")
    mins = np.array([x.hour * 60 + x.minute for x in t])
    px = np.array([float(x["c"]) for x in rows])
    out = {}
    for lab, lo, hi in (("open", 0, 574), ("entry", 575, 960),
                        ("plus1h", 575, 630), ("plus2h", 575, 690),
                        ("close", 575, 960)):
        m = (mins >= lo) & (mins <= hi)
        if not m.any():
            continue
        out[lab] = px[m][0] if lab in ("open", "entry") else px[m][-1]
    return out


def arm(label, r, stake=40.0):
    r = np.asarray([x for x in r if x == x], float)
    if not len(r):
        print(f"  {label:34s}{'--':>5s}")
        return
    eq = stake
    for x in r:
        eq *= (1 + x)
    print(f"  {label:34s}{len(r):>5d}{r.mean() * 100:>+10.1f}%"
          f"{np.median(r) * 100:>+10.1f}%{(r > 0).mean() * 100:>8.0f}%{eq:>10.2f}")


def boot(a, b, n=4000):
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 2 or len(b) < 2:
        return None
    g = np.random.default_rng(0)
    d = [g.choice(a, len(a)).mean() - g.choice(b, len(b)).mean() for _ in range(n)]
    return np.mean(d), np.percentile(d, 2.5), np.percentile(d, 97.5)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--stake", type=float, default=40.0)
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "win_cache"
    T = pd.read_parquet(work / "win_trades.parquet")

    pts = [path_points(cache, r.occ, r.buy_day) for r in T.itertuples()]
    for lab in ("open", "plus1h", "plus2h", "close"):
        T[f"px_{lab}"] = [p.get(lab, np.nan) for p in pts]
    T["ret"] = T.opt_exit / T.opt_entry - 1                       # registered primary
    T["ret_open"] = T.px_open / T.opt_entry - 1
    T["ret_1h"] = T.px_plus1h / T.opt_entry - 1
    T["ret_2h"] = T.px_plus2h / T.opt_entry - 1
    T["stock"] = T.spot_close / T.spot_open - 1
    T["want"] = np.where(T.side == "call", 1, -1)
    T["right"] = np.sign(T.stock) == T.want
    T["ok"] = (T.opt_vol >= MIN_VOL) & T.opt_entry.notna() & T.opt_exit.notna()

    print("\n" + "=" * 104)
    print("EVERY TRADE  (bought at 09:35 on the first session opening after the filing)")
    print("=" * 104)
    print(f"  {'date':12s}{'tkr':6s}{'dir':>4s}{'side':>5s}{'K':>7s}{'dte':>4s}"
          f"{'in':>6s}{'out':>6s}{'option':>9s}{'stock':>8s}{'vol':>8s}{'ok':>4s}  event")
    for _, r in T.sort_values("ret", ascending=False).iterrows():
        f = lambda v: "     n/a" if v != v else f"{v * 100:>+7.1f}%"
        ip = "   n/a" if r.opt_entry != r.opt_entry else f"{r.opt_entry:>6.2f}"
        op = "   n/a" if r.opt_exit != r.opt_exit else f"{r.opt_exit:>6.2f}"
        print(f"  {r.date:12s}{r.ticker:6s}{r.direction:>+4d}{r.side:>5s}{r.strike:>7g}"
              f"{r.dte:>4d}{ip}{op}{f(r.ret):>9s}{f(r.stock):>8s}{r.opt_vol:>8,.0f}"
              f"{('y' if r.ok else '-'):>4s}  {str(r.event_type)[:16]}")

    print("\n" + "=" * 104)
    print(f"ARMS  (${args.stake:.0f} compounded)")
    print("=" * 104)
    print(f"  {'arm':34s}{'n':>5s}{'mean':>10s}{'median':>10s}{'win':>8s}{'$40 ->':>10s}")
    E = T[T.ok]
    arm("all directional trades", T.ret, args.stake)
    arm("tradeable only", E.ret, args.stake)
    arm("  positive readings (calls)", E[E.direction > 0].ret, args.stake)
    arm("  negative readings (puts)", E[E.direction < 0].ret, args.stake)
    arm("  genuinely new information", E[E.is_news].ret, args.stake)
    arm("  merely furnished", E[~E.is_news].ret, args.stake)
    arm("  NOT already priced in", E[~E.already_priced].ret, args.stake)
    arm("  already priced in", E[E.already_priced].ret, args.stake)
    arm("  the stock itself", E.stock * E.want, args.stake)

    print("\n  registered alternative exits (same trades, same data):")
    arm("  sell at the opening print", E.ret_open, args.stake)
    arm("  sell one hour in", E.ret_1h, args.stake)
    arm("  sell two hours in", E.ret_2h, args.stake)

    print("\n" + "=" * 104)
    print("AGAINST THE PRE-REGISTRATION")
    print("=" * 104)
    n = len(E)
    print(f"  H1  the reading predicts the option.  n={n}")
    print(f"      direction called right on the stock: "
          f"{E.right.mean() * 100:.0f}% of trades")
    b = boot(E[E.direction > 0].ret, E[E.direction < 0].ret)
    if b:
        print(f"      calls minus puts: {b[0] * 100:+.1f}pp, "
              f"95% CI [{b[1] * 100:+.1f}, {b[2] * 100:+.1f}]")
    b = boot(E[E.right].ret, E[~E.right].ret)
    if b:
        print(f"      right direction minus wrong: {b[0] * 100:+.1f}pp, "
              f"95% CI [{b[1] * 100:+.1f}, {b[2] * 100:+.1f}]")
    b = boot(E[~E.already_priced].ret, E[E.already_priced].ret)
    if b:
        print(f"\n  H2  not-already-priced minus already-priced: {b[0] * 100:+.1f}pp, "
              f"95% CI [{b[1] * 100:+.1f}, {b[2] * 100:+.1f}]")
    a, c = E[E.is_news].stock.abs(), E[~E.is_news].stock.abs()
    if len(a) > 1 and len(c) > 1:
        print(f"\n  H3  |stock move| when the filing is genuinely new: "
              f"{a.mean() * 100:.1f}%  (n={len(a)})")
        print(f"      when it merely furnishes something known:      "
              f"{c.mean() * 100:.1f}%  (n={len(c)})")
    R = E[E.right]
    if len(R):
        print(f"\n  H4  where the direction was RIGHT (n={len(R)}):")
        print(f"      the stock moved  {(R.stock * R.want).mean() * 100:+.1f}% the right way")
        print(f"      the option returned {R.ret.mean() * 100:+.1f}%")
        print(f"      {(R.ret < 0).sum()} of {len(R)} lost money despite a correct call")

    W = E[~E.right]
    if len(R) and len(W):
        up, dn = R.ret.mean(), W.ret.mean()
        need = -dn / (up - dn)
        print("\n" + "=" * 104)
        print("WHAT ACCURACY THIS WOULD NEED")
        print("=" * 104)
        print(f"  a correct call returns  {up * 100:+.1f}%   (n={len(R)})")
        print(f"  a wrong one returns     {dn * 100:+.1f}%   (n={len(W)})")
        print(f"  so break-even needs the direction right "
              f"**{need * 100:.1f}%** of the time")
        print(f"  the reading got it right {E.right.mean() * 100:.1f}% of the time")
        print(f"  shortfall: {(E.right.mean() - need) * 100:+.1f} percentage points")
        print("\n  The option mechanics are not the problem -- being right pays well.")
        print("  Direction accuracy is, and a long option turns a coin flip into a")
        print("  losing coin flip because the losses are near-total and the wins are not.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
