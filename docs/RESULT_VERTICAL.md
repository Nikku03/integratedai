# Result: the short vertical fails, and says why every version of this trade fails

Pre-registered in `docs/PREREG_VERTICAL.md`, committed before the window's events
were assembled. Window 2026-08-13 → 2026-09-11. Run with
`scripts/vertical_spread.py` and `scripts/vertical_report.py`.

## What the funnel produced

| step | left |
|---|---|
| 8-K filings over 21 sessions | 4,245 |
| ticker trading ≥$20M/day, held across a bell | 1,142 |
| item 2.02 — a scheduled earnings release | 169 |
| market cap $300M–$20B **and** trailing P/S ≥ 8.0× | 13 |
| signal fired, `\|run_z\| > 0.5` | 10 |
| weekly expiry ≤10 days, two strikes, four marks | **9** |

H4 predicted the sample would be thin and it is: 9 spreads over 5 sessions. One
more, MSGS, was built and dropped — its 460-strike call never traded on the entry
session, which is the same illiquidity the butterfly's edge turned out to live in.

## The result

| | gross | net of $0.05/leg |
|---|---|---|
| mean return on margin | **+0.8%** | **−18.0%** |
| median | +7.4% | −8.8% |
| win rate | 67% | 33% |
| worst trade | −84% | −92% |
| total P&L per share | −0.82 | −2.62 |
| 95% CI on the mean, by session | [−11, +32]% | [−26, +2]% |

Note the two headline numbers disagree in sign: the mean *return* is +0.8% while
the summed *dollars* are −0.82. One trade explains the gap, and it is reported
below rather than averaged away.

**H1 fails.** The gross mean is statistically indistinguishable from zero and the
dollar total is negative.
**H2 fails.** −18.0% net, which is the test that mattered.
**H3 fails, and in the wrong direction.** It predicted a break-even half-spread
of roughly double the butterfly's $0.063. The measured figure is **−$0.023** —
the structure does not break even at *zero* transaction cost, so there is no
positive spread at which it survives.

## The finding: the required edge and the available edge are the same number

This is what the backtest is actually worth, and it does not depend on n = 9.

The credit collected averages **64% of the margin posted**. A trade that pays
0.64 when right and costs 1.00 when wrong needs to be right **61%** of the time
to break even — and that figure assumes every winner keeps the *entire* credit.

The directional signal driving it was measured over 118 events at **61.9%**,
day-clustered CI [53.2, 69.7].

> The market prices the spread so that the win rate it demands is the win rate
> the signal supplies. There is no room left over. That is not a small edge; it
> is the absence of one, and it is priced in deliberately.

Everything real then makes it worse:

* **Winners do not keep the credit.** Mean credit retained across the nine
  spreads was **+6%**; the median was +17%. Not one expired worthless, because
  the exit is the next morning and 7–10 days of time value still has to be bought
  back. Using the actual conditional means (+21.0% on a win, −39.5% on a loss),
  the break-even win rate is **65.3%** against 66.7% observed — a knife edge.
* **Four crossings push it out of reach.** At $0.05 a crossing the required win
  rate becomes **75.0%**, which is outside the signal's entire confidence
  interval.

## And the wing is not a wing

The long leg sits 10% out, which averaged 14.2% of spot here against a mean
absolute gap of 6.6%. That sounds like ample protection. It is not: **2 of 9 gaps
were larger than the wing distance.** HTFL reported and gapped **+26.0%**, blew
through the short call at 30 and past the long at 35, and lost 84% of margin —
the maximum the structure permits. Dropping it alone moves the gross mean from
+0.8% to +11.4%.

Sizing the wing beyond the earnings gap distribution is possible, but a wing far
enough out to be safe costs almost nothing, which returns the position to the
naked short whose worst trade was measured at −387% of margin. The two ends of
that trade-off are both known and neither works.

## Where this leaves the strategy

Both directions are now closed by measurement rather than by argument:

* **Buying** options into scheduled events loses, because the market charges
  13.7% for a move that delivers 9.9%, on 30 of 30 names.
* **Selling** them — naked, four-legged, or two-legged — does not win either,
  because that same 13.7%/9.9% premium is set at precisely the level that pays
  for the directional accuracy available against it.

The reversal signal remains real: 61.9% over 118 events, CI [53.2, 69.7], earned
against a +4.3% SPY tape. The finding here is that **it is real and not tradeable
through weekly options at retail spreads.** Expressing it in the underlying,
where one crossing replaces four and the cost is basis points rather than 5% of a
premium, is the only route these results leave open, and it has not been tested.

## Honest limits

* **Nine trades over five sessions.** The mean return carries no weight on its
  own. The pricing facts — credit as a fraction of margin, credit retained, gaps
  against wing distance — are what the sample supports, and they are what the
  argument above rests on.
* **This window was not blind.** Disclosed in the pre-registration before the
  run: outcomes across 2026-08-17 → 09-11 had been seen in this session. The rule
  is mechanical and was committed first, so knowledge of outcomes could not enter
  it, but this is a consistency check, not independent confirmation.
* **Two marks sit a tick below intrinsic.** DUOT's entry printed at 15:15, 45
  minutes before the bell, at 0.70 against 0.75 of intrinsic; HTFL's exit printed
  9.00 against 9.06. The first understates a loss, the second understates a loss
  too — both push the reported result *better* than the truth, and both are
  within one tick.
* **Every price here is a trade, not a quote.** Polygon's free tier returns 403
  on NBBO, so the cost of crossing is assumed rather than observed. That is why
  the break-even half-spread, not the return, is the reported quantity.
