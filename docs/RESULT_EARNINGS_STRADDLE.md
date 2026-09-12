# Weekly straddles on scheduled events, Q2-2026 earnings season

The unscheduled version of this strategy failed for a reason that was specific:
an 8-K's date is unknowable, a near-dated straddle bleeds ~8.7% of premium per
session while it waits, and with the gap paying ~70% you need roughly a 12%
chance the event lands tomorrow against a base rate near 4%. Earnings fix
exactly that — the date is published weeks ahead — so the strategy is rebuilt on
them, with weekly options only.

**Window** 2026-07-27 → 2026-08-21, the Q2-2026 reporting peak.

## The event calendar

| class | 8-K item | events | issuers | held across a bell |
|---|---|---|---|---|
| **earnings** | 2.02 | **2,935** | 2,883 | **97%** |
| corporate actions | 1.01, 2.01, 5.02, 3.02 | 1,395 | 1,124 | 96% |
| shareholder votes | 5.07 | 175 | 171 | 91% |

97% of earnings releases land outside market hours — 60% after the close, 38%
before the open. That is not luck; issuers release them there deliberately, and
it is what makes the trade expressible at all. A release that lands mid-session
cannot be both positioned for and closed into the gap, and the 77 that did are
dropped rather than approximated.

## The screen

All point-in-time: share count filed before the release, price the close of the
last session that closed before it, revenue as known at that moment.

```
2,935 releases
  2,842  held across a bell with a price on both sides
  1,441  trade at least $20M a day
    566  market cap $300M-$20B
    111  price-to-sales >= 8.0x
     73  both
```

**Coverage caveat, stated before the results:** SEC company-facts were on disk
for **807 of 1,424 filers (57%)**. Fetching stalled twice on oversized responses
and was stopped rather than fought. The 617 missing filers are *invisible* to
this screen, not rejected by it — they were the ones reached last, so this is a
truncation of effort, not a selection on outcome, but it is a real limit.

## Weekly options are the binding constraint

Of the 73 screened events, **52 had no weekly option chain**:

| nearest expiry after the event | events | |
|---|---|---|
| ≤ 10 days (**weekly**) | **21** | traded |
| 11–18 days | 25 | rejected |
| 21–25 days | 26 | rejected |
| no chain at all | 1 | rejected |

Names like Rambus, Repligen, W. P. Carey, Madrigal and Ionis are large, liquid
and heavily traded — and their nearest expiry was 23–25 days out, three times the
premium for the same overnight gap. **Requiring weeklies removes 71% of a
universe that had already passed a liquidity screen.** The cap-and-price-to-sales
screen selects mid-cap narrative stocks; the weekly-options universe is a
different, mostly larger set, and the overlap is thin.

## The number that decides it

A straddle profits when the realised move beats the move already priced in:

```
edge  =  |gap|  -  (call premium + put premium) / spot
```

| | n | market charged | earnings delivered | **edge** | 95% interval | beat the price |
|---|---|---|---|---|---|---|
| priced both ends | 16 | 13.7% | 9.9% | **−3.8pp** | [−8.0, +1.1] | 31% |
| executable only | 5 | 11.3% | 6.2% | **−5.1pp** | [−9.6, +0.7] | 20% |

**Weekly earnings straddles on this universe are priced about 4–5 points above
what earnings actually delivers.** Both intervals span zero on a sample this
size, and both point the same way. `corr(edge, straddle return) = +0.88` —
the edge is the mechanism, not a coincidence of it.

## Every arm, $40 compounded

| arm | n | mean | median | win | compounds | $40 → |
|---|---|---|---|---|---|---|
| all priced | 16 | +5.7% | −5.0% | 44% | +0.1% | **$40.32** |
| **executable only** | **5** | **−6.5%** | −16.3% | 20% | −10.8% | **$22.62** |
| pre-open releases | 2 | −24.4% | — | 0% | −24.8% | $22.63 |
| after-close releases | 3 | +5.3% | −15.4% | 33% | −0.0% | $39.98 |
| held to that close instead | 5 | +1.1% | −30.7% | 20% | −10.8% | $22.62 |
| call leg alone | 5 | −44.5% | −45.0% | 20% | −63.6% | $0.25 |
| put leg alone | 5 | +50.2% | +8.7% | 60% | +24.1% | $117.60 |

The full priced set is a coin — mean +5.7%, median −5.0%, ending where it
started. The subset you could actually have traded lost.

## Where the winners came from

The obvious suspicion is stale marks on thin contracts. **Tested, that is not
what happened.**

| pre-event volume in the strike | n | mean return | mean edge | mean \|gap\| |
|---|---|---|---|---|
| <50 contracts | 3 | +15.5% | −2.0pp | **16.6%** |
| 50–250 | 8 | +9.6% | −3.6pp | 9.8% |
| ≥250 | 5 | −6.5% | −5.1pp | **6.2%** |

`corr(log pre-event volume, return) = −0.12` — weak. The bucket that wins is the
bucket whose *underlying gapped hardest*, which is the same monotone
small-names-move-more relationship measured over the 8-K sample. **The edge is
negative in all three buckets**; it is merely least negative where the gaps are
biggest, because premium does not fall as fast as liquidity does.

The best trade in the set makes the point. Antimony (UAMY) gapped **−17.3%**
against a breakeven of 11.2% and returned **+55%** on a contract that traded 567
contracts beforehand — liquid, and a real winner. The worst, DigitalOcean,
gapped −5.8% against a 17.7% breakeven and lost 45%.

## The ±100% target, resolved

| | |
|---|---|
| straddles with a leg moving ≥100% | 1 of 5 |
| straddles finishing positive | 1 of 5 |
| overlap | 1 |

The target is reachable and it is not the objective. At the money, the winning
leg doubling only replaces the two premiums you paid. What pays is the edge, and
`corr(edge, return) = +0.88` says so directly while the size of the swing does
not.

## What this establishes

1. **The scheduling problem is solved.** Earnings dates are known weeks ahead and
   97% of releases land outside market hours, so the one-session hold that the
   decay maths requires is available. That was the blocker and it is gone.
2. **The pricing problem is not.** The market charges 13.7% for a move that
   averages 9.9%. Earnings straddles are the most heavily studied trade in
   options and this is the direction the literature would predict; nothing here
   contradicts it.
3. **The weekly requirement and this screen barely overlap.** 52 of 73 screened
   names had no weekly chain. Either the screen moves toward larger names where
   weeklies are universal — which is where gaps are smallest — or the strategy
   accepts monthlies and triples its premium. Both directions make the edge worse.

The honest conclusion is that this is a **negative-edge trade as specified**, and
the specification is not obviously fixable by tuning: the two levers (bigger gaps,
cheaper premium) point at opposite ends of the liquidity spectrum.

## Limitations

* **Five executable trades.** The sample is too small to establish the −5.1pp
  edge; it is enough to say nothing here suggests a positive one.
* **No bid-ask.** The Polygon key serves aggregates but returns 403 on NBBO.
  A straddle crosses four spreads round trip. Every figure is an upper bound.
* **One earnings season.** Implied-versus-realised varies across regimes.
* **57% filer coverage** on the fundamental screen, as stated above.
* **Entry is a closing print and exit an opening print**, both of which are the
  last and first *trades*, not quotes.
* Some price-to-sales figures remain suspect for REITs at specific dates —
  Camden Property Trust screens at 902x. It changes which names are selected,
  not whether the straddle mechanism works.

## Reproducing

```
python3 scripts/events_screen.py                                # 2,935 -> 73
POLYGON_API_KEY=... python3 scripts/options_straddle.py --limit 73
python3 scripts/options_straddle_report.py
```
