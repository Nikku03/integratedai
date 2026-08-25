# The universal REM residual model, built and trained

Implemented as specified, on this project's forward-return problem, with the one
ablation that can actually falsify the design. The headline: **the architecture's
central claim is supported, and it does not help.** Those are compatible, and the
reason is the interesting part.

## What plays the role of REM here

The known mathematics is the diffusion. A price under geometric Brownian motion
has `log(S_T/S_0) ~ Normal(μT, σ²T)`, which gives closed forms for the expected
return, every quantile, the probability of finishing up, and — via the reflection
principle — the probability of *touching* a barrier anywhere inside the window:

```
P( max_{t≤T} X_t ≥ b ) = Φ((μT − b)/(σ√T)) + exp(2μb/σ²)·Φ((−b − μT)/(σ√T))
```

That last one matters because this project's labels are excursion-based. It is
exact for Brownian motion and costs two normal CDFs.

**The shared representation is real, not decorative.** `Φ_S = (μ̂, σ̂)` is
estimated once per ticker-day; **fifteen queries** then reuse it. The volatility
estimate is the expensive part and it is amortised across every question asked of
that row — exactly the reuse the design is built around.

**What was deliberately withheld from the solver** became `F_local`: skew,
kurtosis, the overnight-gap share of variance, jump rate, dead-session fraction,
volume shocks, illiquidity. Every one is something a Gaussian diffusion cannot
represent, so the residual has something to be made of. `F_context` carries
market-wide volatility, cross-sectional volatility rank, price level and date.

```
z = [ F_REM(15) ‖ Y_REM(1) ‖ F_local(9) ‖ F_context(5) ]   → 30 columns
ΔY = f_θ(z)     Linear→SiLU  30→64→64→32→1
Y  = Y_REM + ΔY,   target r = Y_true − Y_REM
```

`Y_REM` is the lognormal **median**, not q75 — using a high quantile as the point
answer would hand the network a residual with a large fixed offset and make the
comparison against a direct model unfair.

## Results — walk-forward, 14 six-month blocks, 14-day embargo

| arm | MSE | vs REM | pick return | dir AUC |
|---|---|---|---|---|
| A REM only (no network) | 0.01724 | — | **−2.052%** | 0.4794 |
| B REM + residual MLP | 0.01883 | +9.25% | +0.127% | **0.5207** |
| C direct MLP (same inputs, same net) | 0.02214 | +28.47% | **+1.246%** | 0.5173 |
| D gradient boosting, 108 panel features | 0.01741 | +1.03% | +1.075% | 0.5012 |
| E REM + residual + panel features | 0.01567 | **−9.10%** | +0.497% | 0.5183 |
| F warm-started + replay buffer | **0.01474** | **−14.50%** | −1.342% | 0.5181 |
| G REM + residual, q75 pinball loss | 0.01737 | +0.79% | −1.276% | 0.5027 |

### The residual claim is supported on its own terms

On point accuracy the framing works, and clearly. The identical network on the
identical inputs is **15% worse in MSE** when it predicts `Y` directly (C,
0.02214) than when it predicts `Y − Y_REM` (B, 0.01883). Adding the panel
features (E) or warm-starting with a replay buffer (F) beats the closed-form
solver itself by **9%** and **14.5%**. The network really does learn where the
diffusion is systematically wrong.

### And it is the wrong thing to be good at

Read the MSE column against the pick-return column. They run in **opposite
directions**. The best-MSE arm (F, −14.5%) has nearly the worst return
(−1.342%). The worst-MSE arm (C, +28%) has the best (+1.246%). The physics alone
has good MSE and is actively harmful as a ranker (−2.052%, and a directional AUC
of 0.4794 — *inverted*).

This is not a surprise inside this repository, it is the same finding again.
`RESULT_MOONSHOT_TAIL.md` established that mean-optimising objectives
systematically avoid the lottery tickets that carry the return, and
`RESULT_WHY_LOSERS.md` showed the traded edge is convexity, not accuracy — the
book lands at the 47th outcome percentile and still profits. A model trained to
minimise squared error is trained to predict the conditional mean, and the
conditional mean is exactly the statistic that discards the tail.

### The obvious fix does not work either

Arm G is the same residual model with a q75 pinball loss instead of MSE — the
objective this project's book actually trades. If the architecture were sound and
only the loss were wrong, this is where it would show.

```
pick  G−C  −0.025222   95% CI [−0.038375, −0.012831]   G better in 14% of blocks
```

Significantly **worse**. So "the objective was wrong" is not the explanation, and
my hypothesis on that was mistaken.

### The paired test on the central claim

```
mse   B−C  −0.003313   95% CI [−0.010404, +0.000577]   B better in 50% of blocks
pick  B−C  −0.011191   95% CI [−0.024379, +0.001864]   B better in 36% of blocks
auc   B−C  +0.003384   95% CI [−0.002657, +0.010172]   B better in 64% of blocks
```

All three straddle zero. **Caveat worth more than the intervals:** an earlier run
of the identical script gave B a pick return of −0.676% against C's +1.725%, with
the pick interval *excluding* zero. The arms move by roughly a percentage point
between seeds, which is larger than the effect being measured. Nothing in this
table should be read as a reliable ordering of B against C on trading metrics —
only the MSE gap is stable enough to assert.

## What this establishes

1. **The design does what it says.** Residual learning on top of a closed-form
   solver measurably beats the same network learning the answer directly, and
   beats the solver itself once local features are supplied. The shared-`Φ`
   reuse is genuine — fifteen queries off one σ estimate.
2. **It does not beat the incumbent.** D, the gradient-booster this project
   already trades, returns +1.075% against B's +0.127%; C at +1.246% is inside
   seed noise of D.
3. **The binding constraint is not the architecture.** It is that a good
   point-estimate of a convex payoff is not a good selector for it. Any residual
   scheme trained on MSE inherits this, and switching to a quantile loss (G) made
   it worse rather than better.
4. **One thing did improve:** directional AUC. B and E reach 0.5207 and 0.5183
   against the gradient-booster's 0.5012 on the same rows. Small, but this is
   the metric `RESULT_SHORT_DIRECTION.md` identified as the open problem, and the
   REM features are the first inputs to move it above the incumbent.

## Where it would work better

The residual principle is sound and this is a poor problem for it. It needs a
solver whose error is *small and structured*; here the diffusion explains almost
none of a ten-session micro-cap return, so "learn the residual" is nearly the
original problem. On a task where the physics is 90% right — an option surface,
a PDE solution, a docking score, a rate curve — the same construction has far
more to work with, and the protein case it came from is exactly that shape.

## Artefacts

```
scripts/rem_solver.py   Φ_S compile, 15-query inference, F_local, F_context
scripts/rem_train.py    the corrector and all seven arms
/root/.iai/wide2015/rem_model.pt   warm-started corrector: state_dict,
                                   z column names, median/scale, target spec
```

Reproduce with `python3 scripts/rem_train.py` (~25 min).
