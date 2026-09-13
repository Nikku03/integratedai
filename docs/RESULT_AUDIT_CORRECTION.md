# Correction: the premise under the options work was wrong

An adversarial audit of every load-bearing claim in the options research. Four of
five failed. The errors are of **comparison and transmission**, not of foresight
leakage — the point-in-time discipline holds and was re-verified. Every number
below was reproduced independently before this was written.

## 1. "Options are systematically overpriced" — withdrawn

Stated as: *13.7% charged against 9.9% delivered over 2,842 releases, 30 of 30
names above their own gap history.* Wrong three separate ways.

**The horizon does not match.** `options_straddle_report.py:79-81` computes
`breakeven = (call + put) / spot` — the price of a contract with **2 to 10 days**
of remaining life — and compares it to `gap = exit_open / entry_close − 1`, a
single **overnight**. A correctly priced option must show implied-to-expiry above
a one-night move. The comparison detects the passage of time, not mispricing.

The signature is in the data: premium scales with days to expiry
(`corr = +0.448`) while the "delivered" quantity does not (`corr = +0.141`).

**Corrected on a matched horizon, the sign reverses.** At the exit open the jump
has already happened and been paid, so straddle value less intrinsic is the
non-event residual — no square-root-of-time assumption, so no diffusing a
discrete jump. It averages **5.82% of spot, 42% of the premium**:

| | implied | delivered | edge |
|---|---|---|---|
| as published (to expiry vs one night) | 13.71% | 9.95% | **−3.76pp** against the buyer |
| matched to the event night | 7.89% | 9.95% | **+2.05pp** for the buyer |

The arithmetic closes exactly: −3.76 + 5.82 = +2.06.

**The same 16 straddles, actually bought and sold, returned +5.66%.** A real
3.8-point overcharge on a 13.7% premium implies about −27%. The buyer made money.
That number sits in the same table as the claim it refutes.

**n = 16, not 2,842.** `gaps.parquet` is `(2842, 4)` — `ticker, gap, close,
dvol` — with **no option price column**. No premium can come from it. Its own
mean |gap| is 6.13%, not 9.9%. `credit_spread.py` asserts both figures as the
same 2,842-release mean, fifteen lines apart in one docstring.

**The interval was dropped in transmission.** `RESULT_EARNINGS_STRADDLE.md`
reports −3.8pp with a 95% interval of **[−8.0, +1.1]** and says in its own text
that it spans zero. Downstream, `credit_spread.py` and `PREREG_VERTICAL.md`
restate the point estimate as established fact over 2,842 releases, without it.

**Honest reading.** Held to expiry on those 16: buyer −2.5%, seller −2.6% on
margin, 62.5% seller win rate, P(mean ≤ 0) = 0.38. Positive median, zero mean.
That is what a **correctly priced** earnings option looks like. Not rich, not
cheap — approximately fair, and unresolvable at this sample size.

## 2. The deduction chain built on it — withdrawn

> overpriced → therefore sell → therefore sell with defined risk

Every link after the first inherits the reversed premise. With it gone there is
no argument left for expressing this view in options at all. The horizon artifact
that voids the overpricing finding is the *same* defect that voids the trades:
**the instrument prices 2–10 days and the trade holds one night.** The trader
buys five days of volatility and uses one.

## 3. `RESULT_VERTICAL.md`'s headline — qualified

The line *"the required win rate (61%) equals the signal's win rate (61.9%)"*
compares two different events. 61% is the break-even for a binary paying 0.64 and
losing 1.00. 61.9% is P(gap sign matches). A short call spread also wins on flat
and slightly-adverse moves, so its win probability should **exceed** the
directional accuracy. The equality is rhetorical, not arithmetic.

The conditional-means version (needs 65.3%, got 66.7%) is the right shape but
rests on nine trades: a drop-one jackknife swings the requirement from **45.4% to
71.6%** and flips the verdict on 4 of 9 drops. Treat that section as
illustrative. The **net −18.0%** and the negative break-even half-spread stand.

## 4. Two findings that were computed and never reported

**The edge dies at the opening print.** `q1_gaps.parquet` carries a `day_ret`
column — exit close over exit open. No script reads it and no document mentions
it. The identical reversal rule applied to it gives **49.15%** on the same 118
events, against 61.86% on the overnight gap. The edge lives in one print and
nothing adjacent to it.

**The sign edge is significant; the dollar edge is not.**

| | value |
|---|---|
| sign accuracy | 73/118 = 61.9%, binomial P = **0.0063** |
| mean signed return per event | +1.376% (median +1.492%) |
| day-clustered 95% CI | **[−0.59, +2.88]%** |
| P(mean ≤ 0) | **0.071** |

The gap between P = 0.006 and P = 0.071 is the whole live question, and no
document reported the second number.

## 5. Unverified claims — no producing code found

* "~8.7% of premium bled per quiet session" — load-bearing for the opening
  deduction that the event must be scheduled.
* "+4.3% SPY tape" — one of the two checks the Q1 result claims to pass. Zero
  grep hits for SPY anywhere in `scripts/`.
* The funnel counts 7,833 / 2,949 / 1,492 / 187, and "182 names over 20 sessions".
* Which estimator produced P = 0.007. The 61.9% is a hardcoded literal at
  `q1_sel_report.py:90`; the value is correct, its provenance does not exist.

## What survives

* **The reversal signal.** 73/118 = 61.9%, binomial P = 0.0063, day-clustered CI
  [53.0, 69.4]. Bucket table exact: run-up (n=95) gaps up 37.9%; flat (n=69)
  52.2%; run-down (n=23) 65.2%. **Sound.**
* **Gap magnitudes**, on the only large sample: 2,842 releases, mean |gap| 6.13%,
  median 3.64%, 18.1% above 10%, max 132.6%. In own-volatility units, mean 1.61
  daily sigma.
* **The point-in-time discipline.** Re-verified: `implied_vs_history.py:104`
  excludes the traded event's own gap; `legs_for()` correctly refuses intraday
  releases; the pre-registrations were committed before their windows were
  assembled.
* **Every "net of costs" conclusion**, which never depended on the premise.

## Measurement floor under all of it

Every option price in this repository is a **single trade print at an unknown
time of day** — not a quote, not a mid. Polygon's free tier returns 403 on NBBO.
On one exit session the thinnest legs printed once, one contract. This is why the
break-even half-spread, and not the return, is the only quantity worth quoting
from any options study here.
