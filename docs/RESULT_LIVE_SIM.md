# The simulation, run as if live

Pick which 8-K filings to trade, enter one minute after EDGAR accepts them, target
twenty trades, July 2026. Every decision uses only what existed at that moment.

## The three causal commitments

**Selection is an expanding window.** Each filing is ranked against the pre-event
volatility of filings *already seen this month*, never the finished month's
distribution. The first 20 filings build the distribution and are not traded.

**Entry is a genuine one-minute fill.** The order goes in at acceptance + 1 minute
and must find a print within three minutes or the filing is declined. Letting the
order rest into the next session is a *different strategy* — it turns a
one-minute trade into a next-open trade — so it is refused rather than silently
relabelled. Realised median lag: **2 minutes, 86% inside two minutes.**

**Exit reads bars in order.** Barriers checked bar by bar after the entry bar,
ambiguous bars resolve against the trade, stops fill at `min(level, bar_low)`,
and a zero-volume bar can neither trigger an exit nor supply an exit price.

## The funnel

| stage | count |
|---|---|
| 8-K filings, 1–29 July | **2,422** |
| screened out (Item 3.01/3.02, sub-$1, illiquid) | 201 |
| **no print within 3 minutes** | **2,141 (88%)** |
| no free slot | 38 |
| **traded** | **22** |

**Eighty-eight percent of filings cannot be traded on a one-minute rule at all**,
because the tape is not running. That is the strategy's real constraint and it is
not fixable by better selection.

## The trades

$80, three slots, 6% target, 10% stop, one session maximum hold.

| ticker | items | public ET | fill ET | lag | entry | exit ET | exit | why | ret | balance |
|---|---|---|---|---|---|---|---|---|---|---|
| BDN | 2.01,9.01 | 07-10 15:17 | 15:19 | 1.0m | 3.06 | 07-13 15:43 | 3.18 | time | +4.26% | 81.13 |
| TREX | 7.01 | 07-14 10:00 | 10:02 | 1.8m | 46.00 | 07-14 16:00 | 44.17 | time | −3.98% | 80.06 |
| WINA | 2.02,7.01,8.01 | 07-15 11:29 | 11:31 | 1.1m | 367.33 | 07-16 09:38 | 389.37 | **target** | **+6.00%** | 81.66 |
| DFNS | 3.03,5.03,9.01 | 07-16 10:05 | 10:07 | 1.6m | 8.19 | 07-16 10:23 | 7.34 | **stop** | **−10.38%** | 78.83 |
| SRXH | 7.01,9.01 | 07-15 15:45 | 15:47 | 1.8m | 2.25 | 07-16 10:29 | 2.18 | time | −2.89% | 78.06 |
| BNAI | 5.02,9.01 | 07-17 12:10 | 12:12 | 1.8m | 11.75 | 07-20 13:25 | 10.55 | **stop** | **−10.21%** | 75.41 |
| WAFD | 2.02,9.01 | 07-17 13:03 | 13:06 | 2.6m | 38.17 | 07-20 14:05 | 37.15 | time | −2.67% | 74.71 |
| RTB | 8.01,9.01 | 07-17 14:03 | 14:06 | 2.5m | 17.30 | 07-20 14:43 | 15.38 | **stop** | **−11.10%** | 71.82 |
| STLD | 2.02,9.01 | 07-21 09:42 | 09:44 | 1.7m | 233.80 | 07-22 10:11 | 239.44 | time | +2.41% | 72.40 |
| TEX | 8.01,9.01 | 07-21 10:09 | 10:11 | 1.8m | 64.01 | 07-22 10:29 | 66.56 | time | +3.98% | 73.35 |
| FUL | 1.01,1.02,2.03 | 07-20 15:15 | 15:17 | 1.4m | 55.83 | 07-22 12:21 | 56.22 | time | +0.70% | 73.52 |
| RRC | 2.02,9.01 | 07-22 11:00 | 11:02 | 1.7m | 38.83 | 07-23 10:05 | 39.30 | time | +1.21% | 73.81 |
| POOL | 2.02,7.01,9.01 | 07-23 09:29 | 09:31 | 1.5m | 200.29 | 07-24 09:38 | 183.26 | time | −8.50% | 71.73 |
| GRC | 2.02,9.01 | 07-24 09:39 | 09:41 | 2.0m | 76.96 | 07-24 12:34 | 81.57 | **target** | **+6.00%** | 73.17 |
| SLG | 2.02,7.01,9.01 | 07-23 13:45 | 13:47 | 1.6m | 52.92 | 07-24 13:35 | 55.15 | time | +4.21% | 74.20 |
| FJET | 4.01,7.01,9.01 | 07-24 13:50 | 13:52 | 1.2m | 3.49 | 07-27 09:38 | 3.70 | **target** | **+6.00%** | 75.69 |
| CHCO | 2.02,9.01 | 07-22 11:16 | 11:18 | 2.0m | 137.84 | 07-27 11:18 | 142.05 | time | +3.05% | 76.43 |
| CBRL | 5.02,7.01,9.01 | 07-27 09:49 | 09:51 | 2.0m | 52.94 | 07-28 09:38 | 53.13 | time | +0.36% | 76.52 |
| CARE | 7.01,9.01 | 07-27 11:24 | 11:26 | 1.7m | 34.33 | 07-28 15:25 | 34.39 | time | +0.17% | 76.57 |
| NGS | 1.01,3.03,5.03 | 07-24 15:03 | 15:05 | 1.3m | 36.15 | 07-29 09:34 | 36.09 | time | −0.15% | 76.53 |
| WAFD | 7.01,9.01 | 07-28 15:33 | 15:36 | 2.5m | 36.73 | 07-29 15:16 | 36.65 | time | −0.20% | 76.48 |
| TMP | 7.01,9.01 | 07-28 09:55 | 09:57 | 1.4m | 100.12 | 07-30 11:10 | 99.98 | time | −0.14% | 76.44 |

| | |
|---|---|
| **start** | **$80.00** |
| **end** | **$76.44** |
| **ROI** | **−4.45%** |
| trades | 22 |
| mean | −0.54% |
| **median** | **+0.27%** |
| win rate | **55%** |
| t | −0.47 |
| max drawdown | −12.2% |
| exits | 16 time, 3 target, 3 stop |

## The selection adds nothing

Random selection from the identical eligible pool, 150 draws:

| | trades | end | ROI | mean/trade |
|---|---|---|---|---|
| **model** (volatility rank) | 22 | $76.44 | −4.45% | −0.540% |
| **random** | 15.0 | $76.70 | −4.13% | −0.806% |
| | | | **p(random ≥ model) = 0.52** | **0.44** |

The volatility selector is indistinguishable from a coin. Worse, tightening it
actively hurts: at the 50th percentile the month returns −7.39%, at the 70th
−17.98%. **Pre-event volatility predicts the size of the move, not its sign**,
and when you buy the offer and sell the bid, size without direction is pure cost.

## The loss is the barrier geometry, not the picks

The median trade is a small **winner** (+0.27%) and 55% win. The mean is negative
because of three stops at −10.2%, −10.4% and −11.1% against targets capped at
+6.0%.

With a 6% target and 10% stop you need **63% wins to break even.** We got 55%.

| target / stop | trades | end | ROI |
|---|---|---|---|
| 6% / 10% | 22 | $76.44 | −4.45% |
| 6% / 6% | 23 | $77.61 | −2.99% |
| 4% / 4% | 25 | $76.61 | −4.23% |
| 10% / 10% | 19 | $72.58 | −9.27% |
| **8% / 5%** | 22 | **$78.42** | **−1.98%** |

Symmetric or favourable geometry loses less. **Nothing crosses zero.** These were
chosen after seeing the result, so the best cell is not a finding — the useful
part is that the whole surface sits between −1.98% and −9.27%.

## What this run settles

**Twenty trades a month is achievable on a strict one-minute rule** — 22 here,
with a real median fill lag of two minutes. The trade count was never the problem.

**It costs 4.45% a month to do it.** Not significantly (t=−0.47, n=22, one
month), but every configuration tried is negative and the honest reading of a
month this size is "no edge detected", not "small edge".

**The pool is 12% of filings.** 2,141 of 2,422 filings never print inside three
minutes. Any one-minute strategy is confined to the fraction that lands while the
market is open, and that fraction is not where the moonshots are — the move
census found zero of 59 8-K-driven 20%+ movers survived this screen.

**And selection does not help.** A volatility ranker, which is the best ex-ante
tail predictor this project found, performs no better than random draws from the
same pool and gets worse the harder it is applied.
