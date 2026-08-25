"""Train the residual corrector, and test whether the residual idea earns its keep.

The architecture is the one specified: a fast solver produces ``Y_REM`` plus
compact internal features, local and context features supply what the solver
compressed away, and a small network predicts only the correction.

    z      = [ F_REM || Y_REM || F_local || F_context ]
    dY     = f_theta(z)                  Linear->SiLU 64 -> 64 -> 32 -> 1
    Y_hat  = Y_REM + dY
    target = Y_true - Y_REM

The claim being tested
----------------------
The design's central assertion is that learning the residual is *easier* than
learning the answer, because the solver has already explained most of it. That
is a testable statement and it is not automatically true: if the solver's error
is nearly all of the signal, the residual task is the original task with extra
steps, and the residual framing buys nothing but a fixed offset.

So the ablation that matters is arm C — the identical network, on the identical
inputs, trained to predict ``Y`` directly instead of ``Y - Y_REM``. Anything the
residual framing is worth shows up as the gap between B and C. Every other
comparison in the table is context for that one.

Arms
----
* **A  REM only** — the closed form, no network. How much does the physics get?
* **B  REM + residual MLP** — the proposed model.
* **C  direct MLP** — same inputs, same network, predicts ``Y``. The control.
* **D  gradient boosting on the 108 panel features** — the incumbent this
  project actually trades.
* **E  REM + residual MLP + the 108 panel features** — does it compose?
* **F  warm-started B** — weights carried across blocks with a replay buffer
  rather than re-initialised, which is the continual-correction idea.

Everything is walk-forward in six-month blocks with a fourteen-day embargo,
because a ten-session label overlaps the block boundary otherwise. Reported on
mean squared error, on the return of the daily top pick, and on direction.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adrnn_train import auc, build_arrays  # noqa: E402
from agreed_strategy import daily_paths  # noqa: E402
from moonshot_tail import MAX_TRAIN, blocks, scale_fit  # noqa: E402
from rem_solver import (compile_shared, context_features, infer,  # noqa: E402
                        local_features)

HORIZON = 10
COST = 20.0 / 1e4
EMBARGO = 14
EPOCHS = 40
BATCH = 4096
LR = 1e-3
REPLAY = 60_000


def mlp(d_in: int, d_out: int = 1):
    """The specified corrector: d -> 64 -> 64 -> 32 -> d_out, SiLU throughout."""
    import torch.nn as nn
    return nn.Sequential(
        nn.Linear(d_in, 64), nn.SiLU(),
        nn.Linear(64, 64), nn.SiLU(),
        nn.Linear(64, 32), nn.SiLU(),
        nn.Linear(32, d_out))


def pinball(q: float):
    """Quantile (pinball) loss. MSE targets the conditional mean; this targets a
    quantile, which is what a convex payoff needs -- `RESULT_MOONSHOT_TAIL.md`
    showed mean objectives systematically avoid the lottery tickets that carry
    the return here."""
    import torch

    def f(pred, target):
        e = target - pred
        return torch.mean(torch.maximum(q * e, (q - 1.0) * e))
    return f


def fit(net, Z, y, epochs=EPOCHS, seed=0, val_frac=0.15, log=None, lossf=None):
    """Train with Adam, early-stopped on a held-out tail of the block."""
    import torch
    torch.manual_seed(seed)
    n = len(Z)
    cut = int(n * (1 - val_frac))
    Zt = torch.from_numpy(Z[:cut]); yt = torch.from_numpy(y[:cut]).view(-1, 1)
    Zv = torch.from_numpy(Z[cut:]); yv = torch.from_numpy(y[cut:]).view(-1, 1)
    opt = torch.optim.Adam(net.parameters(), lr=LR)
    lossf = lossf or torch.nn.MSELoss()
    best, best_state, bad = np.inf, None, 0
    for ep in range(epochs):
        net.train()
        perm = torch.randperm(len(Zt))
        for i in range(0, len(Zt), BATCH):
            j = perm[i:i + BATCH]
            opt.zero_grad()
            loss = lossf(net(Zt[j]), yt[j])
            loss.backward()
            opt.step()
        net.eval()
        with torch.no_grad():
            v = float(lossf(net(Zv), yv))
        if v < best - 1e-9:
            best, bad = v, 0
            best_state = {k: p.detach().clone() for k, p in net.state_dict().items()}
        else:
            bad += 1
            if bad >= 6:
                break
    if best_state is not None:
        net.load_state_dict(best_state)
    if log is not None:
        log.append(best)
    return net


def predict(net, Z):
    import torch
    net.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(Z), 65536):
            out.append(net(torch.from_numpy(Z[i:i + 65536])).numpy().ravel())
    return np.concatenate(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--epochs", type=int, default=EPOCHS)
    args = ap.parse_args(argv)
    root = Path(args.root)

    import torch
    from sklearn.ensemble import HistGradientBoostingRegressor
    torch.set_num_threads(4)

    d, X, feats, idx = build_arrays(root / "adrnn_panel.parquet", args.stride)
    prices = pd.read_parquet(root / "w2015_prices.parquet",
                             columns=["date", "ticker", "open", "high", "low",
                                      "close", "volume"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)

    print("compiling the shared representation Phi_S", flush=True)
    mu, sig = compile_shared(prices)
    yrem_all, Frem_all, qnames = infer(mu, sig, HORIZON)
    Floc_all, lnames = local_features(prices)
    Fctx_all, cnames = context_features(prices, sig)
    print(f"  Phi_S -> {len(qnames)} queries from one sigma estimate", flush=True)

    paths = daily_paths(prices, idx, HORIZON)
    ret = np.nanprod(1.0 + np.nan_to_num(paths, nan=0.0), axis=1) - 1.0
    ret = np.where(np.isfinite(paths[:, 0]) & (np.abs(ret) <= 3.0), ret, np.nan)
    ok = np.isfinite(ret) & np.isfinite(sig[idx])
    rows, y = idx[ok], ret[ok].astype(np.float32)

    yrem = yrem_all[rows]
    Z = np.column_stack([Frem_all[rows], yrem.reshape(-1, 1),
                         Floc_all[rows], Fctx_all[rows]]).astype(np.float32)
    Xp = X[rows].astype(np.float32)
    dates = pd.Series(pd.to_datetime(d["date"].to_numpy()[rows]))
    znames = qnames + ["Y_REM"] + lnames + cnames
    print(f"  z has {Z.shape[1]} columns: {len(qnames)} F_REM + 1 Y_REM + "
          f"{len(lnames)} F_local + {len(cnames)} F_context")
    print(f"  {len(rows):,} rows with a realised return and a valid sigma\n", flush=True)

    res = {k: [] for k in ("A REM only", "B REM+residual", "C direct MLP",
                           "D gradient boosting", "E REM+resid+panel",
                           "F warm-started", "G REM+resid q75 loss")}
    warm = None
    buf_Z, buf_r = [], []
    vlog = []

    for b0, b1 in blocks(dates.max()):
        tr = np.flatnonzero(dates < b0 - pd.Timedelta(days=EMBARGO))
        te = np.flatnonzero((dates >= b0) & (dates < b1))
        if len(tr) < 40_000 or len(te) < 500:
            continue
        if len(tr) > MAX_TRAIN:
            tr = tr[np.linspace(0, len(tr) - 1, MAX_TRAIN).astype(int)]
        med, sc = scale_fit(Z[tr])
        Zt = np.clip((Z[tr] - med) / sc, -5, 5).astype(np.float32)
        Ze = np.clip((Z[te] - med) / sc, -5, 5).astype(np.float32)
        r_tr = (y[tr] - yrem[tr]).astype(np.float32)

        # A: the physics alone
        pa = yrem[te]
        # B: residual
        nb = fit(mlp(Zt.shape[1]), Zt, r_tr, args.epochs, 0, log=vlog)
        pb = yrem[te] + predict(nb, Ze)
        # C: the control -- same net, same inputs, predicts Y directly
        nc = fit(mlp(Zt.shape[1]), Zt, y[tr], args.epochs, 0)
        pc = predict(nc, Ze)
        # D: the incumbent
        mp, sp = scale_fit(Xp[tr])
        gb = HistGradientBoostingRegressor(loss="quantile", quantile=0.75,
                                           max_iter=250, learning_rate=0.05,
                                           max_depth=6, random_state=0)
        gb.fit(np.clip((Xp[tr] - mp) / sp, -5, 5), y[tr])
        pd_ = gb.predict(np.clip((Xp[te] - mp) / sp, -5, 5))
        # E: residual, with the panel features appended
        Zt2 = np.column_stack([Zt, np.clip((Xp[tr] - mp) / sp, -5, 5)]).astype(np.float32)
        Ze2 = np.column_stack([Ze, np.clip((Xp[te] - mp) / sp, -5, 5)]).astype(np.float32)
        ne = fit(mlp(Zt2.shape[1]), Zt2, r_tr, args.epochs, 0)
        pe = yrem[te] + predict(ne, Ze2)
        # F: warm-started with a replay buffer
        buf_Z.append(Zt); buf_r.append(r_tr)
        bZ = np.concatenate(buf_Z)[-REPLAY:]
        bR = np.concatenate(buf_r)[-REPLAY:]
        if warm is None:
            warm = mlp(Zt.shape[1])
        warm = fit(warm, bZ, bR, max(8, args.epochs // 4), 0)
        pf = yrem[te] + predict(warm, Ze)
        # G: the same residual model, trained to a q75 pinball loss instead of
        # MSE. If the architecture is sound and only the objective was wrong,
        # this is where it shows.
        ng = fit(mlp(Zt.shape[1]), Zt, r_tr, args.epochs, 0, lossf=pinball(0.75))
        pg = yrem[te] + predict(ng, Ze)

        for name, p in (("A REM only", pa), ("B REM+residual", pb),
                        ("C direct MLP", pc), ("D gradient boosting", pd_),
                        ("E REM+resid+panel", pe), ("F warm-started", pf),
                        ("G REM+resid q75 loss", pg)):
            s = pd.DataFrame({"d": dates.to_numpy()[te], "p": p, "r": y[te]})
            pick = s.sort_values("p", ascending=False).groupby("d").head(1)
            res[name].append({
                "block": f"{b0:%Y-%m}",
                "mse": float(np.mean((p - y[te]) ** 2)),
                "pick": float(pick.r.mean()) - COST,
                "auc": auc((y[te] > 0).astype(int), p)})
        print(f"  block {b0:%Y-%m}  n_tr {len(tr):,}  n_te {len(te):,}  "
              f"val {vlog[-1]:.5f}", flush=True)

    print("\n" + "=" * 104)
    print("RESULTS -- walk-forward, six-month blocks, 14-day embargo")
    print("=" * 104)
    print(f"{'arm':22s} {'blocks':>7s} {'MSE':>10s} {'vs REM':>9s} "
          f"{'pick ret':>10s} {'dir AUC':>9s}")
    base_mse = np.mean([r["mse"] for r in res["A REM only"]])
    summary = {}
    for name, rs in res.items():
        if not rs:
            continue
        t = pd.DataFrame(rs)
        summary[name] = t
        print(f"{name:22s} {len(t):>7d} {t.mse.mean():>10.5f} "
              f"{(t.mse.mean() / base_mse - 1) * 100:>+8.2f}% "
              f"{t.pick.mean() * 100:>+9.3f}% {t.auc.mean():>9.4f}")

    print("\n" + "=" * 104)
    print("THE ABLATION THAT MATTERS -- B (residual) against C (direct), paired")
    print("=" * 104)
    b = summary["B REM+residual"]
    c = summary["C direct MLP"]
    for metric, better in (("mse", "lower"), ("pick", "higher"), ("auc", "higher")):
        dl = (b[metric] - c[metric]).to_numpy()
        rng = np.random.default_rng(7)
        bs = np.array([rng.choice(dl, len(dl), True).mean() for _ in range(20000)])
        lo, hi = np.percentile(bs, [2.5, 97.5])
        win = (dl < 0).mean() if better == "lower" else (dl > 0).mean()
        print(f"  {metric:5s} B-C {dl.mean():+.6f}   95% CI [{lo:+.6f}, {hi:+.6f}]"
              f"   B better in {win * 100:.0f}% of blocks")
    print("\n  If these intervals straddle zero, the residual framing is doing")
    print("  nothing that the same network on the same inputs would not do.")

    print("\n" + "=" * 104)
    print("OBJECTIVE, NOT ARCHITECTURE -- G (residual, q75 loss) against C")
    print("=" * 104)
    g = summary.get("G REM+resid q75 loss")
    if g is not None:
        for metric, better in (("pick", "higher"), ("auc", "higher")):
            dl = (g[metric] - c[metric]).to_numpy()
            rng = np.random.default_rng(9)
            bs = np.array([rng.choice(dl, len(dl), True).mean() for _ in range(20000)])
            lo, hi = np.percentile(bs, [2.5, 97.5])
            win = (dl > 0).mean()
            print(f"  {metric:5s} G-C {dl.mean():+.6f}   95% CI [{lo:+.6f}, "
                  f"{hi:+.6f}]   G better in {win * 100:.0f}% of blocks")

    import torch as _t
    out = Path(args.root) / "rem_model.pt"
    _t.save({"state_dict": warm.state_dict(), "z_names": znames,
             "median": med, "scale": sc, "horizon": HORIZON,
             "arch": "d-64-64-32-1 SiLU", "target": "Y - Y_REM"}, out)
    print(f"\nsaved the warm-started corrector to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
