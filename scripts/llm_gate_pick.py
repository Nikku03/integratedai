"""Add a reading layer to the daily k=1 catalyst pick, blind.

The model ranks the catalyst-gated pool by a q75 quantile score and takes the top
name each session. That score knows the price, the volatility and the shape of
the volume reaction — it does not know what the filing *said*. This puts a reader
between the shortlist and the trade: the model proposes the top few, the reader
opens the actual 8-K, judges whether the news is good, and the trade goes to the
best of them.

Why this window is a fair test of a reader
------------------------------------------
The scored window is July and August 2026, which is **after the reader's
knowledge cutoff**. These outcomes cannot be recalled, only inferred from the
document — which is the condition the earlier `llm_pilot.py` had to manufacture
by anonymising issuers and which here holds for free.

Blindness is still structural, not promised. ``--build`` writes two things to
different places: reading bundles containing the filing text, the ticker and the
date, and a shortlist table containing the realised returns. ``--score`` is the
first step that joins them. The reader never sees an outcome, and the join
appears in the command history if it happens early.

What is being measured
----------------------
Selections over the same fifteen sessions:

* **model k=1** — the top-scoring gated name. The control.
* **reader k=1** — the shortlist name the reader rates highest.
* **reader veto** — the model's top name, unless the reader judges the filing
  negative, in which case the next acceptable one down.

Each judgement carries a **direction** (-2..+2) and, once ``company_context``
was added, a **materiality** (0..3): not "is this good" but "how much does it
move the company", which is unanswerable from an 8-K alone because the document
never says how big the issuer is. That funds three further arms -- veto plus
most-material, ranking by direction x materiality, and positive-and-material.

If reading the document is worth anything, these beat the control. Fifteen
trades cannot establish that, and the report says so rather than implying
otherwise; what it can show is whether the judgement points the same way as the
outcome at all.

``--offset`` shifts the window back so a second, non-overlapping block can be
run. That is the test that matters: see ``docs/RESULT_LLM_GATE.md``, where the
two blocks disagree and the pooled effect is nil.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import company_context as cc  # noqa: E402
from agreed_strategy import daily_paths  # noqa: E402
from catalyst_pipeline import surge_features  # noqa: E402
from gate_live_test import UA, cik_map, since_matrix  # noqa: E402
from rem_solver import _roll_count, _roll_sum, compile_shared, infer  # noqa: E402

HORIZON = 10
COST = 20.0 / 1e4
ROW = re.compile(r"^(\S+)\s+(.+?)\s\s+(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(\S+)\s*$")
ACC = re.compile(r"(\d{10}-\d{2}-\d{6})")

#: A full EDGAR submission .txt is a concatenation of tagged documents behind a
#: header, and the first fifty thousand characters are XBRL scaffolding. Feeding
#: that to a reader wastes the whole budget on namespace declarations -- the
#: first attempt at this produced bundles that were almost entirely
#: `<ix:nonNumeric contextRef=...>`. So the documents are split apart, only the
#: 8-K body and its EX-99 press release are kept, and the item codes are lifted
#: from the header where they are stated in plain English.
DOC_RE = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.S)
TYPE_RE = re.compile(r"<TYPE>([^\n<]+)")
TEXT_RE = re.compile(r"<TEXT>(.*?)(?:</TEXT>|\Z)", re.S)
IXHDR = re.compile(r"<ix:header.*?</ix:header>", re.S | re.I)
HIDDEN = re.compile(r"<div[^>]*display:\s*none[^>]*>.*?</div>", re.S | re.I)
ITEMS = re.compile(r"ITEM INFORMATION:\s*(.+)")
#: Every 8-K opens with the same two thousand characters of cover page --
#: address, telephone number, the four Rule 425/14a-12/14d-2/13e-4 checkboxes,
#: the emerging-growth-company paragraph. Identical across filings, so it
#: carries no information and would eat most of a 2,600-character budget. The
#: substance begins at the first numbered item.
FIRST_ITEM = re.compile(r"Item\s+\d\.\d{2}", re.I)


def submission_text(raw: str, limit: int) -> str:
    """The readable half of a full EDGAR submission: items, 8-K body, press release."""
    import html as _h
    items = [x.strip() for x in ITEMS.findall(raw[:8000])]
    parts = []
    for doc in DOC_RE.findall(raw):
        t = TYPE_RE.search(doc)
        typ = t.group(1).strip() if t else ""
        if not (typ == "8-K" or typ.upper().startswith("EX-99")):
            continue
        body = TEXT_RE.search(doc)
        if not body:
            continue
        txt = IXHDR.sub(" ", body.group(1))
        txt = HIDDEN.sub(" ", txt)
        txt = re.sub(r"<[^>]+>", " ", txt)
        txt = _h.unescape(txt)
        txt = re.sub(r"[^\x20-\x7e]+", " ", txt)
        txt = re.sub(r"\s{2,}", " ", txt).strip()
        # drop the cover page, but only when doing so leaves a real body
        hit = FIRST_ITEM.search(txt)
        if hit and len(txt) - hit.start() > 400:
            txt = txt[hit.start():]
        if len(txt) > 200:
            parts.append(f"[{typ}] {txt}")
    head = ("ITEMS REPORTED: " + "; ".join(items)) if items else ""
    return (head + "\n\n" + "\n\n".join(parts)).strip()[:limit]


def scale_fit(Xtr):
    """Robust centre and scale, tolerant of missing values.

    `moonshot_tail.scale_fit` uses ``np.median``/``np.percentile``, which return
    NaN for any column containing one. That was fine while the features were
    REM and surge, both guaranteed finite by the eligibility mask. The context
    block is not -- a name without 60 sessions of history has no 60-day
    momentum -- so a single missing value turned the whole column NaN and
    sklearn's histogram binner failed with "window shape cannot be larger than
    input array shape". Trees handle NaN natively; the scaler has to let them.
    """
    med = np.nanmedian(Xtr, axis=0)
    q1, q3 = np.nanpercentile(Xtr, [25, 75], axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    sc = np.where(np.isfinite(q3 - q1) & ((q3 - q1) > 1e-8), (q3 - q1) / 1.349, 1.0)
    return med, sc


def eightks_with_acc(client, y0: int, y1: int) -> pd.DataFrame:
    """8-K index rows keeping the accession, so the document can be fetched."""
    out = []
    for y in range(y0, y1 + 1):
        for q in (1, 2, 3, 4):
            b = client.get_bytes(
                f"https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.idx")
            if not b:
                continue
            for line in b.decode("latin-1", errors="ignore").splitlines():
                if not line.startswith("8-K"):
                    continue
                m = ROW.match(line)
                if not m or m.group(1).strip() != "8-K":
                    continue
                a = ACC.search(m.group(5))
                out.append((int(m.group(3)), m.group(4),
                            a.group(1) if a else None, m.group(2).strip()))
    d = pd.DataFrame(out, columns=["cik", "filed", "acc", "company"])
    d["filed"] = pd.to_datetime(d["filed"])
    return d.dropna(subset=["acc"]).drop_duplicates(subset=["cik", "acc"])


def build(args) -> int:
    from iai.core.config import Config
    from iai.core.http import HttpClient
    from sklearn.ensemble import HistGradientBoostingRegressor
    cfg = Config.load()
    cl = HttpClient(cfg.data.cache_dir, UA, rate_per_sec=6.0, ttl_hours=24 * 365)
    root = Path(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    old = pd.read_parquet(root / "w2015_prices.parquet",
                          columns=["date", "ticker", "open", "high", "low",
                                   "close", "volume"])
    old["date"] = pd.to_datetime(old["date"])
    new = pd.read_parquet(args.recent)
    new["date"] = pd.to_datetime(new["date"])
    new = new[["date", "ticker", "open", "high", "low", "close", "volume"]]
    px = (pd.concat([old, new[new.date > old.date.max()]], ignore_index=True)
            .drop_duplicates(subset=["ticker", "date"], keep="last")
            .sort_values(["ticker", "date"]).reset_index(drop=True))

    print("indexing 8-K filings", flush=True)
    f = eightks_with_acc(cl, args.from_year, 2026)
    cmap = cik_map(cl)
    f["ticker"] = f["cik"].map(cmap)
    f = f.dropna(subset=["ticker"])
    f = f[f.ticker.isin(set(px.ticker.unique()))]
    print(f"  {len(f):,} filings with an accession, "
          f"{f.ticker.nunique():,} tickers", flush=True)

    since = since_matrix(px, f[["ticker", "filed"]])
    c_all = px["close"].to_numpy(float)
    v_all = np.nan_to_num(px["volume"].to_numpy(float), nan=0.0)
    t_all = px["ticker"].to_numpy()
    adv = _roll_sum(c_all * v_all, t_all, 20) / np.maximum(_roll_count(t_all, 20), 1)
    mu, sig = compile_shared(px)
    yrem, Frem, _ = infer(mu, sig, HORIZON)
    SG, _ = surge_features(px, since)
    # the company-context block, for the ranker as well as the reader. Only the
    # tape half can go here: fundamentals would mean a company-facts download
    # per training issuer, and training on features the test cannot have is the
    # broken comparison `gate_live_test.py` exists to avoid.
    PF = cc.panel_features(px, since)
    print(f"  context features: {PF.shape[1]} columns, "
          f"{np.isfinite(PF).all(axis=1).mean() * 100:.1f}% of rows complete",
          flush=True)
    elig = np.isfinite(sig) & (adv >= args.min_adv) & (c_all >= args.min_price)

    idx = np.flatnonzero(elig)[:: args.stride]
    paths = daily_paths(px, idx, HORIZON)
    ret = np.nanprod(1.0 + np.nan_to_num(paths, nan=0.0), axis=1) - 1.0
    full = np.isfinite(paths[:, HORIZON - 1])
    ret = np.where(np.isfinite(paths[:, 0]) & (np.abs(ret) <= 3.0), ret, np.nan)
    dates = pd.Series(pd.to_datetime(px["date"].to_numpy()[idx]))
    tick = px["ticker"].to_numpy()[idx]
    blocks = [Frem[idx], yrem[idx].reshape(-1, 1), SG[idx]]
    if not args.no_context:
        blocks.append(PF[idx])
    A = np.column_stack(blocks).astype(np.float32)
    gated = (since[idx] >= 1) & (since[idx] <= args.gate_days)
    usable = np.isfinite(ret) & full & gated

    sess = pd.DatetimeIndex(sorted(px.date.unique()))
    scor = sess[sess <= sess[-(HORIZON + 1)]]
    end = len(scor) - args.offset
    win = scor[max(0, end - args.days):end]
    cutoff = win[0] - pd.Timedelta(days=HORIZON * 2 + 14)
    print(f"window: {win[0]:%Y-%m-%d} -> {win[-1]:%Y-%m-%d} "
          f"({len(win)} sessions, offset {args.offset})", flush=True)
    tr = np.flatnonzero((dates < cutoff).to_numpy() & usable)
    if len(tr) > 250_000:
        tr = tr[np.linspace(0, len(tr) - 1, 250_000).astype(int)]
    med, sc = scale_fit(A[tr])
    mo = HistGradientBoostingRegressor(loss="quantile", quantile=0.75,
                                       max_iter=250, learning_rate=0.05,
                                       max_depth=6, random_state=0)
    mo.fit(np.clip((A[tr] - med) / sc, -5, 5), ret[tr])
    print(f"trained on {len(tr):,} gated rows before {cutoff:%Y-%m-%d}", flush=True)

    inwin = dates.isin(win).to_numpy() & usable
    t = pd.DataFrame({"date": dates[inwin].to_numpy(), "ticker": tick[inwin],
                      "ret": ret[inwin], "since": since[idx][inwin],
                      "p": mo.predict(np.clip((A[inwin] - med) / sc, -5, 5))})
    short = (t.sort_values("p", ascending=False).groupby("date")
              .head(args.top).sort_values(["date", "p"], ascending=[True, False])
              .reset_index(drop=True))
    short["rank"] = short.groupby("date").cumcount() + 1
    print(f"\nshortlist: {len(short)} candidates over {short.date.nunique()} "
          f"sessions (top {args.top} each)", flush=True)

    # attach the filing that triggered the gate, fetch it, and assemble the
    # point-in-time company context that makes materiality answerable
    f = f.sort_values("filed")
    date_all = pd.to_datetime(px["date"].to_numpy())
    rowix = {(t, d): i for i, (t, d) in enumerate(zip(t_all, date_all))}
    texts, accs, ctxs = [], [], []
    seen: dict[int, dict | None] = {}
    for _, r in short.iterrows():
        cand = f[(f.ticker == r.ticker) & (f.filed <= r.date)]
        if cand.empty:
            texts.append(""), accs.append(""), ctxs.append("")
            continue
        row = cand.iloc[-1]
        url = (f"https://www.sec.gov/Archives/edgar/data/{int(row.cik)}/"
               f"{row.acc.replace('-', '')}.txt")
        b = cl.get_bytes(url)
        if not b:
            b = cl.get_bytes(f"https://www.sec.gov/Archives/edgar/data/"
                             f"{int(row.cik)}/{row.acc}.txt")
        texts.append(submission_text(b.decode("utf-8", errors="ignore"),
                                     args.chars) if b else "")
        accs.append(row.acc)

        j = rowix.get((r.ticker, r.date))
        j0 = rowix.get((r.ticker, row.filed))
        if j is None:
            ctxs.append("")
            continue
        first = j
        while first > 0 and t_all[first - 1] == r.ticker:
            first -= 1
        c = cc.price_context(c_all, v_all, j - 1, j0, first)
        cik = int(row.cik)
        if cik not in seen:
            seen[cik] = cc.fetch(cl, cik)
        fa = seen[cik]
        if fa:
            sh = cc.stock(fa, "dei", "EntityCommonStockSharesOutstanding", r.date)
            c |= {
                "revenue": cc.flow(fa, cc.REVENUE_TAGS, r.date),
                "net_income": cc.flow(fa, "NetIncomeLoss", r.date),
                "cash": cc.stock(fa, "us-gaap",
                                 "CashAndCashEquivalentsAtCarryingValue", r.date),
                "assets": cc.stock(fa, "us-gaap", "Assets", r.date),
                "mktcap": sh * c["price"] if np.isfinite(sh) else float("nan"),
                "turnover": (c["adv20"] / c["price"] / sh
                             if np.isfinite(sh) and sh > 0 and c["price"] > 0
                             else float("nan")),
            }
        c["n8k"] = int(((f.ticker == r.ticker)
                        & (f.filed <= r.date)
                        & (f.filed > r.date - pd.Timedelta(days=90))).sum())
        ctxs.append(cc.describe(c))
    short["acc"] = accs
    short["chars"] = [len(x) for x in texts]
    print(f"  fetched {sum(1 for x in texts if x):,} filings, "
          f"mean {np.mean([len(x) for x in texts]):.0f} chars; "
          f"context for {sum(1 for x in ctxs if x):,}", flush=True)

    short.to_parquet(out / "shortlist.parquet")
    nb = 0
    for b0 in range(0, len(short), args.per_bundle):
        nb += 1
        chunk = short.iloc[b0:b0 + args.per_bundle]
        lines = [f"# Shortlist bundle {nb}", "",
                 "Each entry is a candidate the model ranked highly on that",
                 "session, with the 8-K that put it in the gate. No outcomes.", ""]
        for (_, r), tx, cx in zip(chunk.iterrows(),
                                  texts[b0:b0 + args.per_bundle],
                                  ctxs[b0:b0 + args.per_bundle]):
            lines += [f"## {r.date:%Y-%m-%d} | {r.ticker} | model rank {r['rank']}",
                      "", f"*filed {int(r['since'])} session(s) before entry*", "",
                      "### the company, as of the session before entry", "",
                      "```", cx if cx else "(context unavailable)", "```", "",
                      "### the filing", "",
                      "```", tx if tx else "(filing text unavailable)", "```", ""]
        (out / f"bundle_{nb}.md").write_text("\n".join(lines))
    print(f"wrote {nb} bundles and shortlist.parquet to {out}")
    print(f"  ~{sum(len(x) for x in texts) / 4 / 1000:.0f}k tokens to read")
    return 0


#: Sessions whose per-name returns already appear in `RESULT_CATALYST_GATE.md`
#: and `RESULT_MOONSHOT_HUNT.md`. The build/score split keeps the reader away
#: from `shortlist.parquet`, but it cannot un-publish a result document, and
#: those two list the gated picks with their realised moves. A reader who has
#: opened them is no longer blind on those dates, so they are excluded from the
#: headline arms and reported separately.
LEAKED = ("2026-07-21", "2026-07-23", "2026-07-29", "2026-07-31",
          "2026-08-04", "2026-08-05", "2026-08-10")


def score(args) -> int:
    out = Path(args.out)
    s = pd.read_parquet(out / "shortlist.parquet")
    lab = json.loads(Path(args.labels).read_text())
    L = pd.DataFrame([{"date": pd.Timestamp(k.split("|")[0].strip()),
                       "ticker": k.split("|")[1].strip(), **v}
                      for k, v in lab.items()])
    m = s.merge(L, on=["date", "ticker"], how="left")
    print(f"{m.judge.notna().sum()}/{len(m)} shortlist entries judged")
    if args.clean:
        keep = ~m.date.dt.strftime("%Y-%m-%d").isin(LEAKED)
        print(f"  clean subset: dropping {(~keep).sum()} entries on "
              f"{len(LEAKED)} already-published sessions, {keep.sum()} left "
              f"over {m[keep].date.nunique()} sessions")
        m = m[keep].reset_index(drop=True)
    print()
    m["net"] = m.ret - COST

    def show(name, sel):
        if not len(sel):
            print(f"  {name:22s} no trades")
            return
        r = sel.net.to_numpy()
        print(f"  {name:22s} {len(r):>2d} trades  mean {r.mean() * 100:>+7.2f}%  "
              f"median {np.median(r) * 100:>+7.2f}%  win {(r > 0).mean() * 100:>5.1f}%  "
              f"best {r.max() * 100:>+7.1f}%  worst {r.min() * 100:>+7.1f}%")

    print("=" * 96)
    print("DAILY k=1, WITH AND WITHOUT THE READING LAYER")
    print("=" * 96)
    model = m[m["rank"] == 1]
    show("model k=1 (control)", model)
    reader = (m[m.judge.notna()].sort_values(["date", "judge", "p"],
                                             ascending=[True, False, False])
                .groupby("date").head(1))
    show("reader k=1", reader)
    okmask = m.judge.fillna(0) >= 0
    veto = (m[okmask].sort_values(["date", "rank"]).groupby("date").head(1))
    show("reader veto", veto)
    show("shortlist average", m)

    # Materiality is a second, independent reading: not "is this good" but "how
    # much does it move the company", which is only answerable with the size
    # and revenue context the bundle now carries. It is a magnitude, so it is
    # used to break ties among names the direction call has already cleared,
    # and — signed — as a ranking of its own.
    if "mat" in m.columns and m.mat.notna().any():
        print()
        big = (m[okmask].sort_values(["date", "mat", "rank"],
                                     ascending=[True, False, True])
                 .groupby("date").head(1))
        show("veto + most material", big)
        m["impact"] = m.judge * m.mat
        imp = (m.sort_values(["date", "impact", "p"], ascending=[True, False, False])
                 .groupby("date").head(1))
        show("rank by judge x mat", imp)
        conf = m[(m.judge > 0) & (m.mat >= 2)]
        show("positive AND material", conf.sort_values(["date", "rank"])
                                          .groupby("date").head(1))

    print("\n" + "=" * 96)
    print("IS THE JUDGEMENT POINTING THE RIGHT WAY?")
    print("=" * 96)
    j = m[m.judge.notna()]
    if len(j) > 5:
        rho = j[["judge", "net"]].corr(method="spearman").iloc[0, 1]
        print(f"  rank correlation, judgement vs realised: {rho:+.3f} "
              f"({len(j)} filings)")
        g = j.groupby("judge").agg(n=("net", "size"),
                                   mean=("net", lambda x: x.mean() * 100),
                                   win=("net", lambda x: (x > 0).mean() * 100))
        print(g.round(2).to_string())
        pos, neg = j[j.judge > 0].net, j[j.judge < 0].net
        if len(pos) > 2 and len(neg) > 2:
            print(f"\n  judged positive: {len(pos)} filings, "
                  f"mean {pos.mean() * 100:+.2f}%")
            print(f"  judged negative: {len(neg)} filings, "
                  f"mean {neg.mean() * 100:+.2f}%")
            print(f"  spread {(pos.mean() - neg.mean()) * 100:+.2f}pp")
    # The pre-registered arm. `docs/PREREG_LLM_GATE_W3.md`, committed before
    # window C was built, names this as the primary hypothesis: the -1 bucket
    # was the best in windows A and B, so rejecting everything negative throws
    # away winners. Only the strong-negative call is supposed to carry.
    print()
    strong = (m[m.judge.fillna(0) >= -1].sort_values(["date", "rank"])
                .groupby("date").head(1))
    show("veto -2 only (PREREG)", strong)

    print("\n" + "=" * 96)
    print("WHERE THE VETO ACTUALLY BITES")
    print("=" * 96)
    print("  A veto only matters on a session where the model's own top pick")
    print("  reads badly. Those sessions, and what the swap cost or saved:\n")
    swap = 0.0
    for d, g in m.sort_values(["date", "rank"]).groupby("date"):
        top = g.iloc[0]
        if top.judge >= 0:
            continue
        alt = g[g.judge >= 0]
        if not len(alt):
            print(f"  {d:%Y-%m-%d}  {top.ticker:<5} judge {int(top.judge):+d} "
                  f"{top.net * 100:>+7.2f}%  ->  no acceptable alternative")
            continue
        a = alt.iloc[0]
        swap += a.net - top.net
        print(f"  {d:%Y-%m-%d}  {top.ticker:<5} judge {int(top.judge):+d} "
              f"{top.net * 100:>+7.2f}%  ->  {a.ticker:<5} judge "
              f"{int(a.judge):+d} {a.net * 100:>+7.2f}%   "
              f"{(a.net - top.net) * 100:>+7.2f}pp")
    print(f"\n  total swapped: {swap * 100:+.2f}pp over "
          f"{m.date.nunique()} sessions "
          f"= {swap / m.date.nunique() * 100:+.2f}pp per trade")

    print("\n  Fifteen trades cannot establish an edge. What this can show is")
    print("  whether the reading points the same way as the outcome at all.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--recent", default="/root/.iai/wide2015/recent_prices.parquet")
    ap.add_argument("--out", default="/root/.iai/wide2015/llm_gate")
    ap.add_argument("--from-year", type=int, default=2018)
    ap.add_argument("--gate-days", type=int, default=3)
    ap.add_argument("--days", type=int, default=15)
    ap.add_argument("--offset", type=int, default=0,
                    help="shift the scored window back this many "
                         "sessions; 15 gives the block before the "
                         "one already tested")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--chars", type=int, default=2600)
    ap.add_argument("--per-bundle", type=int, default=15)
    ap.add_argument("--min-adv", type=float, default=1e6)
    ap.add_argument("--min-price", type=float, default=1.0)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--score", metavar="LABELS.json")
    ap.add_argument("--no-context", action="store_true",
                    help="rank on REM and surge alone, as the first two "
                         "windows did, for a like-for-like comparison")
    ap.add_argument("--clean", action="store_true",
                    help="score only the sessions whose outcomes were not "
                         "already published in a RESULT_*.md")
    args = ap.parse_args(argv)
    if args.build:
        return build(args)
    if args.score:
        args.labels = args.score
        return score(args)
    ap.error("pass --build or --score")


if __name__ == "__main__":
    sys.exit(main())
