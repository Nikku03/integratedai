"""Point-in-time company context for a filing being read.

`llm_gate_pick.py` gave the reader the 8-K and nothing else, which makes one of
the two questions worth asking unanswerable. "Is this good news?" can be judged
from the document. "How much does this matter to the company?" cannot — a $25M
convertible is survival financing for a $60M company and a rounding error for a
$6B one, and the filing does not say which it is.

This assembles that missing half from two sources:

* **SEC XBRL company facts** (`data.sec.gov/api/xbrl/companyfacts`) for revenue,
  net income, cash, assets, equity, shares outstanding and public float.
* **The price panel** for size, liquidity, turnover, momentum, drawdown,
  realised volatility and the volume reaction to the filing itself.

Point-in-time discipline
------------------------
Every XBRL fact carries the date it was **filed**, distinct from the period it
covers. A 10-K for FY2025 filed 2026-03-02 did not exist on 2026-02-15, and
using it there would be lookahead of exactly the kind that makes fundamentals
look predictive. `as_of` therefore filters on ``filed < date``, never on the
period end. Everything derived from the price panel is likewise computed from
bars strictly before the entry session.

There is no news or social sentiment feed available here, so "how the company is
seen" is proxied by what the tape shows: turnover, momentum, distance from the
52-week high, realised volatility, and how often the company has been filing.
Those are attention measures, not sentiment measures, and the writeup says so
rather than dressing them up.
"""

from __future__ import annotations

import json
from datetime import date as _date

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
QUARTER = (75, 105)
ANNUAL = (340, 400)


def fetch(client, cik: int) -> dict | None:
    """Company facts for one CIK, or None if the issuer has never filed XBRL."""
    b = client.get_bytes(FACTS_URL.format(int(cik)))
    if not b:
        return None
    try:
        return json.loads(b)
    except json.JSONDecodeError:
        return None


def _units(facts: dict, tax: str, tag: str) -> list[dict]:
    node = facts.get("facts", {}).get(tax, {}).get(tag)
    if not node:
        return []
    out = []
    for rows in node.get("units", {}).values():
        out.extend(rows)
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


def flow(facts: dict, tags, when: pd.Timestamp) -> float:
    """Trailing-twelve-month value of a flow item, as known at ``when``.

    Four consecutive quarters where they exist, because a company that has
    reported three quarters since its last 10-K should be measured on those
    rather than on a year-old annual figure. Falls back to the latest annual
    period, then to NaN.
    """
    if isinstance(tags, str):
        tags = (tags,)
    for tag in tags:
        rows = as_of(_units(facts, "us-gaap", tag), when)
        if not rows:
            continue
        qs = {}
        for r in rows:
            s = _span(r)
            if s is None or not (QUARTER[0] <= s <= QUARTER[1]):
                continue
            # a later filing restates an earlier one for the same period
            prev = qs.get(r["end"])
            if prev is None or r["filed"] > prev["filed"]:
                qs[r["end"]] = r
        picked = sorted(qs.values(), key=lambda r: r["end"], reverse=True)[:4]
        if len(picked) == 4:
            cover = (_date.fromisoformat(picked[0]["end"])
                     - _date.fromisoformat(picked[-1]["start"])).days
            if ANNUAL[0] <= cover <= ANNUAL[1]:
                return float(sum(r["val"] for r in picked))
        ann = [r for r in rows if (_span(r) or 0) >= ANNUAL[0]
               and (_span(r) or 0) <= ANNUAL[1]]
        if ann:
            return float(max(ann, key=lambda r: (r["end"], r["filed"]))["val"])
    return float("nan")


def stock(facts: dict, tax: str, tag: str, when: pd.Timestamp) -> float:
    """Latest point-in-time value of a balance-sheet or cover-page item."""
    rows = [r for r in as_of(_units(facts, tax, tag), when) if not r.get("start")]
    if not rows:
        rows = as_of(_units(facts, tax, tag), when)
    if not rows:
        return float("nan")
    return float(max(rows, key=lambda r: (r.get("end", ""), r["filed"]))["val"])


def price_context(c: np.ndarray, v: np.ndarray, j: int, j0: int) -> dict:
    """Tape context at row ``j``, with the filing session at ``j0``.

    ``j`` is the last bar before the entry, so every window ends there and
    nothing after the entry session is touched.
    """
    def win(a, n):
        lo = max(j0 - n + 1, j - n + 1)
        return a[max(0, j - n + 1):j + 1]

    px = c[j]
    d20, d60, d252 = win(c, 20), win(c, 60), win(c, 252)
    v20 = win(v, 20)
    r = np.diff(np.log(np.maximum(d20, 1e-9))) if len(d20) > 2 else np.array([0.0])
    out = {
        "price": px,
        "adv20": float(np.nanmean(win(c, 20) * v20)) if len(v20) else float("nan"),
        "mom20": px / d20[0] - 1.0 if len(d20) > 1 and d20[0] > 0 else float("nan"),
        "mom60": px / d60[0] - 1.0 if len(d60) > 1 and d60[0] > 0 else float("nan"),
        "from_high": px / np.nanmax(d252) - 1.0 if len(d252) else float("nan"),
        "vol20": float(np.nanstd(r) * np.sqrt(252)) if len(r) > 2 else float("nan"),
    }
    # the volume reaction on the filing session itself, against its own baseline
    base = v[max(0, j0 - 21):max(1, j0 - 1)]
    med = float(np.nanmedian(base)) if len(base) else np.nan
    out["surge"] = float(v[j0] / med) if med and np.isfinite(med) and med > 0 else float("nan")
    return out


def describe(ctx: dict) -> str:
    """The context block as the reader sees it. Units chosen to be scannable."""
    def m(x, unit="$", scale=1e6, suffix="M"):
        if x is None or not np.isfinite(x):
            return "n/a"
        if abs(x) >= 1e9 and scale == 1e6:
            return f"{unit}{x / 1e9:,.2f}B"
        return f"{unit}{x / scale:,.1f}{suffix}"

    def pc(x, dp=0):
        return "n/a" if x is None or not np.isfinite(x) else f"{x * 100:+.{dp}f}%"

    rev, ni, mc = ctx.get("revenue"), ctx.get("net_income"), ctx.get("mktcap")
    lines = [
        f"  size        market cap {m(mc)} | public float {m(ctx.get('float'))} "
        f"| price ${ctx.get('price', float('nan')):,.2f}",
        f"  business    revenue (TTM) {m(rev)} | net income (TTM) {m(ni)} "
        f"| cash {m(ctx.get('cash'))} | assets {m(ctx.get('assets'))}",
    ]
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
