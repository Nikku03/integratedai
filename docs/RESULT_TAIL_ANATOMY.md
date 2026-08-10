# Anatomy of the +50% and +100% touches

I flagged the earlier numbers as suspicious — a mean realised return of +44.94%
conditional on a +50% touch implies almost no give-back, which is not how small-
cap spikes usually behave. Taking them apart, **the suspicion was wrong on the
main point and right on a smaller one.**

## The moves are genuinely sticky

Whole universe, ten-session window, realised close-to-open return:

| touched | n | mean | **median** | p25 | p75 | p90 | closed negative |
|---|---|---|---|---|---|---|---|
| 20-35% | 23,587 | +14.16% | +16.95% | +9.45% | +21.43% | +25.49% | 10.3% |
| 35-50% | 5,921 | +23.14% | +27.42% | +15.79% | +34.52% | +39.44% | 9.3% |
| 50-100% | 3,732 | +35.52% | +39.87% | +21.24% | +51.87% | +63.05% | 8.4% |
| 100%+ | 1,061 | +78.07% | +74.06% | +41.12% | +107.64% | +153.11% | 7.5% |
| **>=50% (cumulative)** | **4,793** | **+44.94%** | **+43.66%** | +23.60% | +58.82% | +85.59% | **8.2%** |
| **>=100% (cumulative)** | **1,061** | **+78.07%** | **+74.06%** | +41.12% | +107.64% | +153.11% | **7.5%** |

**The median sits on top of the mean in every bucket.** These are not a handful
of 300% outliers dragging an average — the typical +50% toucher really does end
the window around +44%, and only 8.2% finish below entry. That refutes the
"a few enormous winners" explanation outright.

## Capture, and the one thing that is an artifact

| touched | median capture | mean capture | closed below entry | **median session of the peak** |
|---|---|---|---|---|
| >=20% | 67.6% | 55.2% | 9.8% | 8 |
| >=35% | 64.7% | 54.8% | 8.8% | 8 |
| >=50% | 59.9% | 52.8% | 8.2% | 8 |
| >=100% | 49.6% | 47.8% | 7.5% | 7 |

Capture is realised ÷ available. Holding to day 10 keeps about 60% of a +50%
move and half of a +100% move.

**The peak lands on session 8 of 10.** That is the artifact I suspected: the
window closes two sessions after the typical high, so there is very little time
for give-back to be measured. A longer hold would show worse capture. The stated
returns are correct *for a ten-session hold* and should not be extrapolated.

## What this looks like as a book — and this is the part that matters

q75 model, one pick a day, 1,759 trades, 2019-2025:

```
mean +1.349%        median -1.800%        win rate 45.5%
```

**The median trade loses 1.8%.** Everything is in the tail:

| bucket | n | share of book | mean | % closing negative | contribution |
|---|---|---|---|---|---|
| touched 100%+ | 40 | 2.27% | +89.30% | 5.0% | +2.03pp |
| touched 50-100% | 109 | 6.20% | +40.16% | 7.3% | +2.49pp |
| touched 20-50% | 423 | 24.05% | +12.66% | 19.9% | +3.04pp |
| **touched <20%** | **1,187** | **67.48%** | **−9.21%** | **72.8%** | **−6.21pp** |

Two-thirds of every trade you place loses an average of 9.21%.

**Where the P&L comes from:**

- 40 trades (**2.27%** of the book) contribute **150.5%** of total profit
- 149 trades (8.47%) contribute **335.0%**
- the other 1,187 trades contribute **−460.6%**

Strip out the picks that touched +50% and the strategy returns **−3.464% per
trade**. Strip out only the 40 that touched +100% and it returns **−0.697%**.

**The entire result is forty trades out of one thousand seven hundred and
fifty-nine.**

## The waiting

| | count | median gap | p90 | **worst gap** |
|---|---|---|---|---|
| +50% touch | 149 | 7 trades (0.3 mo) | 26 | **95 trades (4.5 months)** |
| +100% touch | 40 | 31 trades (1.5 mo) | 85 | **290 trades (13.8 months)** |

Four and a half months without a +50%, nearly fourteen without a double, while
two-thirds of your positions bleed 9% each.

## The equity curve

Ten equal slots, one new position a day, 2019-01 to 2025-12:

```
final 6.11x        +29.5% a year
MAX DRAWDOWN       -57.7%
longest underwater 495 trades, about 23.6 months
monthly            mean +3.49%   median +1.34%   worst -27.18%   best +58.97%
                   44% of months negative
```

A 58% drawdown and nearly two years underwater, to earn 29.5% a year.

## Fragility, which is the reason to be careful

Because forty trades carry everything, the result is extremely sensitive to
whether those forty are real. The panel has **zero delistings** and a measured
missing mass of at least 11.8%, so some of this tail belongs to names that a
real universe would have shown failing.

Replacing a fraction of the +50% winners with a −10% loss instead:

| winners removed | final equity | max drawdown | mean per trade |
|---|---|---|---|
| 0% (as measured) | **6.11x** | −58% | +1.349% |
| **25%** | **0.55x** | −69% | **−0.069%** |
| 50% | 0.06x | −95% | −1.389% |

**Losing a quarter of the winners turns 6.1x into losing half your money.** Not
a reduced edge — a reversed one. That is what a strategy resting on 2.27% of its
trades looks like when the 2.27% is measured on a survivorship-broken panel.

## What to take from this

The +50% and +100% numbers are real, well-behaved, and not outlier artifacts —
median tracks mean, fewer than one in ten close below entry, and you keep 50-60%
of the move on a ten-session hold. The model finds them at 8.9x the base rate.

But as a book it is a lottery with a positive expectation on this panel, and the
expectation lives entirely in forty trades. Before sizing anything to it, the
question worth answering is not "does the edge exist" but "how much of the tail
survives a universe that includes the companies that died" — because at a 25%
haircut it does not survive at all.
