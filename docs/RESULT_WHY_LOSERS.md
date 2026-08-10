# Why the model picks losing trades

Three candidate explanations, measured on 382,855 scored candidates across 1,760
sessions — about 199 names to choose from each day.

## The pool is never the problem

| per session | mean | median |
|---|---|---|
| **best name available** | **+62.34%** | **+49.71%** |
| our pick | +1.55% | −1.60% |
| the day's median name | +0.02% | +0.22% |
| worst name available | −41.38% | — |

On the 944 sessions where our pick lost — 54% of them — **the best name
available that day averaged +57.68%**, and the share of sessions where *nothing*
was positive was **0.0%**.

There is a +50% winner sitting in the candidate list essentially every single
trading day. The opportunity is always present. Finding it is the entire problem.

## Winners and losers are indistinguishable beforehand

Train a classifier on the picks alone to predict win versus loss:

```
in-sample AUC      0.9961     (pure memorisation)
out-of-sample AUC  0.5302     no better than a coin
```

That is the mechanical reason the eighteen-question checklist failed, and it is
not a property of the checklist. **The two populations have the same feature
distribution.** Nothing built on these 108 features will separate them, because
there is nothing there to separate.

## The model selects convexity, not accuracy

This is the part that reframes everything:

| measure | model | random pick from the same day |
|---|---|---|
| mean outcome percentile within the day | **47.1%** | 50% |
| median outcome percentile | **40.1%** | 50% |
| picked the day's single best name | **3.6%** | 0.5% |
| landed in the day's bottom quartile | **43.1%** | 25% |
| mean return | **+1.55%** | +0.02% |

Read those rows together, because individually they contradict each other.

**On rank, the model is worse than random.** It lands at the 47th percentile on
average and in the bottom quartile 43% of the time against 25% for chance.

**On return, it beats random by +1.53%.** And it picks the outright best name of
the day at **seven times** the chance rate.

Both are true because the return distribution is violently skewed. The model is
not choosing names that are *more likely* to go up; it is choosing names with
*fatter tails in both directions*, which is exactly what a q75 quantile objective
is built to do. It buys convexity and pays for it with a below-median hit rate.

**So the model does not "choose losing trades." It chooses lottery tickets, and
most lottery tickets lose.** The 3.6%-versus-0.5% hit rate on the day's best name
is the entire edge, and it carries the whole +1.349% per trade.

## The score itself is uninformative

Rank correlation between the model's predicted score and the realised return of
its pick: **+0.0093.**

Bucketing the picks by their own predicted score gives means of +1.22%, +1.57%,
−1.52%, +2.32%, +4.15% — non-monotone noise. Only the *within-day ranking*
carries information; the absolute level of the score carries none.

That kills the "only trade when the model is confident" idea for a second time,
and now with a mechanism rather than just a null result.

## What this means

The honest summary of the whole strategy:

1. **There is enormous room.** Perfect selection would return +62% per session.
   The information-theoretic ceiling is not the constraint.
2. **The current features cannot reach it.** Out-of-sample AUC of 0.53 on
   win-versus-lose among the picks means these 108 features are exhausted. Better
   algorithms on the same inputs will not help — that is what the checklist
   failure and the ADRNN's loss to gradient boosting were both telling us.
3. **The edge that exists is convexity, not accuracy.** Do not expect a high win
   rate and do not try to engineer one; every attempt so far has removed the
   tail along with the losses.
4. **The only path forward is new information**, not new modelling. Things not in
   the panel: the actual text and content of the catalyst, short interest and
   days-to-cover, float and lock-up structure, options positioning, ownership
   concentration.

## The uncomfortable framing

The model is right at the 47th percentile of ranks and still profitable. That is
a strategy that survives on rare large wins while being wrong more often than a
coin toss on any individual name. It is a real edge and it is a fragile one — as
the tail anatomy showed, removing a quarter of the winners reverses it entirely.

Anyone sizing this should understand they are buying a lottery with a positive
expected value on this panel, not a stock-picking method.
