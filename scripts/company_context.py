"""Point-in-time company context for a filing being read, and for the ranker.

`llm_gate_pick.py` originally gave the reader the 8-K and nothing else, which
makes one of the two questions worth asking unanswerable. "Is this good news?"
can be judged from the document. "How much does this matter?" cannot — a $25M
convertible is survival financing for a $60M company and a rounding error for a
$6B one, and the filing does not say which it is.

Two sources: **SEC XBRL company facts** for revenue, net income, cash, assets
and shares outstanding, and **the price panel** for size, liquidity, turnover,
momentum, drawdown, realised volatility and the volume reaction to the filing.

Point-in-time discipline
------------------------
Every XBRL fact carries the date it was **filed**, distinct from the period it
covers. A 10-K for FY2025 filed 2026-03-02 did not exist on 2026-02-15, and
using it there is lookahead of exactly the kind that makes fundamentals look
predictive. `as_of` filters on ``filed < date``, never on the period end.

Four things the first version of this file got wrong
----------------------------------------------------
**Proxy statements lie about scale.** DEF 14A pay-versus-performance tables tag
``NetIncomeLoss`` for the same fiscal year as the 10-K, but a thousand times
larger — BDTX's FY2025 net income is $22,367,000 in the 10-K and
$22,367,000,000 in the DEF 14A filed six weeks later. Preferring the
latest-filed fact therefore reported a $106M biotech earning $22 billion.
`PERIODIC` now restricts every us-gaap fact to periodic reports.

**There is no fourth quarter.** Issuers never file a standalone Q4; it is
implied by the 10-K less the nine-month year-to-date figure. Taking "the four
most recent quarterly facts" therefore spans 454 days, fails a naive
twelve-month span check, and silently falls through to the annual path — which
is how the proxy bug above got reached. `flow` now checks that the quarters are
*contiguous*, and otherwise rolls the last full year forward.

**Share counts and prices can be on different split bases.** KUST reports
626,860 shares outstanding while the panel still carries pre-reverse-split
volume, giving a $0.8M market cap on $9.2M of daily turnover — 1,161% of the
company changing hands per day. Nothing checked. `_plausible` now suppresses a
market cap that implies impossible turnover rather than printing it.

**Public float is up to eighteen months stale.** ``EntityPublicFloat`` is
measured on the last business day of the most recently completed second fiscal
quarter, at that day's price. Printing it beside a current market cap produced
eight rows where the float exceeded the whole company. It is gone.

There is no news or social feed available here, so "how the company is seen" is
proxied by what the tape shows: turnover, momentum, distance from the 52-week
high, realised volatility and how often the company has been filing. Those are
attention measures, not sentiment measures.
"""

from __future__ import annotations

import json
from datetime import date as _date, timedelta

import numpy as np
import pandas as pd

FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{:010d}.json"

#: Issuers tag revenue half a dozen different ways; these are tried in order.
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
)
#: Only periodic reports. Proxies restate the same figures at the wrong scale.
#: 8-K exhibits carry pro-forma and carve-out statements -- VISN's post-RUCKUS
#: pro-formas report $87.8M of revenue against $1.93B actually reported -- so
#: they are excluded too. Only the issuer's own periodic results count.
PERIODIC = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"}
QUARTER = (75, 105)
ANNUAL = (340, 400)
#: A US common stock turning over more than this fraction of itself per day for
#: twenty straight sessions is not a real measurement, it is a split mismatch.
MAX_TURNOVER = 1.00


def fetch(client, cik: int) -> dict | None:
    """Company facts for one CIK, or None if the issuer has never filed XBRL."""
    b = client.get_bytes(FACTS_URL.format(int(cik)))
    if not b:
        return None
    try:
        return json.loads(b)
    except json.JSONDecodeError:
        return None


def _units(facts: dict, tax: str, tag: str, periodic_only: bool = True) -> list[dict]:
    node = facts.get("facts", {}).get(tax, {}).get(tag)
    if not node:
        return []
    out = []
    for rows in node.get("units", {}).values():
        for r in rows:
            if periodic_only and r.get("form") not in PERIODIC:
                continue
            out.append(r)
    return out


def as_of(rows: list[dict], when: pd.Timestamp) -> list[dict]:
    """Only the facts that had actually been filed by ``when``."""
    cut = when.date() if isinstance(when, pd.Timestamp) else when
    keep = []
    for r in rows:
        f = r.get("filed")
        if not f:
            continue
        try:
            if _date.fromisoformat(f) < cut:
                keep.append(r)
        except ValueError:
            continue
    return keep


def _span(r: dict) -> int | None:
    if not r.get("start") or not r.get("end"):
        return None
    try:
        return (_date.fromisoformat(r["end"]) - _date.fromisoformat(r["start"])).days
    except ValueError:
        return None


def _latest_per_period(rows, lo, hi) -> dict[str, dict]:
    """Facts of a given period length, keyed by end date, latest filing wins."""
    out: dict[str, dict] = {}
    for r in rows:
        s = _span(r)
        if s is None or not (lo <= s <= hi):
            continue
        prev = out.get(r["end"])
        if prev is None or r["filed"] > prev["filed"]:
            out[r["end"]] = r
    return out


def _contiguous(picked: list[dict]) -> bool:
    """True when the quarters abut, so their sum is a real twelve months."""
    for a, b in zip(picked, picked[1:]):          # a is later than b
        try:
            gap = (_date.fromisoformat(a["start"]) - _date.fromisoformat(b["end"])).days
        except ValueError:
            return False
        if not (0 <= gap <= 4):
            return False
    return True


def flow(facts: dict, tags, when: pd.Timestamp) -> float:
    """Trailing-twelve-month value of a flow item, as known at ``when``.

    Three routes, in order of preference:

    1. Four contiguous quarters. Exact, and the usual case mid-year.
    2. The last full year, rolled forward: **FY + quarters since year end −
       the same quarters a year earlier**. Both legs are required. Adding the
       new quarters *without* subtracting the year-ago ones counts them twice
       and is how this function first reported $7.0B of net income for a
       company with $5.4B of assets.
    3. The last full year on its own.

    NaN if none apply.
    """
    if isinstance(tags, str):
        tags = (tags,)
    for tag in tags:
        rows = as_of(_units(facts, "us-gaap", tag), when)
        if not rows:
            continue
        qs = _latest_per_period(rows, *QUARTER)
        anns = _latest_per_period(rows, *ANNUAL)

        picked = sorted(qs.values(), key=lambda r: r["end"], reverse=True)[:4]
        if len(picked) == 4 and _contiguous(picked):
            return float(sum(r["val"] for r in picked))
        if not anns:
            continue

        fy = max(anns.values(), key=lambda r: r["end"])
        after = [r for r in sorted(qs.values(), key=lambda r: r["end"])
                 if r["end"] > fy["end"]]
        if not after:
            return float(fy["val"])
        prior = [_nearest(qs, _shift_end(r["end"], -365)) for r in after]
        if all(p is not None for p in prior):
            # guard against a "year-ago" match that is really one of the new
            # quarters, which would subtract a figure from the wrong period
            if all(p["end"] <= fy["end"] for p in prior):
                return float(fy["val"] + sum(r["val"] for r in after)
                             - sum(p["val"] for p in prior))
        return float(fy["val"])
    return float("nan")


def _shift_end(iso: str, days: int) -> str:
    try:
        return (_date.fromisoformat(iso) + timedelta(days=days)).isoformat()
    except ValueError:
        return ""


def _nearest(pool: dict[str, dict], target: str, tol: int = 20) -> dict | None:
    if not target:
        return None
    t = _date.fromisoformat(target)
    best, bd = None, tol + 1
    for k, v in pool.items():
        d = abs((_date.fromisoformat(k) - t).days)
        if d < bd:
            best, bd = v, d
    return best


def stock(facts: dict, tax: str, tag: str, when: pd.Timestamp) -> float:
    """Latest point-in-time value of a balance-sheet or cover-page item."""
    periodic = tax != "dei"
    rows = as_of(_units(facts, tax, tag, periodic_only=periodic), when)
    inst = [r for r in rows if not r.get("start")]
    rows = inst or rows
    if not rows:
        return float("nan")
    return float(max(rows, key=lambda r: (r.get("end", ""), r["filed"]))["val"])


def price_context(c: np.ndarray, v: np.ndarray, j: int, j0: int | None,
                  lo: int) -> dict:
    """Tape context at row ``j``, with the filing session at ``j0``.

    ``lo`` is the first row belonging to this ticker; every window is clamped to
    it so a lookback can never reach into the previous issuer's bars. On this
    shortlist no window was long enough to cross — the shortest history was 343
    sessions against a 252-session high — but nothing was stopping it.
    """
    def win(a, n):
        return a[max(lo, j - n + 1):j + 1]

    px = c[j]
    d20, d60, d252 = win(c, 20), win(c, 60), win(c, 252)
    v20 = win(v, 20)
    r = np.diff(np.log(np.maximum(d20, 1e-9))) if len(d20) > 2 else np.array([0.0])
    out = {
        "price": px,
        "adv20": float(np.nanmean(d20 * v20)) if len(v20) else float("nan"),
        "mom20": px / d20[0] - 1.0 if len(d20) > 1 and d20[0] > 0 else float("nan"),
        "mom60": px / d60[0] - 1.0 if len(d60) > 1 and d60[0] > 0 else float("nan"),
        "from_high": px / np.nanmax(d252) - 1.0 if len(d252) else float("nan"),
        "vol20": float(np.nanstd(r) * np.sqrt(252)) if len(r) > 2 else float("nan"),
        "hist": j - lo,
    }
    # The volume reaction on the filing session itself. If the filing date was
    # not a trading day there is no such session, and reporting the day before
    # entry under that label would be a lie -- so it is left out.
    if j0 is not None and j0 >= lo:
        base = v[max(lo, j0 - 21):max(lo + 1, j0)]
        med = float(np.nanmedian(base)) if len(base) else np.nan
        out["surge"] = (float(v[j0] / med)
                        if med and np.isfinite(med) and med > 0 else float("nan"))
    else:
        out["surge"] = float("nan")
    return out


def _plausible(ctx: dict) -> dict:
    """Drop figures the data cannot actually support.

    Split-basis mismatches between the panel and the XBRL cover page produce
    market caps an order of magnitude wrong, and the tell is always the implied
    turnover. Unit errors in tagged fundamentals show up as values absurd
    against the balance sheet. Both are suppressed rather than displayed.
    """
    mc, adv, price = ctx.get("mktcap"), ctx.get("adv20"), ctx.get("price")
    if all(np.isfinite(x or np.nan) for x in (mc, adv)) and mc > 0:
        if adv / mc > MAX_TURNOVER:
            ctx["mktcap"] = float("nan")
            ctx["turnover"] = float("nan")
            ctx["cap_note"] = "suppressed: share count and panel volume disagree"
    assets, rev, ni = (ctx.get("assets"), ctx.get("revenue"), ctx.get("net_income"))
    scale = max([abs(x) for x in (assets, rev) if np.isfinite(x or np.nan)] or [0.0])
    if scale > 0 and np.isfinite(ni or np.nan):
        if abs(ni) > 100 * scale:
            # only a tagging error reaches this ratio
            ctx["net_income"] = float("nan")
        elif abs(ni) > scale:
            # VISN's own 10-K reports $5.5B of quarterly net income against
            # $5.4B of assets, on disposal gains. The figure is what the issuer
            # filed; it is simply not earnings power, and saying so beats both
            # printing it bare and hiding it.
            ctx["ni_note"] = "one-time items dominate"
    if (np.isfinite(rev or np.nan) and np.isfinite(assets or np.nan)
            and assets > 0 and rev > 100 * assets):
        ctx["revenue"] = float("nan")
    return ctx


def describe(ctx: dict) -> str:
    """The context block as the reader sees it. Units chosen to be scannable."""
    ctx = _plausible(dict(ctx))

    def m(x, unit="$", scale=1e6, suffix="M"):
        if x is None or not np.isfinite(x):
            return "n/a"
        if abs(x) >= 1e9 and scale == 1e6:
            return f"{unit}{x / 1e9:,.2f}B"
        return f"{unit}{x / scale:,.1f}{suffix}"

    def pc(x, dp=0):
        return "n/a" if x is None or not np.isfinite(x) else f"{x * 100:+.{dp}f}%"

    rev, ni, mc = ctx.get("revenue"), ctx.get("net_income"), ctx.get("mktcap")
    size = f"  size        market cap {m(mc)} | price ${ctx.get('price', float('nan')):,.2f}"
    if ctx.get("cap_note"):
        size += f"  [{ctx['cap_note']}]"
    lines = [size,
             f"  business    revenue (TTM) {m(rev)} | net income (TTM) {m(ni)}"
             + (f" [{ctx['ni_note']}]" if ctx.get("ni_note") else "")
             + f" | cash {m(ctx.get('cash'))} | assets {m(ctx.get('assets'))}"]
    if np.isfinite(rev or np.nan) and np.isfinite(mc or np.nan) and rev > 0:
        lines.append(f"  valuation   {mc / rev:,.1f}x revenue"
                     + (f" | net margin {ni / rev * 100:+.0f}%"
                        if np.isfinite(ni or np.nan) else ""))
    lines += [
        f"  liquidity   ADV {m(ctx.get('adv20'))}/day | turnover "
        f"{pc(ctx.get('turnover'), 2)}/day of shares out",
        f"  the tape    20d {pc(ctx.get('mom20'))} | 60d {pc(ctx.get('mom60'))} "
        f"| {pc(ctx.get('from_high'))} vs 52-week high | realised vol "
        f"{pc(ctx.get('vol20'))}",
        f"  reaction    filing-day volume "
        + (f"{ctx['surge']:.1f}x its 20-day median"
           if np.isfinite(ctx.get("surge", np.nan)) else "n/a")
        + f" | {ctx.get('n8k', 0)} 8-Ks filed in the prior 90 days",
    ]
    return "\n".join(lines)


#: Column order for :func:`panel_features`.
PANEL_COLS = ("ctx_logprice", "ctx_logadv", "ctx_turn", "ctx_mom20", "ctx_mom60",
              "ctx_from_high", "ctx_vol20", "ctx_volratio", "ctx_since8k")


def panel_features(px: pd.DataFrame, since: np.ndarray) -> np.ndarray:
    """The tape half of the context, for every row of the panel.

    The fundamental half cannot go here: it would mean a 2MB company-facts
    download for each of several thousand training issuers. These nine are
    derived from OHLCV and the filing index, so they exist identically in the
    training period and the test window — which is the condition
    `RESULT_CATALYST_GATE.md` says a live comparison has to meet.

    Every column is shifted one session within ticker, so a row's features are
    strictly what was knowable before that session opened.
    """
    g = px.groupby("ticker", sort=False)
    c, v = px["close"], px["volume"].fillna(0.0)
    dollar = c * v
    adv = g.apply(lambda d: (d["close"] * d["volume"].fillna(0.0))
                  .rolling(20, min_periods=5).mean(), include_groups=False)
    adv = adv.reset_index(level=0, drop=True).sort_index()
    hi252 = g["close"].transform(lambda s: s.rolling(252, min_periods=20).max())
    ret = g["close"].transform(lambda s: np.log(s.clip(lower=1e-9)).diff())
    out = pd.DataFrame({
        "ctx_logprice": np.log(c.clip(lower=1e-6)),
        "ctx_logadv": np.log1p(adv),
        "ctx_turn": dollar / adv.replace(0, np.nan),
        "ctx_mom20": c / g["close"].shift(20) - 1.0,
        "ctx_mom60": c / g["close"].shift(60) - 1.0,
        "ctx_from_high": c / hi252 - 1.0,
        "ctx_vol20": g.apply(lambda d: np.log(d["close"].clip(lower=1e-9)).diff()
                             .rolling(20, min_periods=5).std(),
                             include_groups=False)
                      .reset_index(level=0, drop=True).sort_index() * np.sqrt(252),
        "ctx_volratio": v / g["volume"].transform(
            lambda s: s.rolling(20, min_periods=5).median()).replace(0, np.nan),
        # sessions since the most recent 8-K, not a count: the gate already
        # bounds this to 1..gate_days, so inside the gate it carries staleness
        "ctx_since8k": pd.Series(np.where(np.isfinite(since), since, 999.0),
                                 index=px.index),
    })
    out = out.groupby(px["ticker"], sort=False).shift(1)
    A = out[list(PANEL_COLS)].to_numpy(np.float32)
    # A zero prior close or a zero 20-day median volume turns a ratio into an
    # infinity, which survives clipping only if the column's own median is
    # finite -- and when it is not, the whole column arrives at the histogram
    # binner as NaN and sklearn fails with "window shape cannot be larger than
    # input array shape". Infinities are missing data here, so say so.
    return np.where(np.isfinite(A), A, np.nan).astype(np.float32)
