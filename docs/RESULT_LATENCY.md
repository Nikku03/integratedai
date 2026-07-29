# Result: the latency window is not tradable

Tests the proposition that official paperwork is public before the crowd
notices, so a scraper watching EDGAR can position ahead of them — not to beat
institutions to the microsecond, but to get filled into normal liquidity
instead of chasing a gap.

Measured on **1,203 8-K filings across 497 names over 28 days**, using exact
EDGAR `acceptanceDateTime` values and real 1-minute bars including pre- and
post-market.

## It fails on liquidity, before information is even reached

| session | filings | share | fillable at T+1min |
|---|---|---|---|
| after-hours | 718 | 60% | **5.8%** |
| pre-market | 365 | 30% | 15.9% |
| **regular hours** | **99** | **8%** | **93.9%** |
| closed | 21 | 2% | 9.5% |

**Overall: 16.2% fillable.** Five filings in six cannot be traded a minute
later at any price, because at that moment there is no trade — not a wide
spread, no print at all.

This is the whole argument's foundation and it does not hold. You cannot be
early to a market that is not running, and **92% of filings arrive when it is
not running.**

## The one-minute reaction is fictional

Median entry lag: **29.3 minutes.** 90th percentile: **1,052 minutes**, which
is 17.5 hours.

The lag is not scraper speed — it is waiting for a market. An 8-K accepted at
18:40 ET cannot be acted on until the next session regardless of how fast the
scraper is. Speed of detection is not the binding constraint; the exchange
calendar is.

## Where you can trade, there is nothing to capture

Entering at T+1min, holding to each horizon:

| horizon | mean | median | win% | t | **realistic fill** |
|---|---|---|---|---|---|
| 5m | −0.06% | 0.00% | 14.9% | −1.08 | **−0.92%** |
| 15m | −0.22% | 0.00% | 21.0% | −0.76 | **−1.09%** |
| 30m | −0.38% | 0.00% | 24.1% | −1.22 | **−1.22%** |
| 60m | −0.42% | 0.00% | 29.7% | −1.28 | **−1.16%** |
| 120m | −0.55% | 0.00% | 31.8% | −1.72 | **−1.21%** |

Regular hours only — the genuinely tradable 93 — is the same shape: −0.08% to
−0.84% at the close-to-close fill, **−0.55% to −1.31%** realistic.

"Realistic fill" buys at the entry minute's high and sells at the exit
minute's low: the worst prices that actually printed. Minute bars carry no
quotes, so the spread cannot be measured directly, but it can be bracketed,
and at this size the spread is the entire cost.

### On the zero medians

They are partly an artifact and the artifact is itself the finding. At 5
minutes, **69% of trades show exactly 0.00%** because nothing printed in
between — the close simply carries forward. That share falls to 31% by 120
minutes as trades trickle in.

So the median is not saying "the price held steady". It is saying "this name
does not trade". Which is the same problem as the fillability table, seen from
the other end: you are in a position you cannot exit.

**Among the filings whose price actually moved, the mean is negative at every
horizon** — −0.20% at 5 minutes to −0.80% at 120. When the price does move
after entry, it moves against you.

## Chasing is measurably the worst thing to do

Filings that had already moved ≥2% before entry (n=49) — the ones a headline
would have shown you:

| horizon | realistic fill |
|---|---|
| 5m | **−2.59%** |
| 15m | **−3.30%** |
| 30m | **−3.29%** |
| 120m | **−2.94%** |

Two to three percent lost, immediately, for arriving after the move. This is
the trap in its purest measurable form, and it is roughly three times worse
than the average filing.

## What this does and does not say

**It does not say the information is worthless.** 25% of fillable filings moved
≥2% before entry, so filings clearly do move prices. It says the move is over
before a one-minute reaction can act, and what remains is negative.

**It does not test a colocated system.** A firm reading the EDGAR feed in 50ms
during regular hours is playing a different game with different economics.
This measures what is left *after* they have acted, which is the relevant
question for anyone who is not them.

**It does not rule out the 8% that land in regular hours** as an object of
study — 93 events is a small sample, and the point estimates there are
negative but not significant (t between −0.71 and −1.30). What it rules out is
the *mechanism*: there is no interval during which the paperwork is public,
the price has not moved, and you can transact.

## The stronger versions of the thesis, and why they are worse

The natural objection is that 8-K is a bad test, because the company is both
filer and news source — the press release is filed as Exhibit 99.1, so filing
time *is* announcement time and no gap can exist. That is correct, and the
forms where the filer is a third party are the right test:

| form | filings (28d) | during regular hours |
|---|---|---|
| Form 4 (insider) | 5,880 | **16.6%** |
| SCHEDULE 13D + 13D/A | 164 | 14.1% |
| SCHEDULE 13G + 13G/A | 783 | 44.2% |

Form 4 is the case the argument most wants — the insider files it, no company
announces it. It is also **69% after-hours**, where 5.8% of these names are
fillable. And the intersection that actually matters is smaller still: of a
250-name sample, 397 Form 4s in 28 days yielded **38 during regular hours, of
which 4 were open-market purchases** — extrapolating to roughly 100 tradable
insider-buy events a month, at sizes like $10,743 and $17,300. An insider
buying seventeen thousand dollars of stock is not moving a small cap.

The forms that best fit the thesis are the ones filed most heavily into hours
when nothing trades.
