"""Can a reader tell a winning filing from a losing one? A blind pilot.

Running a language model over all 7,601 cached 8-Ks is affordable but not free,
and the regex pass already spent a week's work to conclude that text as
*categories* carries nothing the panel did not have. Before paying for the full
extraction it is worth answering the sharpest version of the question on a small
sample: **hand a reader the document with the issuer's name removed and no
outcome attached, and see whether its judgement ranks the +20% filings above the
−15% ones.**

If it cannot do that on a deliberately easy, balanced, case-control sample, the
full run will not rescue it and the money is better spent elsewhere. If it can,
the effect size measured here sets the expectation for the panel-wide test.

The protocol is blind by construction, not by good intentions
-------------------------------------------------------------
``--build`` writes two things to different places: reading bundles containing
*only* anonymised document text, and a truth table containing the outcomes. The
reader sees the bundles. ``--score`` is the first step that joins them. A reader
cannot condition on an outcome it was never shown, and because the join happens
in a separate invocation there is no way to peek without it appearing in the
command history.

Anonymisation is imperfect and that is stated rather than hidden. The issuer's
name and ticker are replaced, but drug names, trial acronyms and dates survive,
so a reader with memory of the event can still recognise some filings. That
makes the measured discrimination an **upper bound** on what a genuinely
uninformed reader would achieve.

Why case-control, and what the number means
-------------------------------------------
Big movers are rare. Sampling filings at random would spend most of the reading
budget on 8-Ks announcing a conference appearance. Sampling equal numbers from
the tails buys discrimination power at the cost of generality: the AUC reported
here is "can you separate a big winner from a big loser", not "can you rank the
whole panel". That is the right first question — it is the *easiest* version, so
a failure here is decisive in a way a failure on the full panel would not be.
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
from adrnn_train import auc  # noqa: E402
from exit_rules import walk  # noqa: E402
from filing_corpus import GENERIC, client, document, filing_table  # noqa: E402

HORIZON = 10
COST = 20.0 / 1e4
WIN = 0.15
LOSE = -0.10
CHARS = 2600
PER_BUNDLE = 16


def outcomes(root: Path, g: pd.DataFrame) -> pd.DataFrame:
    """Attach each filing to its first tradeable session and the realised move.

    Entry is the open of the session *after* the one the filing lands on, which
    is the same convention the panel labels use. A filing accepted at 20:30 on a
    Tuesday lands on Tuesday and is entered at Wednesday's open; one accepted at
    09:00 lands on Tuesday too and is still entered Wednesday, which forgoes the
    day-of move. That is deliberately conservative and it is what the trading
    results elsewhere assume.
    """
    prices = pd.read_parquet(root / "w2015_prices.parquet",
                             columns=["date", "ticker", "open", "high", "low",
                                      "close", "volume"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)
    o = prices["open"].to_numpy(float)
    h = prices["high"].to_numpy(float)
    lo = prices["low"].to_numpy(float)
    c = prices["close"].to_numpy(float)
    v = np.nan_to_num(prices["volume"].to_numpy(float), nan=0.0)
    tick = prices["ticker"].to_numpy()

    f = g.copy()
    f["avail"] = pd.to_datetime(f["available_ts"], utc=True, errors="coerce")
    f = f.dropna(subset=["avail"])
    f["date"] = (f["avail"].dt.tz_convert("America/New_York")
                 .dt.normalize().dt.tz_localize(None))

    # searchsorted per ticker gives the first session at or after the filing
    # date, so weekend and holiday filings land on the next open session instead
    # of being silently dropped by an exact-date join.
    rows = np.full(len(f), -1)
    starts = prices.groupby("ticker", sort=False).indices
    dts = prices["date"].to_numpy()
    fd = f["date"].to_numpy()
    ftk = f["ticker"].to_numpy()
    for i in range(len(f)):
        ix = starts.get(ftk[i])
        if ix is None:
            continue
        j = np.searchsorted(dts[ix], fd[i], side="left")
        if j < len(ix):
            rows[i] = ix[j]
    f["row"] = rows
    f = f[f.row >= 0].reset_index(drop=True)

    ret = np.full(len(f), np.nan)
    for a, i in enumerate(f.row.to_numpy()):
        r, _, _ = walk(o, h, lo, c, v, tick, int(i) + 1, HORIZON,
                       None, None, None, None, None)
        if np.isfinite(r) and abs(r) <= 3.0:
            ret[a] = r
    f["ret"] = ret
    f["entry_px"] = np.where(f.row.to_numpy() + 1 < len(o),
                             o[np.minimum(f.row.to_numpy() + 1, len(o) - 1)], np.nan)
    return f.dropna(subset=["ret"]).reset_index(drop=True)


def _identity_removed(anon: str, ticker: str, sec, row) -> bool:
    """Did anonymisation actually work on this filing?

    Redaction keys off the registrant's legal name, so it misses identity that
    leaks through other channels: exhibit file names like ``cvm_ex991.htm``,
    website addresses, subsidiary and drug names, and officers' signatures. A
    reader who recognises the issuer may be recalling the outcome rather than
    reading the document, which would inflate the result. Flagging those
    filings lets the discrimination be re-measured on the clean subset, which
    is the number that actually bears on a production run.
    """
    import html as _html
    from filing_corpus import registrant as _reg
    from text_features import fetch_text as _ft
    name = _reg(_html.unescape(_ft(sec, row) or ""))
    probe = [ticker.lower()]
    probe += [w.lower() for w in re.split(r"[^A-Za-z0-9]+", name)
              if len(w) > 3 and w.lower() not in GENERIC]
    low = anon.lower()
    return not any(p in low for p in probe if p)


def build(args) -> int:
    root = Path(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    known = pd.read_parquet(root / "text_feats_bio.parquet", columns=["acc"])
    g = filing_table(root, set(known.acc))
    print(f"{len(g):,} filings on {g.ticker.nunique()} tickers", flush=True)

    f = outcomes(root, g)
    print(f"{len(f):,} with a realised {HORIZON}-session return", flush=True)
    net = f.ret - COST
    win = f[net >= WIN]
    lose = f[net <= LOSE]
    print(f"  {len(win):,} winners (>= {WIN:+.0%}), {len(lose):,} losers "
          f"(<= {LOSE:+.0%}), {len(f) - len(win) - len(lose):,} in between")

    rng = np.random.default_rng(args.seed)
    k = args.n // 2
    pick = pd.concat([win.sample(min(k, len(win)), random_state=args.seed),
                      lose.sample(min(k, len(lose)), random_state=args.seed)])
    pick = pick.sample(frac=1.0, random_state=args.seed + 1).reset_index(drop=True)
    pick["fid"] = [f"F{i:03d}" for i in range(1, len(pick) + 1)]
    print(f"\nsampled {len(pick)} filings "
          f"({int((pick.ret - COST >= WIN).sum())} winners, "
          f"{int((pick.ret - COST <= LOSE).sum())} losers)", flush=True)

    sec = client()
    texts, clean_id = [], []
    for i, r in pick.iterrows():
        t = document(sec, r, args.chars, anonymous=True)
        texts.append(t)
        clean_id.append(_identity_removed(t, str(r.ticker), sec, r))
        if (i + 1) % 20 == 0:
            print(f"  read {i + 1}/{len(pick)}", flush=True)
    pick["chars"] = [len(t) for t in texts]
    pick["redacted_ok"] = clean_id
    print(f"  identity fully removed on {int(pick.redacted_ok.sum())}/{len(pick)}")

    # Truth goes somewhere the reader is not asked to look, and the bundles
    # carry nothing but text. This is the whole guarantee.
    cols = ["fid", "acc", "ticker", "date", "ret", "entry_px", "chars", "redacted_ok"]
    prev = out / "truth.parquet"
    if prev.exists():
        old = pd.read_parquet(prev)
        assert list(old.fid) == list(pick.fid) and list(old.acc) == list(pick.acc), \
            "rebuild changed the sample; existing labels would no longer line up"
    pick[cols].to_parquet(prev)

    n_b = 0
    for b0 in range(0, len(pick), PER_BUNDLE):
        n_b += 1
        chunk = pick.iloc[b0:b0 + PER_BUNDLE]
        lines = [f"# Filing bundle {n_b}", "",
                 "Anonymised 8-K text. No outcomes, no tickers, no dates of",
                 "publication beyond what the document itself states.", ""]
        for (_, r), t in zip(chunk.iterrows(), texts[b0:b0 + PER_BUNDLE]):
            lines += [f"## {r.fid}", "",
                      f"*items {', '.join(sorted(r['items']))}*", "",
                      "```", t, "```", ""]
        (out / f"bundle_{n_b}.md").write_text("\n".join(lines))
    print(f"\nwrote {n_b} bundles and truth.parquet to {out}")
    print(f"mean {pick.chars.mean():.0f} chars per filing, "
          f"{pick.chars.sum() / 4 / 1000:.0f}k tokens total")
    return 0


#: What the reader is asked for. ``impact`` is the primary score -- everything
#: else is diagnostic, there to show *why* a judgement was made and to test
#: whether a cruder field (news direction alone) would have done as well.
FIELDS = {
    "impact": "expected signed move over the next 10 sessions, in percent",
    "dir": "news direction for the company, -2 clearly bad to +2 clearly good",
    "subst": "substance 0-3: 0 vague/administrative, 3 hard numbers on a real endpoint",
    "dilution": "0-3 likelihood this filing implies imminent share issuance",
    "conf": "0-3 confidence in the impact estimate",
}


def score(args) -> int:
    out = Path(args.out)
    truth = pd.read_parquet(out / "truth.parquet")
    lab = json.loads(Path(args.labels).read_text())
    if isinstance(lab, dict):
        lab = [{"fid": k, **v} for k, v in lab.items()]
    L = pd.DataFrame(lab)
    m = truth.merge(L, on="fid", how="inner")
    miss = set(truth.fid) - set(L.fid)
    print(f"{len(m)}/{len(truth)} labelled" + (f"  (missing {sorted(miss)[:6]})"
                                               if miss else ""))
    if len(m) < 20:
        print("too few labels to score")
        return 1

    m["net"] = m.ret - COST
    y = (m.net >= WIN).astype(int).to_numpy()
    print(f"{int(y.sum())} winners, {int((1 - y).sum())} losers\n")

    print("=" * 84)
    print("1. DISCRIMINATION -- does the reading rank winners above losers?")
    print("=" * 84)
    rng = np.random.default_rng(11)
    for col in [c for c in ("impact", "dir", "subst", "dilution", "conf")
                if c in m.columns]:
        s = pd.to_numeric(m[col], errors="coerce").fillna(0.0).to_numpy(float)
        a = auc(y, s)
        bs = np.array([auc(y[i], s[i]) for i in
                       (rng.integers(0, len(y), len(y)) for _ in range(4000))])
        lo, hi = np.percentile(bs[np.isfinite(bs)], [2.5, 97.5])
        star = "  <-- primary" if col == "impact" else ""
        print(f"  {col:9s} AUC {a:.3f}   95% CI [{lo:.3f}, {hi:.3f}]   "
              f"P(<=0.5) = {(bs <= 0.5).mean():.4f}{star}")

    print("\n" + "=" * 84)
    print("2. CALIBRATION -- is the predicted size related to the realised one?")
    print("=" * 84)
    if "impact" in m.columns:
        p = pd.to_numeric(m["impact"], errors="coerce").fillna(0.0).to_numpy(float)
        r = m.net.to_numpy() * 100
        rho = pd.Series(p).corr(pd.Series(r), method="spearman")
        print(f"  rank correlation predicted vs realised: {rho:+.3f}")
        print(f"  sign agreement: {(np.sign(p) == np.sign(r)).mean() * 100:.1f}%")
        q = pd.qcut(pd.Series(p).rank(method="first"), min(4, m.fid.nunique()),
                    labels=False)
        g = pd.DataFrame({"q": q, "r": r, "y": y}).groupby("q").agg(
            n=("r", "size"), mean_ret=("r", "mean"), win_rate=("y", "mean"))
        g["win_rate"] *= 100
        print(g.round(2).to_string())

    print("\n" + "=" * 84)
    print("3. WHAT WOULD IT HAVE TRADED?")
    print("=" * 84)
    if "impact" in m.columns:
        p = pd.to_numeric(m["impact"], errors="coerce").fillna(0.0).to_numpy(float)
        for thr in (0, 5, 10, 20):
            sel = p >= thr
            if sel.sum() == 0:
                continue
            print(f"  buy when predicted >= {thr:>2d}%:  {int(sel.sum()):>2d} trades   "
                  f"mean {m.net.to_numpy()[sel].mean() * 100:+7.2f}%   "
                  f"win rate {y[sel].mean() * 100:5.1f}%")
        print(f"  {'buy everything':<24s}  {len(m):>2d} trades   "
              f"mean {m.net.mean() * 100:+7.2f}%   win rate {y.mean() * 100:5.1f}%")

    # ---- 4. is it reading, or remembering? ----------------------------
    print("\n" + "=" * 84)
    print("4. LEAKAGE -- does the edge survive on filings where the issuer was "
          "genuinely hidden?")
    print("=" * 84)
    if "redacted_ok" in m.columns and "impact" in m.columns:
        s = pd.to_numeric(m["impact"], errors="coerce").fillna(0.0).to_numpy(float)
        ok = m.redacted_ok.to_numpy(dtype=bool)
        print(f"  identity fully removed on {int(ok.sum())}/{len(m)} filings")
        for lab, sel in (("clean only", ok), ("leaked only", ~ok)):
            if sel.sum() < 8 or len(set(y[sel])) < 2:
                print(f"  {lab:12s} too few to score ({int(sel.sum())})")
                continue
            print(f"  {lab:12s} n {int(sel.sum()):>2d}   "
                  f"{int(y[sel].sum())} winners   AUC {auc(y[sel], s[sel]):.3f}")

    # ---- 5. do the fields add up to more than the headline judgement? --
    print("\n" + "=" * 84)
    print("5. COMBINED -- the summary judgement against its components")
    print("=" * 84)
    have = [c for c in ("impact", "dir", "subst", "dilution") if c in m.columns]
    num = {c: pd.to_numeric(m[c], errors="coerce").fillna(0.0).to_numpy(float)
           for c in have}
    rk = {c: pd.Series(v).rank(pct=True).to_numpy() for c, v in num.items()}
    combos = {}
    if "impact" in rk:
        combos["impact alone"] = rk["impact"]
    if "dilution" in rk:
        combos["no-dilution alone"] = 1.0 - rk["dilution"]
    if "impact" in rk and "dilution" in rk:
        combos["impact - dilution"] = rk["impact"] - rk["dilution"]
    if "impact" in rk and "dir" in rk:
        combos["impact + direction"] = rk["impact"] + rk["dir"]
    for name, s in combos.items():
        a = auc(y, s)
        bs = np.array([auc(y[i], s[i]) for i in
                       (rng.integers(0, len(y), len(y)) for _ in range(4000))])
        lo, hi = np.percentile(bs[np.isfinite(bs)], [2.5, 97.5])
        print(f"  {name:20s} AUC {a:.3f}   95% CI [{lo:.3f}, {hi:.3f}]   "
              f"P(<=0.5) = {(bs <= 0.5).mean():.4f}")
    print("\n  For reference, the same win-versus-lose question on the 108 numeric")
    print("  panel features reached 0.5302 out of sample (RESULT_WHY_LOSERS.md).")

    # ---- 6. same documents, the other reader -------------------------
    print("\n" + "=" * 84)
    print("6. REGEX ON THE SAME 64 DOCUMENTS -- the like-for-like comparison")
    print("=" * 84)
    rx_path = Path(args.root) / "text_feats_bio.parquet"
    if not rx_path.exists():
        print("  no regex features on disk")
        return 0
    rx = pd.read_parquet(rx_path)
    j = m[["fid", "acc"]].merge(rx, on="acc", how="left")
    cols = [c for c in rx.columns if c not in ("acc", "ticker", "available_ts")]
    rows = []
    for c in cols:
        v = pd.to_numeric(j[c], errors="coerce").fillna(0.0).to_numpy(float)
        if np.nanstd(v) < 1e-9:
            continue
        a = auc(y, v)
        rows.append((c, a, max(a, 1 - a)))
    tab = pd.DataFrame(rows, columns=["feature", "auc", "abs"]).sort_values(
        "abs", ascending=False)
    print("  strongest regex features on these filings, direction chosen with")
    print("  hindsight -- deliberately generous, since the LLM fields were not:")
    for _, r in tab.head(6).iterrows():
        d = "as-is" if r.auc >= 0.5 else "inverted"
        print(f"    {r.feature:24s} AUC {r['abs']:.3f}  ({d})")
    print(f"\n  best regex feature      {tab['abs'].max():.3f}  (in-sample pick)")
    if "impact" not in rk or "dilution" not in rk:
        return 0
    s = rk["impact"] - rk["dilution"]
    print(f"  LLM impact - dilution   {auc(y, s):.3f}  (fixed in advance)")

    # Paired, because both readers scored the same 64 documents. The gap is
    # what a production run would be buying, and on this many filings it is
    # the confidence interval that decides whether the run is worth paying for.
    best = tab.iloc[0]
    bv = pd.to_numeric(j[best.feature], errors="coerce").fillna(0.0).to_numpy(float)
    if best.auc < 0.5:
        bv = -bv
    d = []
    for _ in range(4000):
        i = rng.integers(0, len(y), len(y))
        if len(set(y[i])) < 2:
            continue
        d.append(auc(y[i], s[i]) - auc(y[i], bv[i]))
    d = np.array(d)
    lo, hi = np.percentile(d, [2.5, 97.5])
    print(f"\n  LLM minus best regex:  {auc(y, s) - float(best['abs']):+.3f}   "
          f"95% CI [{lo:+.3f}, {hi:+.3f}]   P(<=0) = {(d <= 0).mean():.4f}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--out", default="/root/.iai/wide2015/llm_pilot")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--score", metavar="LABELS.json")
    ap.add_argument("--n", type=int, default=64)
    ap.add_argument("--chars", type=int, default=CHARS)
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args(argv)
    if args.build:
        return build(args)
    if args.score:
        args.labels = args.score
        return score(args)
    ap.error("pass --build or --score")


if __name__ == "__main__":
    sys.exit(main())
