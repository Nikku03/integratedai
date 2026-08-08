# Twenty trades a month

Twenty a month is one trade per trading day. The question is not whether the
model can produce one pick a day — it always can — but what that costs, and how
many slots it ties up.

Three quantities are one constraint, not three choices:

```
trades per month  x  hold length / 21  =  slots open at once
```

Twenty a month at a ten-session hold needs ten slots. Wanting fewer slots means
shortening the hold, and the hold turns out to be the whole strategy.

## The horizon decides everything

One pick per day, walk-forward, 14 blocks, long only, net of 20bps:

| hold | slots | return/trade | excess | IR | blocks won | win% | **book/month** |
|---|---|---|---|---|---|---|---|
| **3 sessions** | 3.0 | **−0.169%** | −0.190% | −0.33 | 6/14 | 47.9% | **−1.18%** |
| **5 sessions** | 5.0 | +0.465% | +0.367% | 0.51 | 8/14 | 50.3% | +1.97% |
| **10 sessions** | 10.0 | **+1.699%** | **+1.450%** | **0.94** | **11/14** | 54.2% | **+3.60%** |

**At three sessions the edge is negative.** Not small — negative, in 8 of 14
blocks. At five it is roughly a quarter of the ten-session edge. The model was
retrained on each horizon, so this is not a ten-day model exited early; it is
the honest statement that whatever this signal is, it takes about two weeks to
pay out.

That kills the appealing compromise. Twenty trades a month on three or four
slots does not work, because the only way to get there is a short hold.

## Concentration: more per trade, less reliably

At the ten-session horizon:

| picks/day | trades/mo | slots | excess | IR | blocks won | book/month |
|---|---|---|---|---|---|---|
| **1** | **21** | **10** | **+1.450%** | 0.94 | 11/14 | **+3.60%** |
| 2 | 42 | 20 | +1.041% | 0.92 | 11/14 | +2.73% |
| 5 | 105 | 50 | +0.894% | **1.22** | **13/14** | +2.41% |

Taking only the single best name earns **62% more per trade** than taking five,
which is what a ranking model should do if the ranking means anything. It also
gives up consistency: information ratio 0.94 against 1.22, and two more losing
half-years. With ten positions instead of fifty there is far less to average
away a bad pick.

Both are defensible. One pick a day is the higher-return, lumpier book; five is
the steadier one. At twenty trades a month the choice is already made.

## The gate does nothing, and that is worth recording

Three variants were run: take the daily best unconditionally, or only if its
score clears the 50th or 80th percentile of the *training* prediction
distribution. All three produce identical results to three decimal places.

The reason is structural: the best of roughly fifty candidates is essentially
always a high-scoring name, so a threshold set anywhere below the top percentile
never binds. "Only trade when the model is confident" is not implementable this
way — a gate would have to sit at p99 or above to skip any days at all, and at
that point it is choosing the days, not the names.

## What the book looks like

**Twenty trades a month, ten-session holds, ten slots, one new position per day
and one exit per day once the pipeline fills.**

- +1.699% per trade net of 20bps, against a universe doing +0.249%
- +3.60% a month compounding, if every slot stays occupied
- 54.2% of trades profitable
- picks have a median 2.52% daily volatility — around 40% annualised, small-cap
  but nothing like the 211% the old magnitude model was selecting
- eleven of fourteen half-year blocks beat the universe

## Read this before believing the monthly number

**+3.60% a month is ~53% a year, and it is measured on a panel with no
delistings.** That is not a forecast. The excess over the universe, +1.450% per
ten sessions, is the more defensible number because the benchmark carries the
same bias, but even that is overstated if the strategy picks names likelier to
delist than average.

**Three of fourteen blocks lost.** On ten slots, a bad half-year is felt.

**Capacity is small.** Median pick around $8-11 with single-digit-million daily
volume. One position a day is fine for a personal account and will not scale.

**Costs are assumed at 20bps round trip.** Each additional 10bps takes about
0.10% off the per-trade number — material against +1.699%, and real spreads on
the smaller names will exceed the assumption.
