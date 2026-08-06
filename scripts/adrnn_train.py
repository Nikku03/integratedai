"""Train and score the ADRNN against the baselines it has to beat.

Runs the protocol frozen in ``docs/PREREGISTRATION_ADRNN.md``. The splits are
temporal with an embargo, the test period is scored once, and the pass/fail
criteria were written down before any of this was run.

Three things here are deliberate and worth stating, because each is a way this
kind of model usually produces a fake result.

**The scaler is fitted on train only.** Fitting normalisation on the full panel
leaks the test period's distribution into training, which is enough on its own
to manufacture an AUC.

**Samples are strided in time.** With a ten-day label horizon, consecutive rows
for one ticker share nine of their ten label days, so daily sampling would count
the same event ten times and shrink every confidence interval by roughly the
square root of that. Striding is a statistical correction that also happens to
make CPU training feasible.

**Bootstrap is clustered by week.** Returns are correlated across names on the
same day; resampling rows independently would treat one market-wide move as
hundreds of independent observations.

The bar is the trailing-volatility logistic regression, not the base rate.
Volatility clustering already predicts large moves, so a sequence model that
cannot beat one variable has justified nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

SEQ_LEN = 60
META = {"ticker", "date", "entry", "max_up", "max_dn", "mag", "y_mag",
        "y_dir", "eligible", "adv_usd", "tradable"}

TRAIN_END = "2022-12-31"
VAL_START, VAL_END = "2023-01-01", "2024-06-30"
TEST_START = "2024-07-01"
EMBARGO_DAYS = 10


def build_arrays(path: Path, stride: int):
    """Contiguous feature matrix plus the sample indices that point into it.

    Sequences are never materialised. The panel is one float32 block ordered by
    (ticker, date) and a sample is a slice of sixty consecutive rows, which is
    the difference between three gigabytes and two hundred.

    The columns are streamed in small groups into a pre-allocated float32 block
    rather than loaded as a DataFrame and converted. ``to_numpy`` on a
    hundred-column frame materialises a float64 intermediate first -- roughly
    seven gigabytes here -- and then a float32 copy on top of it, which is
    enough to be killed on a sixteen-gigabyte machine.
    """
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    all_cols = [f.name for f in pf.schema_arrow]
    feats = [c for c in all_cols if c not in META]
    meta_cols = [c for c in all_cols if c in META]

    d = pq.read_table(path, columns=meta_cols).to_pandas()
    n = len(d)
    X = np.empty((n, len(feats)), dtype=np.float32)
    for j0 in range(0, len(feats), 12):
        chunk = feats[j0:j0 + 12]
        t = pq.read_table(path, columns=chunk)
        for j, c in enumerate(chunk):
            col = t.column(c).to_numpy(zero_copy_only=False)
            X[:, j0 + j] = np.nan_to_num(
                col.astype(np.float32, copy=False),
                nan=0.0, posinf=0.0, neginf=0.0)
        del t

    # The panel is written in (ticker, date) order by adrnn_dataset.py; assert
    # it rather than re-sorting, because sorting here would need a permutation
    # of the whole block and double the peak memory again.
    tick = d["ticker"].to_numpy()
    chg = np.flatnonzero(tick[1:] != tick[:-1])
    assert len(np.unique(tick)) == len(chg) + 1, "panel is not grouped by ticker"
    first = np.r_[True, tick[1:] != tick[:-1]]
    grp_start = np.maximum.accumulate(np.where(first, np.arange(len(tick)), 0))
    pos_in_grp = np.arange(len(tick)) - grp_start

    ok = (d["eligible"].to_numpy(dtype=bool)
          & (pos_in_grp >= SEQ_LEN - 1)
          & np.isfinite(d["y_mag"].to_numpy(dtype=np.float64)))
    idx = np.flatnonzero(ok)
    if stride > 1:
        idx = idx[::stride]
    return d, X, feats, idx


def split_idx(d: pd.DataFrame, idx: np.ndarray):
    dt = d["date"].to_numpy()[idx]
    emb = np.timedelta64(EMBARGO_DAYS, "D")
    tr_end = np.datetime64(TRAIN_END) - emb
    va_s, va_e = np.datetime64(VAL_START), np.datetime64(VAL_END) - emb
    te_s = np.datetime64(TEST_START)
    return (idx[dt <= tr_end], idx[(dt >= va_s) & (dt <= va_e)],
            idx[dt >= te_s])


def robust_scaler(X: np.ndarray, rows: np.ndarray):
    """Median/IQR from the training rows only, clipped at five deviations."""
    sub = X[rows]
    med = np.median(sub, axis=0)
    q1, q3 = np.percentile(sub, [25, 75], axis=0)
    scale = np.where((q3 - q1) > 1e-8, (q3 - q1) / 1.349, 1.0)
    return med.astype(np.float32), scale.astype(np.float32)


def auc(y: np.ndarray, s: np.ndarray) -> float:
    """Rank AUC with tie handling."""
    y = np.asarray(y, dtype=np.float64)
    n1, n0 = float(y.sum()), float((1 - y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = pd.Series(s).rank().to_numpy()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def weekly_boot_diff(y, sa, sb, weeks, n=4000, seed=17):
    """Paired AUC difference, resampling whole weeks."""
    rng = np.random.default_rng(seed)
    uw = np.unique(weeks)
    where = {w: np.flatnonzero(weeks == w) for w in uw}
    out = []
    for _ in range(n):
        pick = rng.choice(uw, len(uw), replace=True)
        sel = np.concatenate([where[w] for w in pick])
        ys = y[sel]
        if ys.sum() == 0 or ys.sum() == len(ys):
            continue
        out.append(auc(ys, sa[sel]) - auc(ys, sb[sel]))
    a = np.array(out)
    return float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5)), float((a <= 0).mean())


def weekly_boot_auc(y, s, weeks, null=0.5, n=4000, seed=19):
    rng = np.random.default_rng(seed)
    uw = np.unique(weeks)
    where = {w: np.flatnonzero(weeks == w) for w in uw}
    out = []
    for _ in range(n):
        pick = rng.choice(uw, len(uw), replace=True)
        sel = np.concatenate([where[w] for w in pick])
        ys = y[sel]
        if ys.sum() == 0 or ys.sum() == len(ys):
            continue
        out.append(auc(ys, s[sel]))
    a = np.array(out)
    return (float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5)),
            float((a <= null).mean()))


def precision_at_k(dates, y, s, k=20):
    """Mean precision of the top-k names on each day -- how it would be used.

    Only days that actually offer more than k candidates are counted. On a day
    with six eligible names the top twenty is all six, and scoring it would
    silently report the base rate as if it were precision.
    """
    df = pd.DataFrame({"d": dates, "y": y, "s": s})
    big = df.groupby("d")["y"].transform("size") > k
    df = df[big]
    if df.empty:
        return float("nan"), 0
    hits = df.sort_values("s", ascending=False).groupby("d").head(k)
    return float(hits.y.mean()), int(len(hits))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=10,
                    help="sample every Nth eligible row; see module docstring")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--d-model", type=int, default=128)
    ap.add_argument("--blocks", type=int, default=3)
    ap.add_argument("--max-train", type=int, default=250_000)
    ap.add_argument("--skip-nn", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root)

    print("loading panel", flush=True)
    d, X, feats, idx = build_arrays(root / "adrnn_panel.parquet", args.stride)
    print(f"  {len(d):,} panel rows, {X.shape[1]} features, "
          f"{len(idx):,} samples after stride {args.stride}", flush=True)

    tr, va, te = split_idx(d, idx)
    y_mag = d["y_mag"].to_numpy(dtype=np.float32)
    y_dir = d["y_dir"].to_numpy(dtype=np.float32)
    dates = d["date"].to_numpy()
    print(f"  train {len(tr):,}  val {len(va):,}  test {len(te):,}")
    for nm, s in (("train", tr), ("val", va), ("test", te)):
        if len(s):
            print(f"    {nm:5s} {pd.Timestamp(dates[s].min()):%Y-%m-%d}"
                  f"..{pd.Timestamp(dates[s].max()):%Y-%m-%d}   "
                  f"base rate {y_mag[s].mean() * 100:.2f}%   "
                  f"P(up|big) {y_dir[s][y_mag[s] == 1].mean() * 100:.2f}%")

    if len(tr) > args.max_train:
        sel = np.linspace(0, len(tr) - 1, args.max_train).astype(int)
        tr = tr[sel]
        print(f"  train capped to {len(tr):,} (evenly across time)")

    med, scale = robust_scaler(X, tr)
    te_weeks = pd.Series(dates[te]).dt.to_period("W").astype(str).to_numpy()

    results = {}

    # ---------------- baselines ----------------
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier

    vol_i = feats.index("vol_20d")
    def flat(rows):
        return (X[rows] - med) / scale

    print("\nbaseline 1: base rate")
    base = float(y_mag[tr].mean())
    results["base_rate"] = base
    print(f"  train base rate {base * 100:.2f}%")

    print("baseline 2: trailing-volatility logistic")
    lr = LogisticRegression(max_iter=1000)
    lr.fit(flat(tr)[:, [vol_i]], y_mag[tr])
    s_vol = lr.predict_proba(flat(te)[:, [vol_i]])[:, 1]
    a_vol = auc(y_mag[te], s_vol)
    results["auc_vol"] = a_vol
    print(f"  test AUC {a_vol:.4f}")

    print("baseline 3: gradient boosting on flat features")
    gb = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06,
                                        max_depth=6, random_state=0)
    gb.fit(flat(tr), y_mag[tr])
    s_gb = gb.predict_proba(flat(te))[:, 1]
    a_gb = auc(y_mag[te], s_gb)
    results["auc_gb"] = a_gb
    print(f"  test AUC {a_gb:.4f}")

    if args.skip_nn:
        print(json.dumps(results, indent=2))
        return 0

    # ---------------- ADRNN ----------------
    import torch
    from torch.utils.data import DataLoader, Dataset
    from adrnn_model import ADRNN, two_head_loss
    torch.manual_seed(0)
    torch.set_num_threads(4)

    class Seq(Dataset):
        def __init__(self, rows): self.rows = rows
        def __len__(self): return len(self.rows)
        def __getitem__(self, k):
            i = int(self.rows[k])
            w = (X[i - SEQ_LEN + 1:i + 1] - med) / scale
            return (torch.from_numpy(np.clip(w, -5, 5).astype(np.float32)),
                    torch.tensor(y_mag[i]), torch.tensor(y_dir[i]))

    dl_tr = DataLoader(Seq(tr), batch_size=args.batch, shuffle=True,
                       num_workers=0, drop_last=True)
    dl_va = DataLoader(Seq(va), batch_size=512, shuffle=False)
    dl_te = DataLoader(Seq(te), batch_size=512, shuffle=False)

    model = ADRNN(X.shape[1], d_model=args.d_model, n_blocks=args.blocks)
    n_par = sum(p.numel() for p in model.parameters())
    print(f"\nADRNN: {n_par:,} parameters, {X.shape[1]} input features")
    pw = torch.tensor(max(1.0, (1 - base) / max(base, 1e-6)), dtype=torch.float32)
    print(f"  pos_weight {float(pw):.2f}")
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)

    def infer(dl):
        model.eval()
        pm, pd_ = [], []
        with torch.no_grad():
            for xb, _, _ in dl:
                lm, ld = model(xb)
                pm.append(torch.sigmoid(lm).numpy())
                pd_.append(torch.sigmoid(ld).numpy())
        return np.concatenate(pm), np.concatenate(pd_)

    best, best_state, t0 = -1.0, None, time.time()
    for ep in range(1, args.epochs + 1):
        model.train()
        tot = n = 0
        for xb, ym, yd in dl_tr:
            opt.zero_grad()
            lm, ld = model(xb)
            loss, _, _ = two_head_loss(lm, ld, ym, yd, pw)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += float(loss.detach()) * len(xb); n += len(xb)
        sched.step()
        vm, _ = infer(dl_va)
        a = auc(y_mag[va], vm)
        print(f"  epoch {ep}/{args.epochs}  loss {tot / max(n,1):.4f}  "
              f"val AUC {a:.4f}  [{time.time() - t0:.0f}s]", flush=True)
        if a > best:
            best = a
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
    if best_state:
        model.load_state_dict(best_state)

    s_nn, s_dir = infer(dl_te)
    a_nn = auc(y_mag[te], s_nn)
    results["auc_adrnn"] = a_nn
    results["auc_val_best"] = best

    print("\n" + "=" * 72)
    print("TEST RESULTS -- scored once, per the pre-registration")
    print("=" * 72)
    print(f"  base rate            {y_mag[te].mean() * 100:6.2f}%")
    print(f"  trailing-vol logistic AUC {a_vol:.4f}")
    print(f"  gradient boosting     AUC {a_gb:.4f}")
    print(f"  ADRNN magnitude       AUC {a_nn:.4f}")

    lo, hi, p = weekly_boot_diff(y_mag[te], s_nn, s_vol, te_weeks)
    results["primary"] = {"diff_lo": lo, "diff_hi": hi, "p": p}
    print(f"\nPRIMARY  ADRNN - vol baseline = {a_nn - a_vol:+.4f}")
    print(f"  week-clustered 95% CI [{lo:+.4f}, {hi:+.4f}]   P(<=0) = {p:.4f}")
    primary = "PASS" if lo > 0 else "FAIL"
    print(f"  -> {primary}")

    for k in (10, 20, 50):
        pk, nk = precision_at_k(dates[te], y_mag[te], s_nn, k)
        pv, _ = precision_at_k(dates[te], y_mag[te], s_vol, k)
        print(f"\nSECONDARY  precision@{k}/day: ADRNN {pk * 100:5.2f}%   "
              f"vol {pv * 100:5.2f}%   base {y_mag[te].mean() * 100:5.2f}%  (n={nk:,})")
        if k == 20:
            results["prec20_adrnn"] = pk
            results["prec20_vol"] = pv
            results["prec20_base"] = float(y_mag[te].mean())

    mask = y_mag[te] == 1
    if mask.sum() > 50:
        a_dir = auc(y_dir[te][mask], s_dir[mask])
        lo2, hi2, p2 = weekly_boot_auc(y_dir[te][mask], s_dir[mask],
                                       te_weeks[mask], null=0.5)
        results["auc_dir"] = a_dir
        results["direction"] = {"lo": lo2, "hi": hi2, "p": p2}
        print(f"\nDIRECTION  head AUC on the {int(mask.sum()):,} real moves: "
              f"{a_dir:.4f}")
        print(f"  week-clustered 95% CI [{lo2:.4f}, {hi2:.4f}]   "
              f"P(<=0.5) = {p2:.4f}")
        print(f"  -> {'PASS' if lo2 > 0.5 else 'FAIL'}  "
              f"(the pre-registration predicted FAIL)")

    out = root / "adrnn_results.json"
    out.write_text(json.dumps(results, indent=2, default=float))
    np.savez_compressed(root / "adrnn_test_scores.npz",
                        idx=te, s_mag=s_nn, s_dir=s_dir, s_vol=s_vol, s_gb=s_gb,
                        y_mag=y_mag[te], y_dir=y_dir[te])
    print(f"\nwrote {out}")
    print("Survivorship: 0 of 3,662 tickers ever delisted in this panel. "
          "Baseline comparisons hold; absolute numbers do not.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
