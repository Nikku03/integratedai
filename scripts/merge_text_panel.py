"""Merge per-filing text features onto the (ticker, date) panel, point-in-time.

The text features live per filing. The panel is per ticker-day. Turning one into
the other is where look-ahead usually creeps in, so the rules are explicit:

**A filing lands on the first trading day at or after its ``available_ts``.**
Not its event date. A document accepted at 20:30 on Tuesday is a Wednesday
feature.

**Two views of the same filing, because they answer different questions.**
The *latest* view carries the most recent filing's own features and how many
sessions ago it arrived — this is "what was just announced". The *window* view
counts occurrences over trailing 5/20/60 sessions — this is "what has been
happening lately". A single clinical readout and a company that has filed four
of them in a month are not the same state.

**Absence is a value, not a gap.** A ticker-day with no recent filing gets zeros
and a `days_since` of 999, rather than NaN, so the tree can split on "nothing
has happened" instead of imputing.

Coverage is partial by construction: text was fetched for biotech SIC codes
only, so most of the panel has no text. That is handled with an explicit
`has_text` flag rather than by dropping rows, and the evaluation compares
like-for-like on the covered subset.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

WINDOWS = (5, 20, 60)
NEVER = 999.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--text", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    root = Path(args.root)
    tpath = Path(args.text) if args.text else root / "text_feats_bio.parquet"
    out = Path(args.out) if args.out else root / "adrnn_panel_text.parquet"

    print("loading", flush=True)
    import pyarrow.parquet as pq
    panel_cols = [f.name for f in pq.ParquetFile(root / "adrnn_panel.parquet").schema_arrow]
    keys = pq.read_table(root / "adrnn_panel.parquet",
                         columns=["ticker", "date"]).to_pandas()
    keys["date"] = pd.to_datetime(keys["date"])
    t = pd.read_parquet(tpath)
    print(f"  panel {len(keys):,} rows, text {len(t):,} filings, "
          f"{t.ticker.nunique()} tickers")

    # --- land each filing on its first usable trading day ---------------
    t["avail"] = pd.to_datetime(t["available_ts"], utc=True, errors="coerce")
    t = t.dropna(subset=["avail"])
    t["date"] = (t["avail"].dt.tz_convert("America/New_York")
                 .dt.normalize().dt.tz_localize(None))
    featcols = [c for c in t.columns
                if c not in {"acc", "ticker", "available_ts", "avail", "date"}]
    print(f"  {len(featcols)} text feature columns")

    # Several filings can share a day. Take the max for the flags (any filing
    # that day said this) and the max for magnitudes (the biggest thing said).
    daily = (t.groupby(["ticker", "date"])[featcols].max().reset_index())
    daily["n_filings"] = (t.groupby(["ticker", "date"]).size()
                          .reset_index(drop=True).to_numpy())

    # "First trading day at or after" needs a forward search, not an equality
    # join. Joining on the exact date silently drops any filing whose
    # availability date is not itself a session for that ticker -- holidays,
    # dates outside the ticker's price history, days it did not trade -- which
    # was 197 of 7,601 filings, 2.6%. Snap each filing forward to the next
    # panel row for its ticker first, then the equality join is correct.
    keys["_row"] = np.arange(len(keys))
    ks = keys.sort_values(["ticker", "date"])
    panel_dates = {t: g["date"].to_numpy() for t, g in ks.groupby("ticker", sort=False)}
    snapped, drop = [], 0
    for tk, d in zip(daily["ticker"].to_numpy(), daily["date"].to_numpy()):
        pd_ = panel_dates.get(tk)
        if pd_ is None:
            snapped.append(np.datetime64("NaT"))
            drop += 1
            continue
        j = np.searchsorted(pd_, d, side="left")
        if j >= len(pd_):
            snapped.append(np.datetime64("NaT"))
            drop += 1
        else:
            snapped.append(pd_[j])
    daily["date"] = snapped
    moved = int((pd.notna(daily["date"])).sum())
    print(f"  snapped {moved:,} filing-days onto the next session "
          f"({drop:,} past the end of their ticker's history)")
    # Snapping can collide two filing-days onto one session -- a Saturday and
    # the following Monday both land on Monday. Collapse them the same way
    # same-day filings were collapsed above: max for the flags and magnitudes,
    # but a sum for the count, because two filings did arrive.
    daily = daily.dropna(subset=["date"])
    how = {c: "max" for c in daily.columns if c not in ("ticker", "date")}
    how["n_filings"] = "sum"
    daily = daily.groupby(["ticker", "date"], as_index=False).agg(how)

    m = keys.merge(daily, on=["ticker", "date"], how="left")
    m = m.sort_values(["ticker", "date"]).reset_index(drop=True)
    covered = m.ticker.isin(set(t.ticker.unique()))
    print(f"  panel rows for tickers with any text: {int(covered.sum()):,} "
          f"({covered.mean() * 100:.1f}%)")

    filed = m[featcols[0]].notna() if featcols else pd.Series(False, index=m.index)
    print(f"  panel rows that are themselves a filing day: {int(filed.sum()):,}")

    out_cols = {}
    gb = m.groupby("ticker", sort=False)

    # --- window view: how often, recently -------------------------------
    flags = [c for c in featcols
             if c.startswith(("cat_", "tox_")) or c in
             ("binding", "nonbinding", "tone_good", "tone_bad", "txt_ok")]
    zero = m[flags].fillna(0.0)
    for w in WINDOWS:
        r = (zero.groupby(m.ticker, sort=False)
                 .transform(lambda s, w=w: s.rolling(w, min_periods=1).sum()))
        for c in flags:
            out_cols[f"{c}_{w}d"] = r[c].to_numpy(dtype=np.float32)

    # --- latest view: what the most recent filing actually said ----------
    for c in featcols:
        s = m[c]
        out_cols[f"{c}_last"] = (s.groupby(m.ticker, sort=False).ffill()
                                 .fillna(0.0).to_numpy(dtype=np.float32))

    # --- how long since anything was filed at all ------------------------
    any_filing = filed.astype(float)
    idx = np.where(any_filing.to_numpy() > 0, np.arange(len(m)), np.nan)
    last = pd.Series(idx, index=m.index).groupby(m.ticker, sort=False).ffill()
    since = pd.Series(np.arange(len(m)), index=m.index) - last
    out_cols["text_days_since"] = since.fillna(NEVER).clip(upper=NEVER).to_numpy(
        dtype=np.float32)
    out_cols["has_text"] = covered.reindex(m.index).fillna(False).to_numpy(
        dtype=np.float32)
    out_cols["n_filings_5d"] = (m["n_filings"].fillna(0)
                                .groupby(m.ticker, sort=False)
                                .transform(lambda s: s.rolling(5, min_periods=1).sum())
                                .to_numpy(dtype=np.float32))

    add = pd.DataFrame(out_cols)
    add["_row"] = m["_row"].to_numpy()
    add = add.sort_values("_row").drop(columns="_row").reset_index(drop=True)
    print(f"\n  {add.shape[1]} new columns")

    # --- write the widened panel in row-group batches ---------------------
    # Materialising 8M rows x 200 columns as a pandas frame is roughly thirteen
    # gigabytes and gets the process killed. Arrow batches keep the peak at one
    # row group, and the new columns stay float32 instead of being widened to
    # float64 by pandas on the way through.
    import pyarrow as pa
    print("writing widened panel in batches", flush=True)
    src = pq.ParquetFile(root / "adrnn_panel.parquet")
    new_arrays = {c: add[c].to_numpy(dtype=np.float32) for c in add.columns}
    writer = None
    off = 0
    try:
        for batch in src.iter_batches(batch_size=250_000):
            n = batch.num_rows
            tbl = pa.Table.from_batches([batch])
            for c, arr in new_arrays.items():
                tbl = tbl.append_column(
                    c, pa.array(arr[off:off + n], type=pa.float32()))
            if writer is None:
                writer = pq.ParquetWriter(out, tbl.schema, compression="snappy")
            writer.write_table(tbl)
            off += n
            print(f"  {off:,}/{src.metadata.num_rows:,}", flush=True)
    finally:
        if writer is not None:
            writer.close()
    assert off == src.metadata.num_rows, "row count mismatch on write"
    print(f"wrote {out}  ({len(panel_cols) + len(add.columns)} columns, "
          f"{off:,} rows)")

    cov = pq.read_table(out, columns=["ticker", "has_text"]).to_pandas()
    cov = cov[cov.has_text > 0]
    print(f"\ncoverage: {len(cov):,} rows ({len(cov) / off * 100:.1f}%) "
          f"on {cov.ticker.nunique()} tickers")
    idx = cov.index.to_numpy()
    print("non-zero rate among covered rows, latest-filing view:")
    for c in sorted([c for c in add.columns if c.endswith("_last")])[:14]:
        print(f"  {c:34s} {(add[c].to_numpy()[idx] != 0).mean() * 100:5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
