# The agreed strategy, priced as a book

Everything so far has been quoted per trade. That is the right unit for testing
a signal and the wrong one for answering "what would I have made". This runs
only the rules that passed a pre-registered test, as an actual book with an
actual equity curve, over **2019-01-02 to 2025-12-30 — 7.0 years**.

## The rules

Buy at the next open, hold ten sessions, sell at the close. No stops, no
targets, no trails — all seventeen exit rules lost to holding. Long only. `k`
new names a session, so `10k` positions overlap and each takes `1/(10k)` of
equity. 20bps round trip. Cash drag left in: on days when fewer than `k` names
clear, the book is not fully invested and is not pretended to be.

Selection is a q75 quantile objective, walk-forward in six-month blocks with a
fourteen-day embargo, scoring ~199 candidates a session.

## What it returns

| book | trades | /mo | per trade | win | P(+20%) | **total ROI** | **CAGR** | **maxDD** | vol | Sharpe |
|---|---|---|---|---|---|---|---|---|---|---|
| k=1, 3.02 veto | 1,759 | 21 | +1.004% | 44.9% | 15.5% | **+107.3%** | +11.0% | −77.7% | 61.5% | 0.48 |
| k=1, no veto | 1,759 | 21 | +1.001% | 45.1% | 15.5% | +109.1% | +11.1% | −68.1% | 63.2% | 0.48 |
| k=2, 3.02 veto | 3,518 | 42 | +0.913% | 45.1% | 15.3% | +118.6% | +11.8% | −75.7% | 53.8% | 0.48 |
| k=3, 3.02 veto | 5,277 | 63 | +0.775% | 45.1% | 14.6% | +106.0% | +10.9% | −73.4% | 51.0% | 0.46 |
| **k=5, 3.02 veto** | **8,795** | **105** | **+1.115%** | 46.2% | 14.1% | **+292.7%** | **+21.6%** | **−71.3%** | 47.8% | **0.65** |
| k=5, no veto | 8,795 | 105 | +0.878% | 45.5% | 14.2% | +161.2% | +14.7% | −68.2% | 48.7% | 0.53 |

Against no skill, same accounting:

| | total ROI |
|---|---|
| own the whole pool equally | **−6.0%** |
| random 5 names a day (40 draws) | **+11.3%** median, 5–95% [−12.7%, +62.6%] |
| the model's k=5 book | **+292.7%** — 0 of 40 random draws beat it |

**The selection is doing real work on this data.** That is the honest positive
finding and it is not small: the pool itself lost money over the period.

## Year by year, k=1

| | | |
|---|---|---|
| 2019 | **+67.4%** | 252 trades |
| 2020 | −21.1% | 253 |
| 2021 | +7.1% | 252 |
| 2022 | **−46.6%** | 251 |
| 2023 | +54.0% | 250 |
| 2024 | **+101.3%** | 252 |
| 2025 | −11.4% | 249 |

Three losing years in seven, one of them −46.6%, and a −71% to −78% peak-to-
trough depending on `k`. Nobody holds through that.

## What the trades actually are

Most recent twelve, k=1:

```
2025-12-12  ABTC   +1.49%      2025-12-22  UP      +3.93%
2025-12-15  VOR    -5.06%      2025-12-23  SUPX   -14.70%
2025-12-16  MARA  -16.90%      2025-12-24  SIDU    +4.47%
2025-12-17  DFDV   -1.37%      2025-12-26  SOC     +8.61%
2025-12-18  RZLT  +21.45%      2025-12-29  ABTC    -4.69%
2025-12-19  INHD  -37.56%      2025-12-30  KSCP    -0.20%
```

The ten that carried the whole book: UP +186.8%, AMTX +135.4%, LXRX +133.0%,
BTDR +127.6%, BKKT +125.0%, CDLX +123.7%, OCEA +118.2%, LTBR +115.3%, LAES
+109.0%, QUBT +104.2%.

**Note what these are.** MARA, BTDR, BKKT, QUBT, LAES, DFDV — crypto miners,
quantum and treasury-company meme names. The ten worst are led by KOS, SM,
PTEN, FLR and GIII, all bought in the last week of February and first week of
March 2020. This is not a biotech catalyst strategy. It is a high-volatility
lottery selector run over the whole universe, and it loads into high beta going
into a crash. The filing and catalyst work sits on a biotech subset that this
book barely touches.

One trade prints **−100.16%**, which is impossible and is an unadjusted-price
artifact that the `|r| ≤ 3` guard lets through. It is one of 1,759 and does not
move the totals, but it is a reminder that the price panel is not clean.

## The two numbers that decide whether any of this is real

**Fragility.** The mean is a tail, not a central tendency:

| | mean per trade |
|---|---|
| as measured | +1.004% |
| drop the best 1% of trades (18 of 1,759) | **−0.128%** |
| drop the best 2% (35 trades) | −0.848% |
| haircut every winner by 25% | −1.215% |

The top 10 trades carry **72.4%** of the total per-trade sum; the top 20 carry
122%, meaning everything outside the top twenty is collectively negative.
Eighteen trades in seven years are the strategy.

**Survivorship.** Not one of 3,662 tickers in this panel delisted in eleven
years. EDGAR carries 8,297 real deaths over the same span, and the measured
floor on missing mass is 11.8%. The names that went to zero are absent, and a
high-volatility micro-cap lottery selector buys precisely that population.

Mix in a fraction `f` of trades that actually went to −100%:

| book | per trade | breaks even at |
|---|---|---|
| k=1 | +1.004% | f = **0.99%** — one hidden zero per 101 trades |
| k=2 | +0.913% | f = 0.90% — one per 111 |
| k=3 | +0.775% | f = 0.77% — one per 130 |
| k=5 | +1.115% | f = **1.10%** — one per 91 |

**One undetected total loss in every hundred trades erases the entire edge.**
At 105 trades a month that is one per month. The panel says the rate is zero.
The rate is not zero.

## The verdict

The +292.7% is a real computation on a panel that cannot support it. Three
things are simultaneously true:

1. The selection beats random and beats owning the pool, decisively, and that
   is not explained by luck — 0 of 40 random draws came close.
2. The result lives entirely in ~18 trades, and a quarter-haircut on winners
   turns it negative.
3. The survivorship gap is roughly an order of magnitude larger than the edge
   it would have to survive.

So the answer to "what would the ROI have been" is **+107% to +293% over seven
years, at a 71–78% drawdown, and inside an error bar wide enough to contain
zero.** It is not a number to size a position on. What it is good for is
direction: the ranking works, the convexity is real, and the next thing worth
building is the delisting-corrected panel — because until the dead names are
back in, every figure in this document is an upper bound of unknown tightness.

## Reproducing

```
python3 scripts/agreed_strategy.py            # ~15 min, writes agreed_trades.parquet
```

The per-trade return is cross-checked against `exit_rules.walk` on 3,000 random
trades and asserted to agree to 1e-6. It did not, the first time: marking out at
the first missing bar instead of the last bar that actually traded differed by
up to 2.05e-02 on illiquid names, which are exactly the ones that matter. The
assertion is in the script so that cannot pass silently again.
