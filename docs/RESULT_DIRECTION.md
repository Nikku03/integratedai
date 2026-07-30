# Up 20% or down 20%: why, and can you tell in advance?

The move census only recorded the *largest up move* per name, so the "222 movers"
were winners by construction and every loser was invisible. Recomputing both tails
over 1–29 July, in the same tradable universe:

| direction | count |
|---|---|
| **up ≥20%** | **222** |
| **down ≥20%** | **293** |
| total | 515 |

**Down moves outnumber up moves 293 to 222.** That is 1.3:1 on names, and 2:1 when
measured per filing (below).

## Why each one happened — the causes barely differ

Filings in the seven days up to each move, up cohort vs down cohort:

| feature | in UP | in DOWN | lift | p (Fisher) |
|---|---|---|---|---|
| **has 8-K** | **35.8%** | **24.5%** | 1.46 | **0.0091** |
| **scheduled item** (2.02 earnings, 7.01 reg-FD) | **24.3%** | **15.5%** | 1.57 | **0.0156** |
| insider Form 4 | 24.8% | 21.1% | 1.17 | 0.38 |
| no filing at all | 39.4% | 42.3% | 0.93 | 0.58 |
| bullish item (1.01, 2.01, 8.01) | 14.7% | 14.0% | 1.05 | 0.90 |
| offering / dilution | 7.3% | 8.3% | 0.88 | 0.74 |
| activist 13D | 2.8% | 2.6% | 1.04 | 1.00 |
| merger / tender | 1.4% | 1.9% | 0.73 | 0.73 |
| **bearish item** (3.01 delist, 3.02 dilution, 4.02 restate) | **4.1%** | **4.2%** | **0.99** | **1.00** |

Only two of nine discriminate, both weakly. **Bearish item codes discriminate not
at all** — 4.1% of up-movers and 4.2% of down-movers carry one. The codes that
*mean* bad news are equally present in both tails.

## The tradable version, tested out of sample

Classifying known movers is not a strategy — it needs the move to have happened.
The forward question is: **of all filings, which are followed by +20% rather than
−20%?**

**7,218 filings** with ex-ante features and a forward five-session label:

| outcome | count | rate |
|---|---|---|
| reached +20% | 306 | 4.2% |
| **reached −20%** | **614** | **8.5%** |
| hit exactly one barrier | 826 | 31.4% up |

Rule fitted on **1–14 July**, scored on **15–29 July**. Nothing from the test half
touches the fit.

| | AUC |
|---|---|
| in-sample (1–14 July) | 0.6188 |
| **out-of-sample (15–29 July)** | **0.5428** |

**A coin flip.** Best single feature out of sample is `scheduled item` at 0.5513;
nothing reaches 0.56. Within volatility quintiles the AUC is 0.54–0.57.

## The reason no rule works: the ratio never changes

| cohort | n | −20% rate | +20% rate | **down:up ratio** |
|---|---|---|---|---|
| everything | 4,566 | 7.3% | 3.6% | **2.03** |
| model's bottom decile | 457 | 13.1% | 6.8% | **1.94** |
| simply the most volatile decile | 457 | **34.1%** | **16.6%** | **2.05** |

**The down:up ratio is 2:1 in every cohort.** Selecting harder scales *both* tails
by the same factor — ranking on volatility alone lifts the −20% rate from 7.3% to
34.1% and the +20% rate from 3.6% to 16.6%, a 4.7× multiple on each.

And the earlier placebo showed this 2:1 skew exists at random timestamps with no
filing at all. It is a property of the universe, not of any catalyst.

**Volatility predicts magnitude with high reliability. Nothing predicts direction.**

The model is not even a good volatility ranker: picking the most volatile filings
directly beats it (34.1% vs 13.1% hit rate) and the two selections overlap only
23%. It is a volatility ranker wearing a direction model's clothes.

## The short trade, and why it is a trap

Shorting the most volatile decile looks excellent:

| | short return | t |
|---|---|---|
| short everything | +0.85% | +9.01 |
| short the model's bottom decile | +1.75% | +4.57 |
| **short the most volatile decile** | **+4.33%** | **+7.15** |

That is just harvesting the universe's 2:1 downward skew, levered by volatility.
And the +20%/−20% barrier framing **hides the risk that kills it**:

| the same 457 shorts | |
|---|---|
| largest adverse move | **+220%** |
| filings that rose >50% | 24 |
| filings that rose >100% | **10** |
| barrier model says | **+4.33%** |
| **paying the full adverse move** | **−12.64%** |
| worst single short | **−220%** |

A 20% stop does not hold on a microcap that gaps +80% overnight. Ten of 457
positions would have lost more than the entire position. Add borrow at 20–100%
annualised on exactly these names — 0.4–2.0% over five sessions — and a hard-to-
borrow buy-in risk, and the +4.33% is fiction.

## The strategy this actually implies

**There is no rule that distinguishes the +20% from the −20% cases.** I could not
build one, and the reason is structural rather than a failure of features: the
ratio between the tails is constant at 2:1 across every cut of the data, including
cuts with no catalyst at all.

What is reliably predictable is **magnitude**: pre-event volatility takes the
chance of a ≥20% move in either direction from 11% to 51%. Combined with the
earlier finding that a filing pulls a large move ~2 days forward and raises the
odds of a >5% gap from 1.8% to 8.3%, the whole body of evidence says the same
thing:

**this is a volatility signal, not a direction signal.** The instrument that pays
for magnitude without requiring direction is a long straddle, and the instrument
that pays for the 2:1 skew without unbounded risk is a put. Neither is a long
stock position, and neither has been tested here.

Trading it long, which is what was asked, returns **−0.85% per filing** across the
held-out half at every selection threshold tried.
