# Is a scheduled-event option ever cheap?

The constraint that forces this question: an **unscheduled** filing cannot be
timed — a near-dated option bleeds ~8.7% of premium per quiet session while you
wait, against a ~4% daily chance the filing lands. So the event has to be
**scheduled**. But on a scheduled event the premium is priced at the move the
market expects, which is why every buying test so far has failed.

The remaining hope was that the market prices *some* names wrong. If an option
were priced below what that issuer's earnings actually do, buying it would
profit without needing any direction skill at all.

**It never was. Thirty out of thirty were rich.**

## The comparison

An at-the-money straddle costs roughly the implied move, so one leg is about half
of it: `implied move ≈ 2 × (premium / spot)`. Against that, each company's own
history of earnings gaps from its past 8-K item 2.02 filings — **strictly before
the traded event**, since including the event's own gap in its own base rate
would manufacture the answer.

| | |
|---|---|
| trades with ≥3 prior earnings gaps | **30** |
| priced **cheap** vs their own history | **0** |
| priced **rich** | **30** |
| mean implied move charged | **13.1%** |
| mean historical gap for those names | **7.4%** |
| mean gap actually delivered | **8.7%** |
| mean option return | **−3%** |

The market charges about **1.5×** what these events deliver, on every single
name. The least overpriced was Cognex at 0.3pp, then Aurora 1.2pp and Navitas
2.5pp. The most were Avantax 17.0pp, AXT 12.6pp and IREN 10.8pp.

`corr(cheapness, realised − implied) = +0.20` and `corr(cheapness, option
return) = +0.24` both point the right way — the less overpriced an option, the
better it did — but with all thirty on the same side of zero there is no cheap
subset to select. Being *less* overpriced is not the same as being underpriced.

## What this closes

Buying options on scheduled events is now ruled out by three independent
measurements that agree:

1. **2,842 earnings releases**: the market charged 13.7% of spot for a move that
   delivered 9.9%.
2. **The Q1 directional test**: a genuine 61.9%-accurate signal still lost,
   because among correct calls the mean favourable gap (5.7%) equalled the mean
   premium paid (5.7%) exactly.
3. **This**: 30 of 30 names priced above their own demonstrated history.

There is no name selection, no expiry choice, no strike choice and no exit rule
that fixes paying 13.1% for 8.7%. The three tests fail for the same reason and
it is a pricing reason, not a forecasting one.

## What it leaves

If scheduled events are systematically overpriced, the side with the edge is
the **seller**. That was measured separately: across 2,842 releases, selling at
an 11.3% premium returned a mean **+16.5% on margin** at an **84.9%** win rate —
and a worst trade of **−387% of margin**, 3.9× the capital posted, with 1 in 189
losing more than the whole margin.

So the deduction is forced rather than chosen:

* the event must be **scheduled** (unscheduled cannot be timed);
* scheduled events are **overpriced** (30/30 here, and 13.7 vs 9.9 across 2,842);
* overpriced means **sell, not buy**;
* naked selling carries a **−387%** tail;
* therefore **defined-risk selling** — sell the near option, buy a further one as
  a cap. A credit spread or an iron condor keeps the overpricing edge and
  converts the unbounded loss into a known one, at the cost of part of the
  credit.

That structure is the only one consistent with every measurement in this
repository, and it is the one thing never tested.

## Limitations

* 30 trades, one window, one regime. The direction of the overpricing is
  supported by the 2,842-release sample; its size here is not.
* History per name is 3–10 prior earnings, which is a thin base rate.
* Implied move approximated as twice the single-leg premium; a true straddle
  quote would be slightly different and no bid-ask is modelled.
* Overpricing being universal in a sample of thirty does not prove no cheap
  earnings option exists anywhere — only that name-selection on this basis had
  nothing to work with here.

## Reproducing

```
POLYGON_API_KEY=... python3 scripts/implied_vs_history.py
```
