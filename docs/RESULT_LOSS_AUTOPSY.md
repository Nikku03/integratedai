# Why the trades lost

Three causes, each measured on ~160,000 gated rows across fifteen walk-forward
blocks rather than on the 38 live trades. Two of them are fixed. The third is
not fixable by anything tried here, and it is the one that matters.

## First: the ranker used in windows A and B was negative

| ranked inside the gate, walk-forward | gated pool | k=1 | k=3 | blocks k=1 beat the pool |
|---|---|---|---|---|
| REM + surge *(windows A and B)* | −0.03% | **−1.30%** | −0.95% | **5 / 15** |
| **+ context block** *(window C)* | −0.03% | **+0.75%** | +0.57% | **8 / 15** |

The losing trades in the first two windows were not bad luck. **The selection
rule picked losers**, by 1.3pp a trade against a pool that was flat, and it did
so in ten blocks out of fifteen. Every reading layer built on top inherited
that.

Adding the nine tape-derived context columns flips the sign — **+2.05pp at
k=1**, on 160,000 rows. That is by far the largest effect found anywhere in this
line of work, and it is much better evidenced than the 15-trade windows that
prompted it. It is already in the code and was used for window C.

## Second: the objective selects dispersion, not direction

What the q75 model's top decile looks like against the rest (medians):

| | top decile | rest |
|---|---|---|
| price | ~$8 | ~$34 |
| 20-day momentum | **−7.5%** | +1.0% |
| 60-day momentum | **−29.6%** | +1.7% |
| below 52-week high | **−56%** | −20% |
| realised volatility | **109%** | 43% |
| **realised \|return\|** | **15.09%** | 7.56% |
| realised return | +1.08% | +0.07% |

It buys cheap, beaten-down, violent names. It earns about 1pp of mean for that,
and it takes **twice the dispersion** to get it. That asymmetry is visible
directly in the live book: 38 control trades, **win rate 55.3%**, but the
average winner is **+12.56%** and the average loser **−17.55%**. The five worst
trades cost **86.5% of capital** between them.

Sorting every context column by decile, only two carry any direction at all:

| feature | D1 | D10 | D10−D1 | monotone | \|ret\| D10/D1 |
|---|---|---|---|---|---|
| **price (log)** | +1.44% | −1.18% | **−2.62pp** | **−0.87** | 0.65× |
| 60-day momentum | +0.91% | +0.00% | −0.90pp | −0.68 | 0.94× |
| **volatility** | −0.12% | −0.95% | −0.84pp | **0.04** | **4.94×** |
| everything else | | | <1pp | \|·\|<0.35 | |

Volatility sorts realised magnitude **4.9×** and mean return not at all. It is a
pure size signal. Cheapness is the only real direction signal in the block, and
it is worth 2.6pp top-to-bottom.

## Two things that do *not* explain the losses

**"The good news was already priced in."** I offered this after PENG — a record
beat-and-raise, +196% over 60 days, −33.9%. It does not generalise. The model
systematically selects names with **−29.6% median 60-day momentum, 56% below
their highs** — the opposite of extended. And in the live windows, losers and
winners were indistinguishable at entry:

| | 20d mom | 60d mom | from high | vol |
|---|---|---|---|---|
| the 17 losers | −21.9% | −56.7% | −74.4% | 123% |
| the 21 winners | −28.7% | −52.5% | −74.6% | 109% |

PENG was an anecdote and I generalised from it in conversation. The claim never
reached `RESULT_LLM_GATE.md` in its current form — it was dropped when that
document was rewritten for three windows — so there is nothing to retract there;
it is recorded here because it was said, and because the panel shows the
selection runs the other way.

**The reader's judgement.** Of the 17 control losers, 4 were judged negative. Of
the 21 winners, **6** were. Rejecting negatives drops more winners than losers.

## Third: positive expectancy, negative growth rate

This is the finding. The book shrinks *even when the average trade makes money*,
because the return distribution is skewed enough that the mean and the median
disagree about the sign.

`mean log(1+r)` is what compounds. Every configuration tried:

| | mean | median | sd | **compounds at** |
|---|---|---|---|---|
| q75 objective, k=1 *(incumbent)* | +0.75% | −1.76% | 23.1% | **−1.77%** |
| q75, k=3 | +0.57% | −2.23% | 23.9% | −2.01% |
| q75, k=5 | +0.41% | −1.92% | 22.9% | −1.96% |
| q75, k=5, drop top vol quintile | +0.61% | −0.55% | **17.0%** | **−0.75%** |
| mean-of-r objective | +0.68% | −2.31% | 24.2% | −2.02% |
| median-of-log objective | +0.21% | −1.18% | 17.7% | −1.24% |
| **mean-of-log objective, k=1** | **+1.53%** | −1.34% | 23.6% | **−0.82%** |
| log objective, k=1, calm 80% | +0.59% | −0.71% | 15.5% | −0.66% |
| **log objective, k=5, calm 80%** | +0.61% | **−0.25%** | **14.3%** | **−0.33%** |
| log objective, k=10, calm 80% | +0.36% | −0.15% | 12.3% | −0.35% |

Both corrections work, and they compose. Training on `log(1+r)` instead of a q75
quantile **doubles the arithmetic mean** (+0.75% → +1.53%) *and* halves the
drag. Dropping the most volatile quintile before ranking halves it again and
takes the standard deviation from 23.1% to 14.3%. Together they close **81% of
the gap**, from −1.77% to −0.33% per trade.

**None of them crosses zero.** The median trade is negative in every single row
of that table, and the win rate never exceeds 49.2%.

## What this means

The strategy has a positive arithmetic expectancy and a negative geometric one.
That is not a detail — it is the whole reason $40 became $12.40 on the control
arm while the sum of its returns was only −34.5%. You cannot compound something
whose typical trade loses, however good its average is; the average is carried
by a right tail you cannot bet on arriving.

Three honest options remain, and none of them is "read the filings better":

1. **Bet a fraction.** With a negative growth rate at full size, the Kelly
   fraction is negative — there is no positive stake. This is only an option if
   the remaining −0.33% is estimation error, which 1,765 trades says it probably
   is not.
2. **Change what is being predicted.** Everything here forecasts a 10-session
   return whose median is negative inside the gate. The gate itself selects a
   pool whose *median member loses*, which `RESULT_CATALYST_GATE.md` already
   found (buy-all inside the gate: +0.11% against +0.26% ungated). The fix would
   have to be a different pool, not a better sort of this one.
3. **Accept the result.** The catalyst gate concentrates dispersion, and this
   repository has now failed to convert that dispersion into direction across
   seventeen exit rules, eighteen checklist questions, a confidence gate, a
   direction head, a residual model, short interest, Ramanujan partitions, and
   three windows of LLM filing reads.

The one thing worth carrying forward is the +2.05pp from the context block,
because that is measured on 160,000 rows and it is the only change here that
made the sort itself better rather than merely less bad.

## Reproducing

```
python3 scripts/loss_autopsy.py
```
