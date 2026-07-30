"""One table: every moonshot last month and what caused it.

Earlier passes attributed SEC forms and government sources separately, so a mover
with an FDA approval but no 8-K showed up as "no filing" in one table and as a
gov hit in another. This merges them into a single cause per mover, with a fixed
precedence, and reports the counts the question actually asks for.

Precedence, and why this order
------------------------------
A mover often has several things happening at once -- a merger 8-K, a 13D, and
three Form 4s in the same week. Attribution has to pick one, and picking the
*most economically decisive* is the only defensible rule:

    merger/tender > FDA decision > trial readout > DoD award > offering/dilution
    > activist stake > 8-K > periodic report > passive stake > insider > other

A merger re-prices the whole company, so it outranks the 8-K that announces it.
An FDA approval outranks the 8-K that discloses it, because the FDA is the source
and the 8-K is the echo -- and the whole question here is which *source* to watch.
Insider forms rank last because a Form 4 is filed after almost everything.

The honest caveat is name matching
----------------------------------
Government sources publish company names, not tickers. Matching is exact on a
normalised name, which misses subsidiaries and any spelling the SEC does not use.
For the small set of movers with no SEC filing at all, each is additionally
checked by hand against the gov event tables, since that bucket is the answer to
"what are we missing" and a 9% global match rate would understate it badly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gov_catalysts import norm  # noqa: E402

WINDOW = (pd.Timestamp("2026-07-01"), pd.Timestamp("2026-07-29"))
LOOKBACK = pd.Timedelta(days=7)

#: Most economically decisive first. The first match wins.
PRECEDENCE = [
    "merger/tender", "FDA decision", "trial readout", "DoD contract",
    "offering/dilution", "activist stake", "8-K", "periodic report",
    "passive stake", "insider", "proxy/other", "NO KNOWN CAUSE",
]

SEC_MAP = [
    ("merger/tender", ("425", "SC TO-T", "SC 14D9", "SC TO-I", "DEFM14A")),
    ("offering/dilution", ("424B", "S-1", "S-3", "F-1", "F-3")),
    ("activist stake", ("SCHEDULE 13D", "SC 13D")),
    ("8-K", ("8-K",)),
    ("periodic report", ("10-Q", "10-K", "20-F", "6-K")),
    ("passive stake", ("SCHEDULE 13G", "SC 13G")),
    ("insider", ("4", "3", "144")),
    ("proxy/other", ("DEF 14A", "DEFA14A", "PRE 14A", "8-A12B", "S-8")),
]

GOV_MAP = {
    "fda_drug": "FDA decision", "fda_pma": "FDA decision",
    "fda_510k": "FDA decision",
    "trial_results": "trial readout", "trial_update": "trial readout",
}


def sec_causes(forms) -> set[str]:
    up = {str(f).upper().strip() for f in forms}
    out = set()
    for label, prefixes in SEC_MAP:
        for f in up:
            if any(f == p or f.startswith(p) for p in prefixes):
                out.add(label)
                break
    return out


def build(root: Path, threshold: float) -> pd.DataFrame:
    cen = pd.read_parquet(root / "census_moves.parquet")
    trad = cen[(cen.min_close >= 1.0) & (cen.median_dollars >= 250_000)].copy()
    mv = trad[(trad.max_1d >= threshold) | (trad.max_5d >= threshold)].copy()
    mv["move_date"] = pd.to_datetime(np.where(mv.max_1d >= threshold,
                                              mv.max_1d_date, mv.max_5d_start))
    mv["move_size"] = mv[["max_1d", "max_5d"]].max(axis=1)
    mv = mv[(mv.move_date >= WINDOW[0]) & (mv.move_date <= WINDOW[1])]

    fil = pd.read_parquet(root / "recent_filings.parquet")
    fil["accepted"] = pd.to_datetime(fil["accepted"], utc=True, format="mixed")
    fil["d"] = (fil["accepted"].dt.tz_convert("America/New_York")
                .dt.normalize().dt.tz_localize(None))
    covered = set(fil["ticker"].unique())

    gov = pd.read_parquet(root / "gov_events.parquet")
    gov = gov[gov.ticker.notna()].copy()
    gov["date"] = pd.to_datetime(gov["date"])

    dod = pd.read_csv(root / "dod_awards.tsv", sep="\t",
                      names=["date", "company", "value"]) \
        if (root / "dod_awards.tsv").exists() else pd.DataFrame()
    if len(dod):
        dod["date"] = pd.to_datetime(dod["date"])
        dod["key"] = dod["company"].map(norm)

    rows = []
    for r in mv.to_dict("records"):
        lo, hi = r["move_date"] - LOOKBACK, r["move_date"] + pd.Timedelta(days=1)
        causes = set()

        if r["ticker"] in covered:
            w = fil[(fil.ticker == r["ticker"]) & (fil.d >= lo) & (fil.d <= hi)]
            causes |= sec_causes(w["form"].tolist())
            n_fil = len(w)
            forms = ",".join(sorted(set(w["form"].astype(str))))
        else:
            n_fil, forms = -1, "NOT COVERED"

        g = gov[(gov.ticker == r["ticker"]) & (gov.date >= lo) & (gov.date <= hi)]
        for s in g["source"].unique():
            if s in GOV_MAP:
                causes.add(GOV_MAP[s])

        cause = next((c for c in PRECEDENCE if c in causes), "NO KNOWN CAUSE")
        rows.append({**r, "cause": cause, "n_filings": n_fil, "forms": forms,
                     "all_causes": ",".join(sorted(causes))})
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    args = ap.parse_args(argv)
    root = Path(args.root)

    for th in (0.10, 0.20, 0.50):
        d = build(root, th)
        d.to_parquet(root / f"ledger_{int(th * 100)}.parquet")
        cov = d[d.n_filings >= 0]
        print(f"\n{'=' * 72}")
        print(f"MOONSHOTS >= {th:.0%}, 1-29 July 2026, tradable universe "
              f"(>=$1, >=$250k/day)")
        print(f"{'=' * 72}")
        print(f"total movers: {len(d)}   with EDGAR coverage: {len(cov)}\n")
        g = (cov.groupby("cause")
               .agg(n=("move_size", "size"), median=("move_size", "median"),
                    biggest=("move_size", "max")))
        g = g.reindex([c for c in PRECEDENCE if c in g.index])
        g["share %"] = (g["n"] / len(cov) * 100).round(1)
        g["median"] = (g["median"] * 100).round(1)
        g["biggest"] = (g["biggest"] * 100).round(0)
        print(g.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
